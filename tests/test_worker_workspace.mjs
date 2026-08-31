import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// Cloudflare Workers exposes the Web Crypto timingSafeEqual extension. Node's
// Web Crypto does not yet expose it, so the contract test supplies an equivalent
// fixed-length implementation after the Worker hashes both operands.
if (!globalThis.crypto.subtle.timingSafeEqual) {
  globalThis.crypto.subtle.timingSafeEqual = (left, right) => {
    const a = new Uint8Array(left);
    const b = new Uint8Array(right);
    if (a.length !== b.length) return false;
    let difference = 0;
    for (let index = 0; index < a.length; index += 1) difference |= a[index] ^ b[index];
    return difference === 0;
  };
}

const source = await readFile(new URL("../src/worker/index.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const worker = (await import(moduleUrl)).default;

class MemoryD1 {
  constructor() {
    this.rows = new Map();
    this.messages = new Map();
    this.messageByEvent = new Map();
    this.workspaceJobs = new Map();
    this.workspaceJobByEvent = new Map();
    this.failNextWorkspaceJobInsert = false;
  }

  withSession() {
    return this;
  }

  async batch(statements) {
    const snapshot = {
      rows: new Map([...this.rows].map(([key, value]) => [key, { ...value }])),
      messages: new Map([...this.messages].map(([key, value]) => [key, { ...value }])),
      messageByEvent: new Map(this.messageByEvent),
      workspaceJobs: new Map([...this.workspaceJobs].map(([key, value]) => [key, { ...value }])),
      workspaceJobByEvent: new Map(this.workspaceJobByEvent),
    };
    try {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      return results;
    } catch (error) {
      this.rows = snapshot.rows;
      this.messages = snapshot.messages;
      this.messageByEvent = snapshot.messageByEvent;
      this.workspaceJobs = snapshot.workspaceJobs;
      this.workspaceJobByEvent = snapshot.workspaceJobByEvent;
      throw error;
    }
  }

  prepare(query) {
    const database = this;
    return {
      bind(...values) {
        return {
          async run() {
            if (query.includes("INSERT INTO console_runs")) {
              const [
                run_id, created_at, updated_at, status, title, turn,
                done_items, total_items, isPublic, workspace_key, payload,
              ] = values;
              database.rows.set(run_id, {
                run_id, created_at, updated_at, status, title, turn,
                done_items, total_items, public: isPublic, workspace_key, payload,
              });
              return { meta: { rows_written: 1, changes: 1 } };
            }
            if (query.includes("INTO messages")) {
              const [id, event_id, received_at, payload] = values;
              if (database.messageByEvent.has(event_id)) {
                if (query.includes("OR IGNORE")) {
                  return { meta: { rows_written: 0, changes: 0 } };
                }
                throw new Error("UNIQUE constraint failed: messages.event_id");
              }
              database.messages.set(id, { id, event_id, received_at, payload });
              database.messageByEvent.set(event_id, id);
              return { meta: { rows_written: 1, changes: 1 } };
            }
            if (query.includes("INSERT") && query.includes("INTO workspace_jobs")) {
              if (database.failNextWorkspaceJobInsert) {
                database.failNextWorkspaceJobInsert = false;
                throw new Error("injected workspace_jobs write failure");
              }
              const [
                run_id, workspace_key, event_id, request_fingerprint, title,
                created_at, updated_at, source_run_id,
              ] = values;
              const duplicate = database.workspaceJobs.has(run_id) ||
                database.workspaceJobByEvent.has(event_id);
              if (duplicate) {
                if (query.includes("OR IGNORE")) {
                  return { meta: { rows_written: 0, changes: 0 } };
                }
                throw new Error("UNIQUE constraint failed: workspace_jobs.event_id");
              }
              database.workspaceJobs.set(run_id, {
                run_id, workspace_key, event_id, request_fingerprint, title,
                created_at, updated_at, source_run_id, superseded_at: null,
              });
              database.workspaceJobByEvent.set(event_id, run_id);
              return { meta: { rows_written: 1, changes: 1 } };
            }
            if (query.includes("UPDATE workspace_jobs")) {
              const [supersededAt, runId, workspaceKey] = values;
              const job = database.workspaceJobs.get(runId);
              if (!job || job.workspace_key !== workspaceKey) {
                return { meta: { rows_written: 0, changes: 0 } };
              }
              database.workspaceJobs.set(runId, {
                ...job,
                superseded_at: job.superseded_at || supersededAt,
              });
              return { meta: { rows_written: 1, changes: 1 } };
            }
            if (query.includes("DELETE FROM messages")) {
              let changes = 0;
              for (const id of values) {
                const message = database.messages.get(id);
                if (!message) continue;
                database.messages.delete(id);
                database.messageByEvent.delete(message.event_id);
                changes += 1;
              }
              return { meta: { rows_written: changes, changes } };
            }
            throw new Error(`unexpected run query: ${query}`);
          },
          async all() {
            if (query.includes("UNION ALL") && query.includes("workspace_jobs")) {
              const [consoleWorkspaceKey, queuedWorkspaceKey, limit] = values;
              const consoleRows = [...database.rows.values()]
                .filter((row) => row.workspace_key === consoleWorkspaceKey)
                .map(({ payload: _payload, workspace_key: _workspaceKey, public: _public, ...row }) => row);
              const queuedRows = [...database.workspaceJobs.values()]
                .filter((row) => row.workspace_key === queuedWorkspaceKey && row.superseded_at === null)
                .filter((row) => database.rows.get(row.run_id)?.workspace_key !== queuedWorkspaceKey)
                .map((row) => ({
                  run_id: row.run_id,
                  title: row.title,
                  status: "queued",
                  created_at: row.created_at,
                  updated_at: row.updated_at,
                  turn: 0,
                  done_items: 0,
                  total_items: 0,
                }));
              return {
                results: [...consoleRows, ...queuedRows]
                  .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
                  .slice(0, limit),
              };
            }
            if (!query.includes("WHERE workspace_key = ?")) throw new Error("unexpected list query");
            const [workspaceKey, limit] = values;
            const results = [...database.rows.values()]
              .filter((row) => row.workspace_key === workspaceKey)
              .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
              .slice(0, limit)
              .map(({ payload: _payload, workspace_key: _workspaceKey, public: _public, ...row }) => row);
            return { results };
          },
          async first() {
            if (query.includes("FROM workspace_jobs")) {
              if (query.includes("event_id = ?")) {
                const [eventId, workspaceKey] = values;
                const runId = database.workspaceJobByEvent.get(eventId);
                const job = runId ? database.workspaceJobs.get(runId) : null;
                return job?.workspace_key === workspaceKey ? { ...job } : null;
              }
              const [runId, workspaceKey] = values;
              const job = database.workspaceJobs.get(runId);
              return job?.workspace_key === workspaceKey && job.superseded_at === null
                ? { ...job }
                : null;
            }
            if (query.includes("FROM console_runs") && query.includes("workspace_key = ?")) {
              const [runId, workspaceKey] = values;
              const row = database.rows.get(runId);
              if (!row || row.workspace_key !== workspaceKey) return null;
              return query.includes("SELECT run_id")
                ? { run_id: row.run_id }
                : { payload: row.payload };
            }
            if (query.includes("public = 1")) {
              const [runId] = values;
              const row = database.rows.get(runId);
              return row?.public === 1 ? { payload: row.payload } : null;
            }
            if (query.includes("FROM messages WHERE event_id = ?")) {
              const [eventId] = values;
              const id = database.messageByEvent.get(eventId);
              const row = id ? database.messages.get(id) : null;
              if (!row) return null;
              return query.includes("SELECT payload") ? { payload: row.payload } : { id: row.id };
            }
            throw new Error(`unexpected detail query: ${query}`);
          },
        };
      },
    };
  }
}

const resendSigningKey = Buffer.from("rally-test-resend-webhook-key-32b");
const env = {
  INBOX: new MemoryD1(),
  POLL_TOKEN: "workspace-test-secret",
  WORKSPACE_KEY_SECRET: "workspace-test-secret",
  INGEST_TOKEN: "workspace-ingest-token",
  RESEND_WEBHOOK_SECRET: `whsec_${resendSigningKey.toString("base64")}`,
};
const now = "2026-08-31T12:00:00Z";

function projection(runId, workspaceId, visibility = "private") {
  return {
    schema_version: 1,
    workspace_id: workspaceId,
    visibility,
    run_id: runId,
    title: `Run for ${workspaceId}`,
    created_at: now,
    updated_at: now,
    status: "running",
    status_detail: "",
    turn: 1,
    next_actor: "claude",
    progress: { done: 1, total: 3 },
    checklist: [{
      id: "c1", description: "First item", state: "done", owner: "claude",
      verified_by: "agy", evidence: "verified", rejections: 0,
    }],
    agents: [
      { id: "claude", label: "Claude worker", family: "anthropic", model: "sonnet", role: "implementation", participated: true },
      { id: "agy", label: "Gemini worker", family: "google", model: "flash", role: "review", participated: true },
    ],
    timeline: [],
    policy: { continuity: { mode: "halt", recoveries_used: 0, max_recoveries_per_run: 0 } },
    coordination: { status: "ready_for_rally", framework: "Google ADK", services: ["Cloud Run"] },
    provenance: { published_at: now },
  };
}

async function publish(runId, workspaceId, visibility = "private") {
  const response = await worker.fetch(new Request(
    `https://rally.agent9.dev/v1/console/runs/${runId}`,
    {
      method: "PUT",
      headers: {
        authorization: `Bearer ${env.POLL_TOKEN}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(projection(runId, workspaceId, visibility)),
    },
  ), env, {});
  assert.equal(response.status, 200);
}

await publish("r-20260831-agent9", "agent9-rally", "public");
await publish("r-20260831-other", "another-company");

globalThis.fetch = async (input, init = {}) => {
  const url = input instanceof Request ? input.url : String(input);
  assert.equal(url, "https://rally-control-plane-1000134647783.us-east1.run.app/v1/me");
  const headers = new Headers(input instanceof Request ? input.headers : init.headers);
  const session = headers.get("x-rally-session") || "";
  return Response.json({
    uid: session.startsWith("a") ? "admin-one" : "admin-two",
    email: session.startsWith("a") ? "owner@agent9.dev" : "owner@other.dev",
    workspace_id: session.startsWith("a") ? "agent9-rally" : "another-company",
  });
};

const agent9Headers = { "x-rally-session": "a".repeat(43) };
const list = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
  { headers: agent9Headers },
), env, {});
assert.equal(list.status, 200);
const listBody = await list.json();
assert.deepEqual(listBody.runs.map((run) => run.run_id), ["r-20260831-agent9"]);
assert.doesNotMatch(JSON.stringify(listBody), /another-company/);

const detail = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs/r-20260831-agent9",
  { headers: agent9Headers },
), env, {});
assert.equal(detail.status, 200);
const detailBody = await detail.json();
assert.equal(detailBody.run_id, "r-20260831-agent9");
assert.equal(detailBody.workspace_id, undefined);

const crossTenant = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs/r-20260831-other",
  { headers: agent9Headers },
), env, {});
assert.equal(crossTenant.status, 404);

const unauthenticated = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
), env, {});
assert.equal(unauthenticated.status, 401);

const missingWorkspaceSecretEnv = { ...env };
delete missingWorkspaceSecretEnv.WORKSPACE_KEY_SECRET;
const missingWorkspaceSecretList = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
  { headers: agent9Headers },
), missingWorkspaceSecretEnv, {});
assert.equal(missingWorkspaceSecretList.status, 503);
const missingWorkspaceSecretPut = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/console/runs/r-20260831-missing-key",
  {
    method: "PUT",
    headers: {
      authorization: `Bearer ${env.POLL_TOKEN}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(projection("r-20260831-missing-key", "agent9-rally")),
  },
), missingWorkspaceSecretEnv, {});
assert.equal(missingWorkspaceSecretPut.status, 503);

function jobRequest(body, idempotencyKey = "manual-job-request-0001", headers = agent9Headers) {
  return new Request("https://rally.agent9.dev/v1/workspace/jobs", {
    method: "POST",
    headers: {
      ...headers,
      "content-type": "application/json",
      "idempotency-key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });
}

const unauthenticatedJob = await worker.fetch(jobRequest(
  { title: "Prove the workflow", goal: "Produce a verified executive update." },
  "manual-job-request-noauth",
  {},
), env, {});
assert.equal(unauthenticatedJob.status, 401);
assert.equal(env.INBOX.messages.size, 0);

const missingIdempotency = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/jobs",
  {
    method: "POST",
    headers: { ...agent9Headers, "content-type": "application/json" },
    body: JSON.stringify({ title: "Missing request key", goal: "Reject this request." }),
  },
), env, {});
assert.equal(missingIdempotency.status, 400);
assert.equal(env.INBOX.messages.size, 0);

const injectedAuthority = await worker.fetch(jobRequest({
  title: "Spoof another tenant",
  goal: "This must be rejected.",
  workspace_id: "another-company",
}), env, {});
assert.equal(injectedAuthority.status, 400);
assert.equal(env.INBOX.messages.size, 0);

const crossWorkspaceSource = await worker.fetch(jobRequest({
  title: "Continue someone else's run",
  goal: "This must not reveal or attach to the other workspace.",
  source_run_id: "r-20260831-other",
}), env, {});
assert.equal(crossWorkspaceSource.status, 404);
assert.equal(env.INBOX.messages.size, 0);

const invalidJob = await worker.fetch(jobRequest({
  title: "x".repeat(161),
  goal: "Too long a title must fail instead of being silently clipped.",
}), env, {});
assert.equal(invalidJob.status, 400);
assert.equal(env.INBOX.messages.size, 0);

env.INBOX.failNextWorkspaceJobInsert = true;
const atomicFailure = await worker.fetch(jobRequest({
  title: "Do not enqueue half a commission",
  goal: "A projection failure must roll the inbox write back too.",
}, "manual-job-atomic-failure-0001"), env, {});
assert.equal(atomicFailure.status, 503);
assert.equal(env.INBOX.messages.size, 0);
assert.equal(env.INBOX.workspaceJobs.size, 0);

const submittedJob = {
  title: "Prove Rally's email-first workflow",
  goal: "Use the connected workspace, produce evidence, and publish the verified result.",
  source_run_id: "r-20260831-agent9",
  second_wind: true,
};
const accepted = await worker.fetch(jobRequest(submittedJob), env, {});
assert.equal(accepted.status, 202);
const acceptedBody = await accepted.json();
assert.deepEqual(Object.keys(acceptedBody).sort(), ["accepted_at", "run_id", "status"]);
assert.match(acceptedBody.run_id, /^r-\d{8}-[0-9a-f-]{36}$/);
assert.equal(acceptedBody.status, "accepted");
assert.match(acceptedBody.accepted_at, /^\d{4}-\d{2}-\d{2}T/);
assert.equal(accepted.headers.get("location"), `/v1/workspace/runs/${acceptedBody.run_id}`);
assert.equal(env.INBOX.messages.size, 1);
const storedMessage = [...env.INBOX.messages.values()][0];
const storedEnvelope = JSON.parse(storedMessage.payload);
assert.equal(storedEnvelope.source, "dashboard");
assert.equal(storedEnvelope.run_id, acceptedBody.run_id);
assert.deepEqual(storedEnvelope.job, submittedJob);
assert.deepEqual(storedEnvelope.authority, {
  user_id: "admin-one",
  email: "owner@agent9.dev",
  workspace_id: "agent9-rally",
});
assert.doesNotMatch(storedMessage.payload, /another-company/);
assert.equal(env.INBOX.workspaceJobs.size, 1);
const storedJob = env.INBOX.workspaceJobs.get(acceptedBody.run_id);
assert.equal(storedJob.title, submittedJob.title);
assert.equal(storedJob.source_run_id, submittedJob.source_run_id);
assert.equal(storedJob.superseded_at, null);
assert.equal(storedJob.goal, undefined);

const queuedList = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
  { headers: agent9Headers },
), env, {});
assert.equal(queuedList.status, 200);
const queuedListBody = await queuedList.json();
const queuedSummary = queuedListBody.runs.find((run) => run.run_id === acceptedBody.run_id);
assert.deepEqual(queuedSummary, {
  run_id: acceptedBody.run_id,
  title: submittedJob.title,
  status: "queued",
  created_at: acceptedBody.accepted_at,
  updated_at: acceptedBody.accepted_at,
  turn: 0,
  done_items: 0,
  total_items: 0,
});

// A fresh GET models the dashboard reload: queued state comes from D1, not a
// provisional browser object.
const reloadedList = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
  { headers: agent9Headers },
), env, {});
assert.equal((await reloadedList.json()).runs.some(
  (run) => run.run_id === acceptedBody.run_id && run.status === "queued"
), true);

const queuedDetail = await worker.fetch(new Request(
  `https://rally.agent9.dev/v1/workspace/runs/${acceptedBody.run_id}`,
  { headers: agent9Headers },
), env, {});
assert.equal(queuedDetail.status, 200);
const queuedDetailBody = await queuedDetail.json();
assert.equal(queuedDetailBody.status, "queued");
assert.deepEqual(queuedDetailBody.progress, { done: 0, total: 0 });
assert.deepEqual(queuedDetailBody.timeline, []);
assert.equal(queuedDetailBody.source_run_id, submittedJob.source_run_id);
assert.equal(queuedDetailBody.goal, undefined);
assert.equal(queuedDetailBody.authority, undefined);
assert.equal(queuedDetailBody.request_fingerprint, undefined);

const otherWorkspaceList = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
  { headers: { "x-rally-session": "b".repeat(43) } },
), env, {});
assert.equal(otherWorkspaceList.status, 200);
assert.equal((await otherWorkspaceList.json()).runs.some(
  (run) => run.run_id === acceptedBody.run_id
), false);

