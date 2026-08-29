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
    headers: {
      "cache-control": "no-store",
      "content-type": "application/json",
      "x-content-type-options": "nosniff",
    },
  });

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

    // --- inbound from Resend -------------------------------------------
    if (request.method === "POST" && path.startsWith("/inbound/")) {
      const token = path.slice("/inbound/".length);
      if (!(await safeEqual(token, env.INGEST_TOKEN || ""))) {
        return json({ error: "not found" }, 404);
      }
      const contentLength = Number(request.headers.get("content-length") || "0");
      if (Number.isFinite(contentLength) && contentLength > MAX_BODY) {
        return json({ error: "too large" }, 413);
      }
      const raw = await request.text();
      if (raw.length > MAX_BODY) return json({ error: "too large" }, 413);
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

    return json({ error: "not found" }, 404);
  },
};
