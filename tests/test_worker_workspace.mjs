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
  }

  prepare(query) {
    const database = this;
    return {
      bind(...values) {
        return {
          async run() {
            if (!query.includes("INSERT INTO console_runs")) throw new Error("unexpected run query");
            const [
              run_id, created_at, updated_at, status, title, turn,
              done_items, total_items, isPublic, workspace_key, payload,
            ] = values;
            database.rows.set(run_id, {
              run_id, created_at, updated_at, status, title, turn,
              done_items, total_items, public: isPublic, workspace_key, payload,
            });
            return { meta: { rows_written: 1 } };
          },
          async all() {
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
            if (query.includes("workspace_key = ?")) {
              const [runId, workspaceKey] = values;
              const row = database.rows.get(runId);
              return row && row.workspace_key === workspaceKey ? { payload: row.payload } : null;
            }
            if (query.includes("public = 1")) {
              const [runId] = values;
              const row = database.rows.get(runId);
              return row?.public === 1 ? { payload: row.payload } : null;
            }
            throw new Error("unexpected detail query");
          },
        };
      },
    };
  }
}

const env = { INBOX: new MemoryD1(), POLL_TOKEN: "workspace-test-secret" };
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
  assert.equal(url, "https://rally-control-plane-u5xngrbzna-ue.a.run.app/v1/me");
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

const publicDetail = await worker.fetch(new Request(
  "https://rally.agent9.dev/v1/console/runs/r-20260831-agent9",
), env, {});
assert.equal(publicDetail.status, 200);
assert.equal((await publicDetail.json()).run_id, "r-20260831-agent9");

console.log("worker workspace isolation contract passed");