const replay = await worker.fetch(jobRequest(submittedJob), env, {});
assert.equal(replay.status, 202);
assert.deepEqual(await replay.json(), acceptedBody);
assert.equal(env.INBOX.messages.size, 1);

const idempotencyConflict = await worker.fetch(jobRequest({
  ...submittedJob,
  goal: "A different job may not reuse the same idempotency key.",
}), env, {});
assert.equal(idempotencyConflict.status, 409);
assert.equal(env.INBOX.messages.size, 1);

await publish(acceptedBody.run_id, "agent9-rally");
assert.match(env.INBOX.workspaceJobs.get(acceptedBody.run_id).superseded_at, /^\d{4}-\d{2}-\d{2}T/);
const promotedList = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
  { headers: agent9Headers },
), env, {});
assert.equal(promotedList.status, 200);
const promotedRuns = (await promotedList.json()).runs.filter(
  (run) => run.run_id === acceptedBody.run_id
);
assert.equal(promotedRuns.length, 1);
assert.equal(promotedRuns[0].status, "running");
assert.equal(promotedRuns[0].done_items, 1);
assert.equal(promotedRuns[0].total_items, 3);

const promotedDetail = await worker.fetch(new Request(
  `https://rally.agent9.dev/v1/workspace/runs/${acceptedBody.run_id}`,
  { headers: agent9Headers },
), env, {});
assert.equal(promotedDetail.status, 200);
assert.equal((await promotedDetail.json()).status, "running");

