/**
 * Rally ingress.
 *
 * The always-on half of figure 4. Resend delivers inbound mail here; the runner
 * lives on a laptop that sleeps, so mail is held durably until it is collected.
 * A sleeping runner costs latency, never a lost commission.
 *
 * Routes:
 *   POST /inbound/:token   Resend inbound webhook. Stores one message.
 *   GET  /pending          Runner collects undelivered messages. Bearer auth.
 *   POST /ack              Runner confirms handling. Bearer auth.
 *   PUT  /v1/console/runs/:id  Runner publishes an allowlisted run projection.
 *   GET  /v1/console/runs      Public, sanitized judge console feed.
 *   GET  /v1/console/runs/:id Public, sanitized run detail.
 *   POST /admin/google/callback Exact, bounded Google redirect handoff.
 *   GET  /health           Liveness, no auth, no data.
 */

const MAX_BODY = 512 * 1024;
const MAX_CONSOLE_BODY = 96 * 1024;
const MAX_GOOGLE_FORM_BODY = 32 * 1024;
const CONSOLE_ROOT = "/v1/console/runs";
const SITE_ORIGIN = "https://agent9-rally.pages.dev";
const CONTROL_PLANE_ORIGIN = "https://rally-control-plane-u5xngrbzna-ue.a.run.app";
const GOOGLE_CALLBACK_PATH = "/admin/google/callback";
const RUN_ID = /^r-[0-9a-z-]{3,77}$/;
const RUN_STATUSES = new Set(["running", "complete", "blocked", "halted"]);
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

const json = (obj, status = 200, extraHeaders = {}) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: {
      "cache-control": "no-store",
      "content-type": "application/json",
      "x-content-type-options": "nosniff",
      ...extraHeaders,
    },
  });

const publicJson = (obj, status = 200) => json(obj, status, {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "x-rally-data-source": "live",
});

