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
 *   GET  /health           Liveness, no auth, no data.
 */

const MAX_BODY = 512 * 1024;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });

/** Constant-time-ish comparison, so a token cannot be guessed byte by byte. */
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function bearer(request) {
  const h = request.headers.get("authorization") || "";
  return h.startsWith("Bearer ") ? h.slice(7) : "";
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (path === "/health") {
      return json({ ok: true, service: "rally-ingress" });
    }

    // --- inbound from Resend -------------------------------------------
    if (request.method === "POST" && path.startsWith("/inbound/")) {
      const token = path.slice("/inbound/".length);
      if (!safeEqual(token, env.INGEST_TOKEN || "")) {
        return json({ error: "not found" }, 404);
      }
      const raw = await request.text();
      if (raw.length > MAX_BODY) return json({ error: "too large" }, 413);

      let payload;
      try {
        payload = JSON.parse(raw);
      } catch (_) {
        return json({ error: "invalid json" }, 400);
      }

      const id = crypto.randomUUID();
      await env.INBOX.prepare(
        "INSERT INTO messages (id, received_at, payload) VALUES (?, ?, ?)"
      )
        .bind(id, new Date().toISOString(), JSON.stringify(payload))
        .run();
      return json({ ok: true, id });
    }

    // --- runner collects -------------------------------------------------
    if (path === "/pending" || path === "/ack") {
      if (!safeEqual(bearer(request), env.POLL_TOKEN || "")) {
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
        ids = (await request.json()).ids || [];
      } catch (_) {
        return json({ error: "invalid json" }, 400);
      }
      if (ids.length) {
        const marks = ids.map(() => "?").join(",");
        await env.INBOX.prepare(`DELETE FROM messages WHERE id IN (${marks})`)
          .bind(...ids)
          .run();
      }
      return json({ ok: true, acked: ids.length });
    }

    return json({ error: "not found" }, 404);
  },
};