// The hidden receipt survives promotion and inbox acknowledgement, so retries
// keep returning the original run instead of commissioning duplicate work.
const acknowledged = await worker.fetch(new Request(
  "https://rally.agent9.dev/ack",
  {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.POLL_TOKEN}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ ids: [storedMessage.id] }),
  },
), env, {});
assert.equal(acknowledged.status, 200);
assert.equal(env.INBOX.messages.size, 0);

const retiredPollToken = env.POLL_TOKEN;
env.POLL_TOKEN = "workspace-test-secret-rotated";
const listAfterPollRotation = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs",
  { headers: agent9Headers },
), env, {});
assert.equal(listAfterPollRotation.status, 200);
const runsAfterPollRotation = (await listAfterPollRotation.json()).runs;
assert.equal(runsAfterPollRotation.some((run) => run.run_id === "r-20260831-agent9"), true);
assert.equal(runsAfterPollRotation.some((run) => run.run_id === acceptedBody.run_id), true);
const detailAfterPollRotation = await worker.fetch(new Request(
  `https://rally.agent9.dev/v1/workspace/runs/${acceptedBody.run_id}`,
  { headers: agent9Headers },
), env, {});
assert.equal(detailAfterPollRotation.status, 200);
assert.equal((await detailAfterPollRotation.json()).run_id, acceptedBody.run_id);