async function serveSite(request, url) {
  const upstreamUrl = new URL(`${url.pathname}${url.search}`, SITE_ORIGIN);
  try {
    // Preserve the response stream and its security/cache headers. Rally's
    // custom domain stays on this Worker so the console API is same-origin,
    // while Cloudflare Pages remains the static asset origin.
    return await fetch(new Request(upstreamUrl, request));
  } catch (error) {
    console.error(JSON.stringify({
      event: "site_origin_failed",
      path: url.pathname,
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ error: "site temporarily unavailable" }, 502);
  }
}

async function proxyGoogleCallback(request) {
  const contentType = request.headers.get("content-type") || "";
  if (!contentType.toLowerCase().startsWith("application/x-www-form-urlencoded")) {
    return json({ error: "unsupported sign-in response" }, 415);
  }
  const raw = await boundedText(request, MAX_GOOGLE_FORM_BODY);
  if (raw === null) return json({ error: "sign-in response too large" }, 413);

  const headers = new Headers({ "content-type": contentType });
  const csrfCookie = (request.headers.get("cookie") || "")
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("g_csrf_token="));
  if (csrfCookie) headers.set("cookie", csrfCookie);
  for (const name of ["user-agent", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const upstream = await fetch(`${CONTROL_PLANE_ORIGIN}/auth/google/callback`, {
      method: "POST",
      headers,
      body: raw,
      redirect: "manual",
    });
    const responseHeaders = new Headers({
      "cache-control": "no-store",
      "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
    });
    for (const name of ["content-type", "location", "pragma", "www-authenticate"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error(JSON.stringify({
      event: "google_callback_failed",
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ error: "sign-in temporarily unavailable" }, 502);
  }
}

const text = (value, limit) =>
  typeof value === "string" ? value.trim().slice(0, limit) : "";

const integer = (value, maximum = 10000) => {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? Math.max(0, Math.min(parsed, maximum)) : 0;
};

async function boundedText(request, maximum) {
  const declared = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(declared) && declared > maximum) return null;
  if (!request.body) return "";

  const reader = request.body.getReader();
  const chunks = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > maximum) {
      await reader.cancel("request body exceeds Rally limit");
      return null;
    }
    chunks.push(value);
  }

  const joined = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(joined);
}

const cleanChanges = (changes) => Array.isArray(changes) ? changes.slice(0, 50).map((item) => ({
  id: text(item?.id, 48),
  state: text(item?.state, 40),
  owner: text(item?.owner, 40) || null,
  verified_by: text(item?.verified_by, 40) || null,
  evidence: text(item?.evidence, 800) || null,
})) : [];

function normalizeConsoleRun(value, expectedRunId) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("body must be an object");
  }
  const runId = text(value.run_id, 80);
  if (!RUN_ID.test(runId) || runId !== expectedRunId) {
    throw new Error("run_id does not match the route");
  }
  const status = text(value.status, 20);
  if (value.schema_version !== 1 || !RUN_STATUSES.has(status)) {
    throw new Error("unsupported console record");
  }
  const createdAt = text(value.created_at, 40);
  const updatedAt = text(value.updated_at, 40);
  if (!TIMESTAMP.test(createdAt) || !TIMESTAMP.test(updatedAt)) {
    throw new Error("created_at and updated_at must be UTC timestamps");
  }
  const checklist = Array.isArray(value.checklist) ? value.checklist.slice(0, 50).map((item) => ({
    id: text(item?.id, 48),
    description: text(item?.description, 500),
    state: text(item?.state, 40),
    owner: text(item?.owner, 40) || null,
    verified_by: text(item?.verified_by, 40) || null,
    evidence: text(item?.evidence, 1200) || null,
    rejections: integer(item?.rejections, 99),
  })) : [];
  const timeline = Array.isArray(value.timeline) ? value.timeline.slice(-100).map((item) => ({
    id: text(item?.id, 100),
    kind: text(item?.kind, 40),
    at: text(item?.at, 40),
    turn: integer(item?.turn, 1000),
    actor: text(item?.actor, 40),
    label: text(item?.label, 100),
    family: text(item?.family, 60),
    model: text(item?.model, 100),
    narrative: text(item?.narrative, 4000),
    commit: text(item?.commit, 64) || null,
    changes: cleanChanges(item?.changes),
  })) : [];
  const agents = Array.isArray(value.agents) ? value.agents.slice(0, 12).map((agent) => ({
    id: text(agent?.id, 40),
    label: text(agent?.label, 100),
    family: text(agent?.family, 60),
    model: text(agent?.model, 100),
    role: text(agent?.role, 100),
    participated: agent?.participated === true,
  })) : [];
  const done = integer(value.progress?.done, 1000);
  const total = integer(value.progress?.total, 1000);
  const independentlyVerified = checklist.filter((item) =>
    item.state === "done" && item.owner && item.verified_by && item.owner !== item.verified_by
  ).length;
  const evidenceReceipts = checklist.filter((item) =>
    item.state === "done" && item.evidence
  ).length;
  const selfApproved = checklist.filter((item) =>
    item.state === "done" && item.owner && item.owner === item.verified_by
  ).length;
  const modelFamilies = new Set(
    agents.filter((agent) => agent.participated).map((agent) => agent.family).filter(Boolean)
  ).size;
  return {
    schema_version: 1,
    visibility: value.visibility === "public" ? "public" : "private",
    run_id: runId,
    title: text(value.title, 120) || runId,
    created_at: createdAt,
    updated_at: updatedAt,
    status,
    status_detail: text(value.status_detail, 160),
    turn: integer(value.turn, 1000),
    next_actor: text(value.next_actor, 40),
    progress: { done: Math.min(done, total), total },
    value_receipt: {
      independently_verified: independentlyVerified,
      evidence_receipts: evidenceReceipts,
      model_families: modelFamilies,
      self_approved: selfApproved,
    },
    policy: {
      invariant: "owner != verified_by",
      enforced_by: "Rally deterministic runner",
      continuity: {
        mode: text(value.policy?.continuity?.mode, 40) || "halt",
        recoveries_used: integer(value.policy?.continuity?.recoveries_used, 8),
        max_recoveries_per_run: integer(value.policy?.continuity?.max_recoveries_per_run, 8),
      },
    },
    coordination: {
      status: text(value.coordination?.status, 60),
      framework: text(value.coordination?.framework, 80) || null,
      services: Array.isArray(value.coordination?.services)
        ? value.coordination.services.slice(0, 8).map((item) => text(item, 80)).filter(Boolean)
        : [],
    },
    agents,
    checklist,
    timeline,
    provenance: {
      source: "Rally authoritative runner state",
      storage: "Cloudflare D1",
      published_at: text(value.provenance?.published_at, 40),
    },
  };
}

/** Hash first so even different-length secrets use a fixed-size comparison. */
async function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const encoder = new TextEncoder();
  const [aHash, bHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(a)),
    crypto.subtle.digest("SHA-256", encoder.encode(b)),
  ]);
  return crypto.subtle.timingSafeEqual(aHash, bHash);
}

function bearer(request) {
  const h = request.headers.get("authorization") || "";
  return h.startsWith("Bearer ") ? h.slice(7) : "";
}

function base64(bytes) {
  let value = "";
  for (const byte of bytes) value += String.fromCharCode(byte);
  return btoa(value);
}

async function signedByResend(request, raw, secret) {
  if (!secret) return false;
  const id = request.headers.get("svix-id") || "";
  const timestamp = request.headers.get("svix-timestamp") || "";
  const signature = request.headers.get("svix-signature") || "";
  const age = Math.abs(Math.floor(Date.now() / 1000) - Number(timestamp));
  if (!id || !timestamp || !Number.isFinite(age) || age > 300) return false;
  const keyBytes = Uint8Array.from(atob(secret.replace(/^whsec_/, "")), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey(
    "raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${id}.${timestamp}.${raw}`));
  const expected = base64(new Uint8Array(digest));
  for (const part of signature.split(" ")) {
    const pieces = part.split(",");
    if (pieces.length === 2 && (await safeEqual(pieces[1], expected))) return true;
  }
  return false;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (path === "/health") {
      return json({ ok: true, service: "rally-ingress" });
    }

    // --- public console --------------------------------------------------
    if (request.method === "OPTIONS" &&
        (path === CONSOLE_ROOT || path.startsWith(CONSOLE_ROOT + "/"))) {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, OPTIONS",
          "access-control-max-age": "86400",
        },
      });
    }

    if (request.method === "GET" && path === CONSOLE_ROOT) {
      try {
        const requested = Number.parseInt(url.searchParams.get("limit") || "12", 10);
        const limit = Number.isFinite(requested) ? Math.max(1, Math.min(requested, 25)) : 12;
        const { results } = await env.INBOX.prepare(
          `SELECT run_id, title, status, created_at, updated_at, turn,
                  done_items, total_items
             FROM console_runs
            WHERE public = 1
            ORDER BY updated_at DESC
            LIMIT ?`
        ).bind(limit).all();
        return publicJson({
          runs: results || [],
          provenance: "live Cloudflare D1",
          generated_at: new Date().toISOString(),
        });
      } catch (error) {
        console.error(JSON.stringify({
          event: "console_list_failed",
          error: error instanceof Error ? error.message : String(error),
        }));
        return publicJson({ error: "console temporarily unavailable" }, 503);
      }
    }

    if (path.startsWith(CONSOLE_ROOT + "/")) {
      const runId = path.slice((CONSOLE_ROOT + "/").length);
      if (!RUN_ID.test(runId)) return publicJson({ error: "not found" }, 404);

      if (request.method === "GET") {
        try {
          const record = await env.INBOX.prepare(
            "SELECT payload FROM console_runs WHERE run_id = ? AND public = 1 LIMIT 1"
          ).bind(runId).first();
          if (!record) return publicJson({ error: "not found" }, 404);
          return publicJson(JSON.parse(record.payload));
        } catch (error) {
          console.error(JSON.stringify({
            event: "console_read_failed",
            run_id: runId,
            error: error instanceof Error ? error.message : String(error),
          }));
          return publicJson({ error: "console temporarily unavailable" }, 503);
        }
      }

      if (request.method === "PUT") {
        if (!(await safeEqual(bearer(request), env.POLL_TOKEN || ""))) {
          return json({ error: "unauthorized" }, 401);
        }
        const raw = await boundedText(request, MAX_CONSOLE_BODY);
        if (raw === null) return json({ error: "too large" }, 413);
        let normalized;
        try {
          normalized = normalizeConsoleRun(JSON.parse(raw), runId);
        } catch (error) {
          return json({ error: error instanceof Error ? error.message : "invalid record" }, 400);
        }
        const payload = JSON.stringify(normalized);
        let result;
        try {
          result = await env.INBOX.prepare(
            `INSERT INTO console_runs
             (run_id, created_at, updated_at, status, title, turn,
              done_items, total_items, public, payload)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(run_id) DO UPDATE SET
             updated_at = excluded.updated_at,
             status = excluded.status,
             title = excluded.title,
             turn = excluded.turn,
             done_items = excluded.done_items,
             total_items = excluded.total_items,
             public = excluded.public,
             payload = excluded.payload`
          ).bind(
            normalized.run_id,
            normalized.created_at,
            normalized.updated_at,
            normalized.status,
            normalized.title,
            normalized.turn,
            normalized.progress.done,
            normalized.progress.total,
            normalized.visibility === "public" ? 1 : 0,
            payload,
          ).run();
        } catch (error) {
          console.error(JSON.stringify({
            event: "console_write_failed",
            run_id: runId,
            error: error instanceof Error ? error.message : String(error),
          }));
          return json({ error: "console write unavailable" }, 503);
        }
        console.log(JSON.stringify({
          event: "console_run_synced",
          run_id: runId,
          status: normalized.status,
          turn: normalized.turn,
          rows_written: result.meta?.rows_written || 0,
        }));
        return json({ ok: true, run_id: runId, updated_at: normalized.updated_at });
      }
    }

    // Same-origin landing point for Google redirect sign-in. Only this exact,
    // bounded form POST is forwarded; the control plane verifies Google's
    // double-submit CSRF token before issuing a one-time exchange code.
    if (request.method === "POST" && path === GOOGLE_CALLBACK_PATH) {
      return proxyGoogleCallback(request);
    }

    // --- inbound from Resend -------------------------------------------
    if (request.method === "POST" && path.startsWith("/inbound/")) {
      const token = path.slice("/inbound/".length);
      if (!(await safeEqual(token, env.INGEST_TOKEN || ""))) {
        return json({ error: "not found" }, 404);
      }
      const raw = await boundedText(request, MAX_BODY);
      if (raw === null) return json({ error: "too large" }, 413);
      if (!(await signedByResend(request, raw, env.RESEND_WEBHOOK_SECRET))) {
        return json({ error: "invalid signature" }, 401);
      }

      let payload;
      try {
        payload = JSON.parse(raw);
      } catch (_) {
        return json({ error: "invalid json" }, 400);
      }

      const id = crypto.randomUUID();
      const eventId = request.headers.get("svix-id") || payload.data?.email_id || id;
      const result = await env.INBOX.prepare(
        "INSERT OR IGNORE INTO messages (id, event_id, received_at, payload) VALUES (?, ?, ?, ?)"
      )
        .bind(id, eventId, new Date().toISOString(), JSON.stringify(payload))
        .run();
      const duplicate = Number(result.meta?.changes || 0) === 0;
      let storedId = id;
      if (duplicate) {
        const existing = await env.INBOX.prepare(
          "SELECT id FROM messages WHERE event_id = ? LIMIT 1"
        ).bind(eventId).first();
        storedId = existing?.id || id;
      }
      console.log(JSON.stringify({
        event: duplicate ? "inbound_duplicate" : "inbound_stored",
        message_id: storedId,
      }));
      return json({ ok: true, id: storedId, duplicate });
    }

    // --- runner collects -------------------------------------------------
    if (path === "/pending" || path === "/ack") {
      if (!(await safeEqual(bearer(request), env.POLL_TOKEN || ""))) {
        return json({ error: "unauthorized" }, 401);
      }
    }

    if (request.method === "GET" && path === "/pending") {
      const { results } = await env.INBOX.prepare(
        "SELECT id, received_at, payload FROM messages ORDER BY received_at ASC LIMIT 25"
      ).all();
      const messages = (results || []).map((r) => ({
        id: r.id,
        received_at: r.received_at,
        payload: JSON.parse(r.payload),
      }));
      return json({ messages });
    }

    if (request.method === "POST" && path === "/ack") {
      let ids = [];
      try {
        const body = await request.json();
        ids = Array.isArray(body.ids) ? [...new Set(body.ids)] : [];
      } catch (_) {
        return json({ error: "invalid json" }, 400);
      }
      if (
        ids.length > 25 ||
        ids.some((id) => typeof id !== "string" || !/^[0-9a-f-]{36}$/i.test(id))
      ) {
        return json({ error: "invalid ids" }, 400);
      }
      if (ids.length) {
        const marks = ids.map(() => "?").join(",");
        await env.INBOX.prepare(`DELETE FROM messages WHERE id IN (${marks})`)
          .bind(...ids)
          .run();
      }
      console.log(JSON.stringify({ event: "messages_acknowledged", count: ids.length }));
      return json({ ok: true, acked: ids.length });
    }

    if (request.method === "GET" || request.method === "HEAD") {
      return serveSite(request, url);
    }

    return json({ error: "not found" }, 404);
  },
};