const retiredBearerPut = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/console/runs/r-20260831-retired-bearer",
  {
    method: "PUT",
    headers: {
      authorization: `Bearer ${retiredPollToken}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(projection("r-20260831-retired-bearer", "agent9-rally")),
  },
), env, {});
assert.equal(retiredBearerPut.status, 401);
await publish("r-20260831-rotated-bearer", "agent9-rally");
const rotatedBearerDetail = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/workspace/runs/r-20260831-rotated-bearer",
  { headers: agent9Headers },
), env, {});
assert.equal(rotatedBearerDetail.status, 200);

const promotedReplay = await worker.fetch(jobRequest(submittedJob), env, {});
assert.equal(promotedReplay.status, 202);
assert.deepEqual(await promotedReplay.json(), acceptedBody);
const promotedConflict = await worker.fetch(jobRequest({
  ...submittedJob,
  goal: "The idempotency receipt still rejects a different job after promotion.",
}), env, {});
assert.equal(promotedConflict.status, 409);
assert.equal(env.INBOX.messages.size, 0);

async function signedWebhook(payload, eventId) {
  const raw = JSON.stringify(payload);
  const timestamp = String(Math.floor(Date.now() / 1000));
  const key = await crypto.subtle.importKey(
    "raw", resendSigningKey, { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const digest = await crypto.subtle.sign(
    "HMAC", key, new TextEncoder().encode(`${eventId}.${timestamp}.${raw}`),
  );
  return new Request("https://rally.agent9.dev/inbound/workspace-ingest-token", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "svix-id": eventId,
      "svix-timestamp": timestamp,
      "svix-signature": `v1,${Buffer.from(digest).toString("base64")}`,
    },
    body: raw,
  });
}

const deliveryEvent = await worker.fetch(await signedWebhook({
  type: "email.delivered",
  created_at: now,
  data: { email_id: "outbound-email-id" },
}, "outbound-delivery-event"), env, {});
assert.equal(deliveryEvent.status, 200);
assert.deepEqual(await deliveryEvent.json(), { ok: true, stored: false });
assert.equal(env.INBOX.messages.size, 0);

const publicDetail = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/console/runs/r-20260831-agent9",
), env, {});
assert.equal(publicDetail.status, 200);
assert.equal((await publicDetail.json()).run_id, "r-20260831-agent9");

console.log("worker workspace isolation contract passed");
