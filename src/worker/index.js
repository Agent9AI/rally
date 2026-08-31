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
 *   GET  /v1/workspace/runs    Authenticated, workspace-scoped work queue.
 *   GET  /v1/workspace/runs/:id Authenticated, workspace-scoped run detail.
 *   GET  /v1/workspace/artifacts/:id/:name Authenticated run deliverable.
 *   POST /v1/workspace/jobs    Authenticated manual commission into the inbox.
 *   PUT  /v1/console/artifacts/:id/:name Runner publishes verified bytes.
 *   *    /api/control-plane/*  Allowlisted same-origin browser control-plane gateway.
 *   POST /admin/google/callback Exact, bounded Google redirect handoff.
 *   POST /admin/connect/start/:id Same-origin provider OAuth start and browser binding.
 *   GET  /admin/connect/callback Exact, bounded provider OAuth handoff.
 *   GET  /health           Liveness, no auth, no data.
 */

const MAX_BODY = 512 * 1024;
const MAX_CONSOLE_BODY = 96 * 1024;
const MAX_GOOGLE_FORM_BODY = 32 * 1024;
const MAX_CONNECTOR_START_BODY = 16 * 1024;
const MAX_CONNECTOR_START_RESPONSE = 16 * 1024;
const MAX_CONNECTOR_CALLBACK_QUERY = 12 * 1024;
const MAX_WORKSPACE_IDENTITY_RESPONSE = 16 * 1024;
const MAX_MANUAL_JOB_BODY = 12 * 1024;
const MAX_CONTROL_PLANE_BODY = 32 * 1024;
const MAX_ARTIFACT_BODY = 8 * 1024 * 1024;
const MAX_ARTIFACTS_PER_RUN = 24;
const CONSOLE_ROOT = "/v1/console/runs";
const CONSOLE_ARTIFACT_ROOT = "/v1/console/artifacts";
const WORKSPACE_ROOT = "/v1/workspace/runs";
const WORKSPACE_ARTIFACT_ROOT = "/v1/workspace/artifacts";
const WORKSPACE_JOBS_ROOT = "/v1/workspace/jobs";
const CONTROL_PLANE_PROXY_ROOT = "/api/control-plane";
const SITE_ORIGIN = "https://agent9-rally.pages.dev";
const CONTROL_PLANE_ORIGIN = "https://rally-control-plane-1000134647783.us-east1.run.app";
const GOOGLE_CALLBACK_PATH = "/admin/google/callback";
const CONNECTOR_START_ROOT = "/admin/connect/start/";
const CONNECTOR_CALLBACK_PATH = "/admin/connect/callback";
const CONNECTOR_ID = /^[a-z0-9-]{1,64}$/;
const OAUTH_SECRET = /^[A-Za-z0-9_-]{32,128}$/;
const OAUTH_COOKIE_PREFIX = "__Secure-rally-oauth-";
const RUN_ID = /^r-[0-9a-z-]{3,77}$/;
const ARTIFACT_FILENAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;
const ARTIFACT_KIND = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/;
const USER_ID = /^[A-Za-z0-9._:-]{1,255}$/;
const SIMPLE_EMAIL = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9.-]{1,253}$/;
const DOMAIN_LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const IDEMPOTENCY_KEY = /^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$/;
const SHA256_HEX = /^[0-9a-f]{64}$/;
const RUN_STATUSES = new Set(["running", "complete", "blocked", "halted"]);
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
const ARTIFACT_MIME_TYPES = new Set([
  "application/pdf",
  "audio/mpeg",
  "image/jpeg",
  "image/png",
  "image/webp",
  "text/html",
]);
const ARTIFACT_EXTENSIONS = new Map([
  ["application/pdf", new Set(["pdf"])],
  ["audio/mpeg", new Set(["mp3"])],
  ["image/jpeg", new Set(["jpg", "jpeg"])],
  ["image/png", new Set(["png"])],
  ["image/webp", new Set(["webp"])],
  ["text/html", new Set(["html", "htm"])],
]);

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
    // while Cloudflare Pages remains the static asset origin. Never forward a
    // caller credential or callback cookie across that internal origin hop.
    const headers = new Headers(request.headers);
    for (const name of [
      "authorization",
      "cookie",
      "proxy-authorization",
      "x-rally-id-token",
      "x-rally-oauth-binding",
      "x-rally-session",
    ]) {
      headers.delete(name);
    }
    return await fetch(new Request(upstreamUrl, { method: request.method, headers }));
  } catch (error) {
    console.error(JSON.stringify({
      event: "site_origin_failed",
      path: url.pathname,
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ error: "site temporarily unavailable" }, 502);
  }
}

async function oauthCookieName(state) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(state));
  const suffix = [...new Uint8Array(digest)]
    .slice(0, 16)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `${OAUTH_COOKIE_PREFIX}${suffix}`;
}

function cookieValue(request, name) {
  const prefix = `${name}=`;
  const match = (request.headers.get("cookie") || "")
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return match ? match.slice(prefix.length) : "";
}

function safeUpstreamDetail(value) {
  return typeof value === "string" && /^[A-Za-z0-9 _.-]{1,128}$/.test(value)
    ? value
    : "provider authorization is unavailable";
}

function userAuthHeaders(request) {
  const idToken = request.headers.get("x-rally-id-token") || "";
  const session = request.headers.get("x-rally-session") || "";
  if (Boolean(idToken) === Boolean(session)) return null;
  const headers = new Headers();
  if (/^[A-Za-z0-9._-]{100,16384}$/.test(idToken)) {
    headers.set("x-rally-id-token", idToken);
  } else if (OAUTH_SECRET.test(session)) {
    headers.set("x-rally-session", session);
  } else {
    return null;
  }
  return headers;
}

function normalizedEmail(value) {
  if (typeof value !== "string") return null;
  const email = value.trim().toLowerCase();
  if (!SIMPLE_EMAIL.test(email)) return null;
  const [localPart, domain] = email.split("@");
  if (
    !localPart ||
    localPart.startsWith(".") ||
    localPart.endsWith(".") ||
    localPart.includes("..") ||
    !domain.includes(".") ||
    !domain.split(".").every((label) => DOMAIN_LABEL.test(label))
  ) return null;
  return email;
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function workspaceKey(workspaceId, secret) {
  if (!WORKSPACE_ID.test(workspaceId) || typeof secret !== "string" || !secret) {
    return null;
  }
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, encoder.encode(workspaceId));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function authenticatedWorkspace(request, env) {
  const headers = userAuthHeaders(request);
  if (!headers) return { response: json({ detail: "authentication required" }, 401) };
  let upstream;
  try {
    upstream = await fetch(`${CONTROL_PLANE_ORIGIN}/v1/me`, {
      method: "GET",
      headers,
      redirect: "manual",
    });
  } catch (_) {
    return { response: json({ detail: "workspace authentication is unavailable" }, 502) };
  }
  const raw = await boundedText(upstream, MAX_WORKSPACE_IDENTITY_RESPONSE);
  if (raw === null) {
    return { response: json({ detail: "workspace authentication is unavailable" }, 502) };
  }
  if (!upstream.ok) {
    const status = upstream.status === 401 || upstream.status === 403 ? upstream.status : 502;
    return { response: json({ detail: "authentication required" }, status) };
  }
  let identity;
  try {
    identity = JSON.parse(raw);
  } catch (_) {
    return { response: json({ detail: "workspace authentication is unavailable" }, 502) };
  }
  const workspaceId = typeof identity?.workspace_id === "string"
    ? identity.workspace_id.trim()
    : "";
  // Tenant partition keys must outlive runner credential rotation. Never fall
  // back to POLL_TOKEN: a missing partition secret is safer as a hard outage
  // than silently making historical workspace records disappear.
  const key = await workspaceKey(workspaceId, env.WORKSPACE_KEY_SECRET || "");
  if (!key) {
    return { response: json({ detail: "workspace is not configured" }, 503) };
  }
  const userId = typeof identity?.uid === "string" ? identity.uid.trim() : "";
  return {
    key,
    identity: {
      user_id: USER_ID.test(userId) ? userId : null,
      email: normalizedEmail(identity?.email),
      workspace_id: workspaceId,
    },
  };
}

function controlPlaneProxyRule(method, path) {
  const exact = new Map([
    ["POST /v1/auth/magic-link/request", { auth: "public", body: true }],
    ["POST /v1/auth/magic-link/consume", { auth: "public", body: true }],
    ["POST /v1/auth/exchange", { auth: "public", body: true }],
    ["POST /v1/auth/logout", { auth: "session", body: false }],
    ["GET /v1/me", { auth: "user", body: false }],
    ["GET /v1/email-provider-options", { auth: "user", body: false }],
    ["GET /v1/teammates", { auth: "user", body: false }],
    ["POST /v1/teammates", { auth: "user", body: true }],
    ["GET /v1/connectors", { auth: "user", body: false }],
    ["GET /v1/connections", { auth: "user", body: false }],
  ]);
  const rule = exact.get(`${method} ${path}`);
  if (rule) return rule;

  const connection = path.match(/^\/v1\/connections\/([a-z0-9-]{1,64})(\/verify|\/oauth\/pending)?$/);
  if (!connection) return null;
  const suffix = connection[2] || "";
  if (!suffix && method === "PUT") return { auth: "user", body: true };
  if (!suffix && method === "DELETE") return { auth: "user", body: false };
  if (suffix === "/verify" && method === "POST") return { auth: "user", body: false };
  if (suffix === "/oauth/pending" && method === "DELETE") {
    return { auth: "user", body: false };
  }
  return null;
}

async function proxyControlPlane(request, url, path) {
  const upstreamPath = path.slice(CONTROL_PLANE_PROXY_ROOT.length);
  const rule = controlPlaneProxyRule(request.method, upstreamPath);
  if (!rule || url.search || url.hash) {
    return json({ detail: "control-plane route not found" }, 404);
  }

  const headers = new Headers();
  if (rule.auth === "user") {
    const auth = userAuthHeaders(request);
    if (!auth) return json({ detail: "authentication required" }, 401);
    for (const [name, value] of auth) headers.set(name, value);
  } else if (rule.auth === "session") {
    const session = request.headers.get("x-rally-session") || "";
    if (!OAUTH_SECRET.test(session)) {
      return json({ detail: "authentication required" }, 401);
    }
    headers.set("x-rally-session", session);
  }

  const requestId = request.headers.get("x-request-id") || "";
  if (/^[A-Za-z0-9._:-]{1,128}$/.test(requestId)) {
    headers.set("x-request-id", requestId);
  }

  let body;
  if (rule.body) {
    const contentType = request.headers.get("content-type") || "";
    if (!contentType.toLowerCase().startsWith("application/json")) {
      return json({ detail: "invalid request" }, 415);
    }
    body = await boundedText(request, MAX_CONTROL_PLANE_BODY);
    if (body === null) return json({ detail: "request too large" }, 413);
    headers.set("content-type", "application/json");
  } else if (request.body) {
    return json({ detail: "invalid request" }, 400);
  }

  try {
    const upstream = await fetch(`${CONTROL_PLANE_ORIGIN}${upstreamPath}`, {
      method: request.method,
      headers,
      body,
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
      event: "control_plane_proxy_failed",
      method: request.method,
      path: upstreamPath,
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ detail: "Rally control plane is temporarily unavailable" }, 502);
  }
}

async function proxyConnectorStart(request, connectorId) {
  if (!CONNECTOR_ID.test(connectorId)) {
    return json({ detail: "connector not found" }, 404);
  }
  const contentType = request.headers.get("content-type") || "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    return json({ detail: "invalid connection request" }, 415);
  }
  const raw = await boundedText(request, MAX_CONNECTOR_START_BODY);
  if (raw === null) return json({ detail: "invalid connection request" }, 413);

  const headers = userAuthHeaders(request);
  if (!headers) {
    return json({ detail: "authentication required" }, 401);
  }
  headers.set("content-type", "application/json");

  let upstream;
  try {
    upstream = await fetch(
      `${CONTROL_PLANE_ORIGIN}/v1/connections/${encodeURIComponent(connectorId)}/oauth/start`,
      { method: "POST", headers, body: raw, redirect: "manual" },
    );
  } catch (_) {
    return json({ detail: "provider authorization is unavailable" }, 502);
  }
  const responseText = await boundedText(upstream, MAX_CONNECTOR_START_RESPONSE);
  if (responseText === null) {
    return json({ detail: "provider authorization is unavailable" }, 502);
  }
  let result;
  try {
    result = JSON.parse(responseText);
  } catch (_) {
    return json({ detail: "provider authorization is unavailable" }, 502);
  }
  if (!upstream.ok) {
    return json(
      { detail: safeUpstreamDetail(result?.detail) },
      upstream.status >= 400 && upstream.status < 600 ? upstream.status : 502,
    );
  }

  let authorization;
  try {
    authorization = new URL(result.authorization_url);
  } catch (_) {
    return json({ detail: "provider authorization is unavailable" }, 502);
  }
  const stateValues = authorization.searchParams.getAll("state");
  if (
    result.connector_id !== connectorId ||
    authorization.protocol !== "https:" ||
    authorization.username ||
    authorization.password ||
    authorization.hash ||
    stateValues.length !== 1 ||
    !OAUTH_SECRET.test(stateValues[0]) ||
    !OAUTH_SECRET.test(result.browser_binding || "")
  ) {
    return json({ detail: "provider authorization is unavailable" }, 502);
  }
  const cookieName = await oauthCookieName(stateValues[0]);
  return json(
    {
      connector_id: connectorId,
      authorization_url: authorization.href,
      return_to: "https://rally.agent9.dev/admin/",
    },
    200,
    {
      "referrer-policy": "no-referrer",
      "set-cookie": `${cookieName}=${result.browser_binding}; Max-Age=600; Path=/admin/connect/callback; Secure; HttpOnly; SameSite=Lax`,
    },
  );
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

function safeConnectorReturn(value) {
  try {
    const target = new URL(value);
    if (
      target.origin !== "https://rally.agent9.dev" ||
      target.pathname !== "/admin/" ||
      target.search ||
      target.username ||
      target.password
    ) return null;
    const fragment = new URLSearchParams(target.hash.slice(1));
    const allowed = new Set([
      "rally-login-code",
      "rally-connection",
      "rally-connection-status",
    ]);
    for (const name of fragment.keys()) {
      if (!allowed.has(name) || fragment.getAll(name).length !== 1) return null;
    }
    const loginCode = fragment.get("rally-login-code") || "";
    const connector = fragment.get("rally-connection") || "";
    const status = fragment.get("rally-connection-status") || "";
    if (loginCode && !/^[A-Za-z0-9_-]{32,128}$/.test(loginCode)) return null;
    if (connector && !/^[a-z0-9-]{1,64}$/.test(connector)) return null;
    if (!new Set([
      "ready",
      "verifying",
      "cancelled",
      "needs-attention",
      "disconnect-first",
      "provider-cleanup-required",
      "invalid-or-expired",
    ]).has(status)) {
      return null;
    }
    return target.href;
  } catch (_) {
    return null;
  }
}

function htmlAttribute(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function connectorProgressResponse(upstreamRequest, clearCookie) {
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const shell = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Rally · Securing connection</title><style nonce="${nonce}">:root{color-scheme:light;font-family:Roboto,Arial,sans-serif;color:#10233f;background:#f7f9fc}*{box-sizing:border-box}body{min-height:100vh;margin:0;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 70% 15%,#eaf1ff 0,transparent 38%),#f7f9fc}.shell{width:min(760px,100%);padding:54px;border:1px solid #d9e0ea;border-radius:30px;background:#fff;box-shadow:0 22px 70px rgba(16,35,63,.12)}.brand{display:flex;align-items:center;gap:10px;font-weight:750}.mark{width:38px;height:38px;display:grid;place-items:center;color:#fff;border-radius:12px;background:#246bfd}.eyebrow{margin:50px 0 14px;color:#246bfd;font-size:.72rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}h1{margin:0;font-size:clamp(2.6rem,7vw,4.8rem);font-weight:520;line-height:1;letter-spacing:-.055em}p{max-width:610px;margin:24px 0 0;color:#526178;line-height:1.6}.rail{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:38px}.rail span{padding:11px 8px;text-align:center;color:#617188;border-radius:999px;background:#f0f3f8;font-size:.68rem;font-weight:750}.rail span:nth-child(-n+2){color:#174ea6;background:#e9f0ff}.pulse{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:50%;background:#20a66a;box-shadow:0 0 0 7px rgba(32,166,106,.1);animation:pulse 1.2s ease-in-out infinite}@keyframes pulse{50%{opacity:.4;transform:scale(.78)}}a{display:inline-flex;margin:28px 22px 0 0;color:#246bfd;font-weight:700;text-decoration:none}</style></head><body><main class="shell"><div class="brand"><span class="mark">R</span>Rally</div><p class="eyebrow"><span class="pulse"></span>Secure provider return</p><h1>Approval received.<br>Securing it now.</h1><p>Rally is encrypting the provider grant and returning you to the exact connection card. It will test live access there before enabling any tool.</p><div class="rail" aria-label="Connection progress"><span>Approved</span><span>Encrypted</span><span>Returned</span><span>Tested</span></div><div aria-live="polite">`;
  let body;
  let completed = false;
  try {
    const upstream = await upstreamRequest();
    const target = safeConnectorReturn(upstream.headers.get("location") || "");
    if (upstream.status < 300 || upstream.status >= 400 || !target) {
      throw new Error("invalid control-plane return");
    }
    const escaped = htmlAttribute(target);
    completed = true;
    body = `${shell}<p>Approval secured. Returning you to finish the live connection test…</p><a href="${escaped}">Continue to Rally</a></div><script nonce="${nonce}">window.location.replace(${JSON.stringify(target)});</script></main></body></html>`;
  } catch (error) {
    console.error(JSON.stringify({
      event: "connector_callback_failed",
      error: error instanceof Error ? error.message : String(error),
    }));
    body = `${shell}<p>Rally could not confirm whether this provider return completed. Go back to your connections; if this card is not connected, choose Connect again.</p><a href="/admin/">Return to connections</a></div></main></body></html>`;
  }
  const headers = {
    "cache-control": "no-store",
    "content-security-policy": `default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'`,
    "content-type": "text/html; charset=utf-8",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "x-robots-tag": "noindex, nofollow",
  };
  if (completed) headers["set-cookie"] = clearCookie;
  return new Response(body, {
    status: 200,
    headers,
  });
}

async function proxyConnectorCallback(request, url) {
  if (url.search.length > MAX_CONNECTOR_CALLBACK_QUERY) {
    return json({ error: "authorization response too large" }, 413);
  }
  // OAuth providers may add non-authority response metadata. Google, for
  // example, returns scope/authuser/prompt (and sometimes hd). Rally accepts a
  // fixed singleton allowlist but forwards only code, state, and error.
  const allowed = new Set([
    "code",
    "state",
    "error",
    "error_description",
    "error_uri",
    "scope",
    "authuser",
    "hd",
    "prompt",
    "iss",
    "session_state",
  ]);
  for (const name of url.searchParams.keys()) {
    if (!allowed.has(name) || url.searchParams.getAll(name).length !== 1) {
      return json({ error: "invalid authorization response" }, 400);
    }
  }
  const state = url.searchParams.get("state") || "";
  const code = url.searchParams.get("code") || "";
  const error = url.searchParams.get("error") || "";
  const issuer = url.searchParams.get("iss") || "";
  if (
    !OAUTH_SECRET.test(state) ||
    Boolean(code) === Boolean(error) ||
    code.length > 8192 ||
    error.length > 128 ||
    (error && !/^[A-Za-z0-9_.-]+$/.test(error)) ||
    (issuer && (issuer.length > 2048 || !/^https:\/\/[^\s]+$/.test(issuer)))
  ) {
    return json({ error: "invalid authorization response" }, 400);
  }

  const cookieName = await oauthCookieName(state);
  const browserBinding = cookieValue(request, cookieName);
  const clearCookie = `${cookieName}=; Max-Age=0; Path=/admin/connect/callback; Secure; HttpOnly; SameSite=Lax`;
  return await connectorProgressResponse(() =>
    fetch(`${CONTROL_PLANE_ORIGIN}/auth/connector/callback`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-rally-oauth-binding": browserBinding,
      },
      body: JSON.stringify({
        state,
        code: code || null,
        error: error || null,
        issuer: issuer || null,
      }),
      redirect: "manual",
    }),
    clearCookie,
  );
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

async function boundedBytes(request, maximum) {
  const declared = request.headers.get("content-length") || "";
  if (!/^\d{1,8}$/.test(declared)) return null;
  const expected = Number(declared);
  if (!Number.isSafeInteger(expected) || expected < 1 || expected > maximum || !request.body) {
    return null;
  }

  const reader = request.body.getReader();
  const chunks = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > maximum || length > expected) {
      await reader.cancel("artifact exceeds Rally limit");
      return null;
    }
    chunks.push(value);
  }
  if (length !== expected) return null;

  const joined = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return joined;
}

async function sha256HexBytes(value) {
  const digest = await crypto.subtle.digest("SHA-256", value);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function artifactRoute(path, root) {
  if (!path.startsWith(`${root}/`)) return null;
  const parts = path.slice(root.length + 1).split("/");
  if (parts.length !== 2 || !RUN_ID.test(parts[0])) return null;
  let filename;
  try {
    filename = decodeURIComponent(parts[1]);
  } catch (_) {
    return null;
  }
  if (
    !ARTIFACT_FILENAME.test(filename) ||
    filename.includes("..") ||
    encodeURIComponent(filename) !== parts[1]
  ) return null;
  return { run_id: parts[0], filename };
}

function artifactForFilename(payload, filename, status = null) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.artifacts)) return null;
  return payload.artifacts.find((artifact) =>
    artifact?.filename === filename && (status === null || artifact.status === status)
  ) || null;
}

function artifactObjectKey(workspaceKeyValue, runId, filename) {
  return `${workspaceKeyValue}/${runId}/${filename}`;
}

function visibleRunProjection(payload) {
  const artifacts = Array.isArray(payload?.artifacts)
    ? payload.artifacts
      .filter((artifact) => artifact?.status === "ready")
      .map(({ status: _status, ...artifact }) => artifact)
    : [];
  return { ...payload, artifacts };
}

async function readyArtifactsAreStored(env, workspaceKeyValue, runId, artifacts) {
  const ready = artifacts.filter((artifact) => artifact.status === "ready");
  if (!ready.length) return true;
  if (!env.ARTIFACTS || typeof env.ARTIFACTS.head !== "function") {
    throw new Error("artifact storage unavailable");
  }
  for (const artifact of ready) {
    const object = await env.ARTIFACTS.head(
      artifactObjectKey(workspaceKeyValue, runId, artifact.filename)
    );
    const objectSha256 = object?.checksums?.sha256
      ? hexBytes(object.checksums.sha256)
      : "";
    if (
      !object ||
      object.size !== artifact.size_bytes ||
      object.httpMetadata?.contentType !== artifact.mime_type ||
      object.customMetadata?.workspace_key !== workspaceKeyValue ||
      object.customMetadata?.run_id !== runId ||
      object.customMetadata?.filename !== artifact.filename ||
      object.customMetadata?.sha256 !== artifact.sha256 ||
      (objectSha256 && objectSha256 !== artifact.sha256)
    ) return false;
  }
  return true;
}

function normalizeManualJob(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("body must be an object");
  }
  const allowed = new Set(["title", "goal", "source_run_id", "second_wind"]);
  const keys = Object.keys(value);
  if (
    !Object.hasOwn(value, "title") ||
    !Object.hasOwn(value, "goal") ||
    keys.some((key) => !allowed.has(key))
  ) {
    throw new Error("body contains unsupported fields");
  }
  if (typeof value.title !== "string" || typeof value.goal !== "string") {
    throw new Error("title and goal must be strings");
  }
  const title = value.title.trim();
  const goal = value.goal.trim();
  const unsafeControl = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
  if (!title || title.length > 160 || /[\r\n]/.test(title) || unsafeControl.test(title)) {
    throw new Error("title must be between 1 and 160 characters on one line");
  }
  if (!goal || goal.length > 6000 || unsafeControl.test(goal)) {
    throw new Error("goal must be between 1 and 6000 characters");
  }
  const sourceRunId = value.source_run_id == null ? null : value.source_run_id;
  if (sourceRunId !== null && (typeof sourceRunId !== "string" || !RUN_ID.test(sourceRunId))) {
    throw new Error("source_run_id is invalid");
  }
  if (Object.hasOwn(value, "second_wind") && typeof value.second_wind !== "boolean") {
    throw new Error("second_wind must be a boolean");
  }
  return {
    title,
    goal,
    source_run_id: sourceRunId,
    second_wind: Object.hasOwn(value, "second_wind") ? value.second_wind : null,
  };
}

function acceptedManualJob(envelope, fingerprint, workspaceId) {
  return Boolean(
    envelope &&
    typeof envelope === "object" &&
    !Array.isArray(envelope) &&
    envelope.source === "dashboard" &&
    envelope.schema_version === 1 &&
    RUN_ID.test(envelope.run_id || "") &&
    TIMESTAMP.test(envelope.accepted_at || "") &&
    SHA256_HEX.test(envelope.request_fingerprint || "") &&
    envelope.request_fingerprint === fingerprint &&
    envelope.authority?.workspace_id === workspaceId &&
    typeof envelope.job?.title === "string"
  );
}

function acceptedManualJobResponse(receipt, fingerprint) {
  if (
    !receipt ||
    !RUN_ID.test(receipt.run_id || "") ||
    !TIMESTAMP.test(receipt.created_at || "") ||
    !SHA256_HEX.test(receipt.request_fingerprint || "")
  ) {
    return json({ detail: "job intake is temporarily unavailable" }, 503);
  }
  if (receipt.request_fingerprint !== fingerprint) {
    return json({ detail: "idempotency-key was already used for another job" }, 409);
  }
  return json(
    { run_id: receipt.run_id, status: "accepted", accepted_at: receipt.created_at },
    202,
    { location: `${WORKSPACE_ROOT}/${receipt.run_id}` },
  );
}

function queuedRunProjection(record) {
  const createdAt = TIMESTAMP.test(record?.created_at || "") ? record.created_at : "";
  const updatedAt = TIMESTAMP.test(record?.updated_at || "") ? record.updated_at : createdAt;
  const sourceRunId = RUN_ID.test(record?.source_run_id || "") ? record.source_run_id : null;
  return {
    schema_version: 1,
    visibility: "private",
    run_id: text(record?.run_id, 80),
    title: text(record?.title, 160),
    created_at: createdAt,
    updated_at: updatedAt,
    status: "queued",
    status_detail: "Accepted into Rally and waiting for the runner to begin.",
    turn: 0,
    next_actor: "",
    progress: { done: 0, total: 0 },
    source_run_id: sourceRunId,
    agents: [],
    checklist: [],
    timeline: [],
    provenance: {
      source: "Rally authenticated workspace intake",
      storage: "Cloudflare D1",
      accepted_at: createdAt,
    },
  };
}

async function createManualJob(request, env, workspace) {
  const contentType = request.headers.get("content-type") || "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    return json({ detail: "content-type must be application/json" }, 415);
  }
  const idempotencyKey = request.headers.get("idempotency-key") || "";
  if (!IDEMPOTENCY_KEY.test(idempotencyKey)) {
    return json({ detail: "a valid idempotency-key is required" }, 400);
  }
  if (!workspace.identity?.user_id || !workspace.identity?.email) {
    return json({ detail: "workspace identity is unavailable" }, 503);
  }

  const raw = await boundedText(request, MAX_MANUAL_JOB_BODY);
  if (raw === null) return json({ detail: "job request is too large" }, 413);
  let job;
  try {
    job = normalizeManualJob(JSON.parse(raw));
  } catch (error) {
    return json({ detail: error instanceof Error ? error.message : "invalid job request" }, 400);
  }

  const fingerprint = await sha256Hex(JSON.stringify(job));
  const idempotencyDigest = await sha256Hex(`${workspace.key}\u0000${idempotencyKey}`);
  const eventId = `dashboard:${idempotencyDigest}`;
  const database = typeof env.INBOX.withSession === "function"
    ? env.INBOX.withSession("first-primary")
    : env.INBOX;

  try {
    const receipt = await database.prepare(
      `SELECT run_id, created_at, request_fingerprint
         FROM workspace_jobs
        WHERE event_id = ? AND workspace_key = ?
        LIMIT 1`
    ).bind(eventId, workspace.key).first();
    if (receipt) return acceptedManualJobResponse(receipt, fingerprint);

    // A short-lived deployment of dashboard intake may have accepted a
    // message before this projection table existed. Lazily converge it onto
    // the durable receipt without touching unrelated email envelopes.
    const legacy = await database.prepare(
      "SELECT payload FROM messages WHERE event_id = ? LIMIT 1"
    ).bind(eventId).first();
    if (legacy) {
      let stored;
      try {
        stored = JSON.parse(legacy.payload || "");
      } catch (_) {
        return json({ detail: "job intake is temporarily unavailable" }, 503);
      }
      if (!acceptedManualJob(stored, fingerprint, workspace.identity.workspace_id)) {
        return json({ detail: "idempotency-key was already used for another job" }, 409);
      }
      await database.prepare(
        `INSERT OR IGNORE INTO workspace_jobs
         (run_id, workspace_key, event_id, request_fingerprint, title,
          created_at, updated_at, source_run_id, superseded_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)`
      ).bind(
        stored.run_id,
        workspace.key,
        eventId,
        stored.request_fingerprint,
        stored.job.title,
        stored.accepted_at,
        stored.accepted_at,
        stored.job.source_run_id || null,
      ).run();
      const restored = await database.prepare(
        `SELECT run_id, created_at, request_fingerprint
           FROM workspace_jobs
          WHERE event_id = ? AND workspace_key = ?
          LIMIT 1`
      ).bind(eventId, workspace.key).first();
      return acceptedManualJobResponse(restored, fingerprint);
    }
  } catch (error) {
    console.error(JSON.stringify({
      event: "manual_job_receipt_lookup_failed",
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ detail: "job intake is temporarily unavailable" }, 503);
  }

  if (job.source_run_id) {
    try {
      const source = await database.prepare(
        "SELECT run_id FROM console_runs WHERE run_id = ? AND workspace_key = ? LIMIT 1"
      ).bind(job.source_run_id, workspace.key).first();
      if (!source) return json({ detail: "source run not found" }, 404);
    } catch (error) {
      console.error(JSON.stringify({
        event: "manual_job_source_lookup_failed",
        error: error instanceof Error ? error.message : String(error),
      }));
      return json({ detail: "job intake is temporarily unavailable" }, 503);
    }
  }

  const acceptedAt = new Date().toISOString();
  const runId = `r-${acceptedAt.slice(0, 10).replaceAll("-", "")}-${crypto.randomUUID()}`;
  const messageId = crypto.randomUUID();
  const envelope = {
    source: "dashboard",
    schema_version: 1,
    run_id: runId,
    accepted_at: acceptedAt,
    request_fingerprint: fingerprint,
    job,
    authority: workspace.identity,
  };

  try {
    await database.batch([
      database.prepare(
        "INSERT INTO messages (id, event_id, received_at, payload) VALUES (?, ?, ?, ?)"
      ).bind(messageId, eventId, acceptedAt, JSON.stringify(envelope)),
      database.prepare(
        `INSERT INTO workspace_jobs
         (run_id, workspace_key, event_id, request_fingerprint, title,
          created_at, updated_at, source_run_id, superseded_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)`
      ).bind(
        runId,
        workspace.key,
        eventId,
        fingerprint,
        job.title,
        acceptedAt,
        acceptedAt,
        job.source_run_id,
      ),
    ]);
    console.log(JSON.stringify({
      event: "manual_job_accepted",
      run_id: runId,
    }));
    return acceptedManualJobResponse({
      run_id: runId,
      created_at: acceptedAt,
      request_fingerprint: fingerprint,
    }, fingerprint);
  } catch (error) {
    // Concurrent retries can both miss the initial lookup. The unique event
    // key lets one atomic batch win; the loser replays that durable receipt.
    try {
      const replayDatabase = typeof env.INBOX.withSession === "function"
        ? env.INBOX.withSession("first-primary")
        : env.INBOX;
      const receipt = await replayDatabase.prepare(
        `SELECT run_id, created_at, request_fingerprint
           FROM workspace_jobs
          WHERE event_id = ? AND workspace_key = ?
          LIMIT 1`
      ).bind(eventId, workspace.key).first();
      if (receipt) return acceptedManualJobResponse(receipt, fingerprint);
    } catch (_) {
      // Report the original write failure below without exposing D1 details.
    }
    console.error(JSON.stringify({
      event: "manual_job_write_failed",
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ detail: "job intake is temporarily unavailable" }, 503);
  }
}

const cleanChanges = (changes) => Array.isArray(changes) ? changes.slice(0, 50).map((item) => ({
  id: text(item?.id, 48),
  state: text(item?.state, 40),
  owner: text(item?.owner, 40) || null,
  verified_by: text(item?.verified_by, 40) || null,
  evidence: text(item?.evidence, 800) || null,
})) : [];

function normalizeArtifacts(value) {
  if (value == null) return [];
  if (!Array.isArray(value) || value.length > MAX_ARTIFACTS_PER_RUN) {
    throw new Error(`artifacts must contain at most ${MAX_ARTIFACTS_PER_RUN} items`);
  }
  const filenames = new Set();
  return value.map((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error("artifact metadata must be an object");
    }
    const filename = typeof item.filename === "string" ? item.filename.trim() : "";
    const label = typeof item.label === "string" ? item.label.trim() : "";
    const mimeType = typeof item.mime_type === "string"
      ? item.mime_type.trim().toLowerCase()
      : "";
    const sha256 = typeof item.sha256 === "string" ? item.sha256.trim().toLowerCase() : "";
    const kind = typeof item.kind === "string" ? item.kind.trim().toLowerCase() : "";
    const status = item.status == null
      ? "staged"
      : (typeof item.status === "string" ? item.status.trim().toLowerCase() : "");
    const sizeBytes = Number(item.size_bytes);
    if (
      !ARTIFACT_FILENAME.test(filename) ||
      filename.includes("..") ||
      filenames.has(filename)
    ) throw new Error("artifact filename is invalid or duplicated");
    if (!/^[\x20-\x7e]{1,140}$/.test(label)) {
      throw new Error("artifact label must be printable text up to 140 characters");
    }
    if (!ARTIFACT_MIME_TYPES.has(mimeType)) {
      throw new Error("artifact MIME type is not supported");
    }
    const extension = filename.includes(".") ? filename.split(".").pop().toLowerCase() : "";
    if (!ARTIFACT_EXTENSIONS.get(mimeType)?.has(extension)) {
      throw new Error("artifact filename extension does not match its MIME type");
    }
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 1 || sizeBytes > MAX_ARTIFACT_BODY) {
      throw new Error("artifact size is invalid");
    }
    if (!SHA256_HEX.test(sha256)) throw new Error("artifact sha256 is invalid");
    if (!ARTIFACT_KIND.test(kind)) throw new Error("artifact kind is invalid");
    if (status !== "staged" && status !== "ready") {
      throw new Error("artifact status is invalid");
    }
    filenames.add(filename);
    return {
      filename,
      label,
      mime_type: mimeType,
      size_bytes: sizeBytes,
      sha256,
      kind,
      status,
    };
  });
}

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
  const workspaceId = text(value.workspace_id, 96);
  if (!WORKSPACE_ID.test(workspaceId)) {
    throw new Error("workspace_id is invalid");
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
  const artifacts = normalizeArtifacts(value.artifacts);
  return {
    schema_version: 1,
    workspace_id: workspaceId,
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
    artifacts,
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

function hexBytes(value) {
  return [...new Uint8Array(value)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function publishConsoleArtifact(request, url, env, route) {
  if (url.search) return json({ error: "artifact route does not accept a query" }, 400);
  if (!(await safeEqual(bearer(request), env.POLL_TOKEN || ""))) {
    return json({ error: "unauthorized" }, 401);
  }
  if (!env.ARTIFACTS || typeof env.ARTIFACTS.put !== "function") {
    return json({ error: "artifact storage unavailable" }, 503);
  }

  let record;
  try {
    record = await env.INBOX.prepare(
      "SELECT workspace_key, payload FROM console_runs WHERE run_id = ? LIMIT 1"
    ).bind(route.run_id).first();
  } catch (error) {
    console.error(JSON.stringify({
      event: "artifact_projection_lookup_failed",
      run_id: route.run_id,
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ error: "artifact publication unavailable" }, 503);
  }
  if (!record) return json({ error: "run projection not found" }, 404);

  let projection;
  try {
    projection = JSON.parse(record.payload);
  } catch (_) {
    return json({ error: "run projection is invalid" }, 503);
  }
  const artifact = artifactForFilename(projection, route.filename);
  if (!artifact) return json({ error: "artifact is not declared by this run" }, 404);
  if (artifact.status !== "staged") {
    return json({ error: "artifact is not staged for upload" }, 409);
  }

  const contentType = (request.headers.get("content-type") || "").trim().toLowerCase();
  const declaredSha256 = (request.headers.get("x-rally-artifact-sha256") || "")
    .trim().toLowerCase();
  const declaredKind = (request.headers.get("x-rally-artifact-kind") || "").trim().toLowerCase();
  const declaredLabel = (request.headers.get("x-rally-artifact-label") || "").trim();
  const declaredLength = request.headers.get("content-length") || "";
  if (
    contentType !== artifact.mime_type ||
    declaredSha256 !== artifact.sha256 ||
    declaredKind !== artifact.kind ||
    declaredLabel !== artifact.label ||
    !/^\d{1,8}$/.test(declaredLength) ||
    Number(declaredLength) !== artifact.size_bytes
  ) {
    return json({ error: "artifact metadata does not match the run projection" }, 409);
  }
  if (artifact.size_bytes > MAX_ARTIFACT_BODY) {
    return json({ error: "artifact is too large" }, 413);
  }

  const bytes = await boundedBytes(request, MAX_ARTIFACT_BODY);
  if (!bytes) return json({ error: "artifact body length is invalid" }, 400);
  const actualSha256 = await sha256HexBytes(bytes);
  if (actualSha256 !== artifact.sha256) {
    return json({ error: "artifact checksum verification failed" }, 422);
  }

  const objectKey = artifactObjectKey(record.workspace_key, route.run_id, route.filename);
  let stored;
  try {
    stored = await env.ARTIFACTS.put(objectKey, bytes, {
      sha256: artifact.sha256,
      httpMetadata: {
        contentType: artifact.mime_type,
        contentDisposition: `attachment; filename="${artifact.filename}"`,
        cacheControl: "private, no-store, max-age=0",
      },
      customMetadata: {
        workspace_key: record.workspace_key,
        run_id: route.run_id,
        filename: artifact.filename,
        label: artifact.label,
        kind: artifact.kind,
        sha256: artifact.sha256,
      },
    });
  } catch (error) {
    console.error(JSON.stringify({
      event: "artifact_write_failed",
      run_id: route.run_id,
      filename: route.filename,
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ error: "artifact storage unavailable" }, 503);
  }
  const storedSha256 = stored?.checksums?.sha256
    ? hexBytes(stored.checksums.sha256)
    : "";
  if (
    !stored ||
    stored.size !== artifact.size_bytes ||
    (storedSha256 && storedSha256 !== artifact.sha256)
  ) {
    try {
      await env.ARTIFACTS.delete(objectKey);
    } catch (_) {
      // The object remains unreachable unless both D1 authority and its
      // checksum receipt match. Cleanup failure is logged by the platform.
    }
    return json({ error: "artifact storage verification failed" }, 503);
  }
  console.log(JSON.stringify({
    event: "artifact_published",
    run_id: route.run_id,
    filename: route.filename,
    size_bytes: artifact.size_bytes,
    sha256: artifact.sha256,
  }));
  return json(
    {
      ok: true,
      run_id: route.run_id,
      artifact,
    },
    201,
    { location: `${WORKSPACE_ARTIFACT_ROOT}/${route.run_id}/${encodeURIComponent(route.filename)}` },
  );
}

async function serveWorkspaceArtifact(request, url, env, route) {
  if (url.search) return json({ detail: "artifact route does not accept a query" }, 400);
  const workspace = await authenticatedWorkspace(request, env);
  if (workspace.response) return workspace.response;
  if (!env.ARTIFACTS || typeof env.ARTIFACTS.get !== "function") {
    return json({ detail: "artifact storage is temporarily unavailable" }, 503);
  }

  let record;
  try {
    record = await env.INBOX.prepare(
      "SELECT payload FROM console_runs WHERE run_id = ? AND workspace_key = ? LIMIT 1"
    ).bind(route.run_id, workspace.key).first();
  } catch (error) {
    console.error(JSON.stringify({
      event: "workspace_artifact_projection_failed",
      run_id: route.run_id,
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ detail: "artifact is temporarily unavailable" }, 503);
  }
  if (!record) return json({ detail: "artifact not found" }, 404);

  let projection;
  try {
    projection = JSON.parse(record.payload);
  } catch (_) {
    return json({ detail: "artifact is temporarily unavailable" }, 503);
  }
  const artifact = artifactForFilename(projection, route.filename, "ready");
  if (!artifact) return json({ detail: "artifact not found" }, 404);

  const objectKey = artifactObjectKey(workspace.key, route.run_id, route.filename);
  let object;
  try {
    object = await env.ARTIFACTS.get(objectKey);
  } catch (error) {
    console.error(JSON.stringify({
      event: "workspace_artifact_read_failed",
      run_id: route.run_id,
      filename: route.filename,
      error: error instanceof Error ? error.message : String(error),
    }));
    return json({ detail: "artifact is temporarily unavailable" }, 503);
  }
  if (!object) return json({ detail: "artifact is temporarily unavailable" }, 503);

  const objectSha256 = object.checksums?.sha256 ? hexBytes(object.checksums.sha256) : "";
  if (
    object.size !== artifact.size_bytes ||
    object.httpMetadata?.contentType !== artifact.mime_type ||
    object.customMetadata?.workspace_key !== workspace.key ||
    object.customMetadata?.run_id !== route.run_id ||
    object.customMetadata?.filename !== artifact.filename ||
    object.customMetadata?.sha256 !== artifact.sha256 ||
    (objectSha256 && objectSha256 !== artifact.sha256)
  ) {
    console.error(JSON.stringify({
      event: "workspace_artifact_receipt_mismatch",
      run_id: route.run_id,
      filename: route.filename,
    }));
    return json({ detail: "artifact is temporarily unavailable" }, 503);
  }

  return new Response(object.body, {
    status: 200,
    headers: {
      "cache-control": "private, no-store, max-age=0",
      "content-disposition": `attachment; filename="${artifact.filename}"`,
      "content-length": String(artifact.size_bytes),
      "content-security-policy": "default-src 'none'; sandbox",
      "content-type": artifact.mime_type,
      "cross-origin-resource-policy": "same-origin",
      "etag": object.httpEtag,
      "x-content-type-options": "nosniff",
      "x-rally-artifact-sha256": artifact.sha256,
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (path === "/health") {
      return json({ ok: true, service: "rally-ingress" });
    }

    if (path.startsWith(`${CONTROL_PLANE_PROXY_ROOT}/`)) {
      return proxyControlPlane(request, url, path);
    }

    const consoleArtifact = artifactRoute(path, CONSOLE_ARTIFACT_ROOT);
    if (
      consoleArtifact ||
      path === CONSOLE_ARTIFACT_ROOT ||
      path.startsWith(`${CONSOLE_ARTIFACT_ROOT}/`)
    ) {
      if (!consoleArtifact) return json({ error: "artifact not found" }, 404);
      if (request.method !== "PUT") {
        return json({ error: "method not allowed" }, 405, { allow: "PUT" });
      }
      return publishConsoleArtifact(request, url, env, consoleArtifact);
    }

    // --- authenticated workspace ---------------------------------------
    const workspaceArtifact = artifactRoute(path, WORKSPACE_ARTIFACT_ROOT);
    if (
      workspaceArtifact ||
      path === WORKSPACE_ARTIFACT_ROOT ||
      path.startsWith(`${WORKSPACE_ARTIFACT_ROOT}/`)
    ) {
      if (!workspaceArtifact) return json({ detail: "artifact not found" }, 404);
      if (request.method !== "GET") {
        return json({ detail: "method not allowed" }, 405, { allow: "GET" });
      }
      return serveWorkspaceArtifact(request, url, env, workspaceArtifact);
    }

    if (request.method === "POST" && path === WORKSPACE_JOBS_ROOT) {
      const workspace = await authenticatedWorkspace(request, env);
      if (workspace.response) return workspace.response;
      return createManualJob(request, env, workspace);
    }

    if (request.method === "GET" &&
        (path === WORKSPACE_ROOT || path.startsWith(WORKSPACE_ROOT + "/"))) {
      const workspace = await authenticatedWorkspace(request, env);
      if (workspace.response) return workspace.response;

      if (path === WORKSPACE_ROOT) {
        try {
          const requested = Number.parseInt(url.searchParams.get("limit") || "40", 10);
          const limit = Number.isFinite(requested) ? Math.max(1, Math.min(requested, 100)) : 40;
          const { results } = await env.INBOX.prepare(
            `SELECT run_id, title, status, created_at, updated_at, turn,
                    done_items, total_items
               FROM (
                 SELECT run_id, title, status, created_at, updated_at, turn,
                        done_items, total_items
                   FROM console_runs
                  WHERE workspace_key = ?
                 UNION ALL
                 SELECT run_id, title, 'queued' AS status, created_at, updated_at,
                        0 AS turn, 0 AS done_items, 0 AS total_items
                   FROM workspace_jobs AS queued
                  WHERE workspace_key = ?
                    AND superseded_at IS NULL
                    AND NOT EXISTS (
                      SELECT 1
                        FROM console_runs AS authoritative
                       WHERE authoritative.run_id = queued.run_id
                         AND authoritative.workspace_key = queued.workspace_key
                    )
               )
              ORDER BY updated_at DESC
              LIMIT ?`
          ).bind(workspace.key, workspace.key, limit).all();
          return json({
            runs: results || [],
            provenance: "workspace-scoped Cloudflare D1",
            generated_at: new Date().toISOString(),
          });
        } catch (error) {
          console.error(JSON.stringify({
            event: "workspace_run_list_failed",
            error: error instanceof Error ? error.message : String(error),
          }));
          return json({ detail: "workspace runs are temporarily unavailable" }, 503);
        }
      }

      const runId = path.slice((WORKSPACE_ROOT + "/").length);
      if (!RUN_ID.test(runId)) return json({ detail: "run not found" }, 404);
      try {
        const record = await env.INBOX.prepare(
          "SELECT payload FROM console_runs WHERE run_id = ? AND workspace_key = ? LIMIT 1"
        ).bind(runId, workspace.key).first();
        if (record) return json(visibleRunProjection(JSON.parse(record.payload)));
        const queued = await env.INBOX.prepare(
          `SELECT run_id, title, created_at, updated_at, source_run_id
             FROM workspace_jobs
            WHERE run_id = ? AND workspace_key = ? AND superseded_at IS NULL
            LIMIT 1`
        ).bind(runId, workspace.key).first();
        if (!queued) return json({ detail: "run not found" }, 404);
        return json(queuedRunProjection(queued));
      } catch (error) {
        console.error(JSON.stringify({
          event: "workspace_run_read_failed",
          run_id: runId,
          error: error instanceof Error ? error.message : String(error),
        }));
        return json({ detail: "workspace run is temporarily unavailable" }, 503);
      }
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
          return publicJson(visibleRunProjection(JSON.parse(record.payload)));
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
        const key = await workspaceKey(
          normalized.workspace_id,
          env.WORKSPACE_KEY_SECRET || "",
        );
        if (!key) return json({ error: "workspace projection is unavailable" }, 503);
        try {
          if (!(await readyArtifactsAreStored(env, key, runId, normalized.artifacts))) {
            return json({ error: "ready artifact is not present in verified storage" }, 409);
          }
        } catch (error) {
          console.error(JSON.stringify({
            event: "artifact_readiness_check_failed",
            run_id: runId,
            error: error instanceof Error ? error.message : String(error),
          }));
          return json({ error: "artifact readiness check unavailable" }, 503);
        }
        const { workspace_id: _workspaceId, ...browserRecord } = normalized;
        const payload = JSON.stringify(browserRecord);
        let result;
        try {
          const database = typeof env.INBOX.withSession === "function"
            ? env.INBOX.withSession("first-primary")
            : env.INBOX;
          [result] = await database.batch([
            database.prepare(
              `INSERT INTO console_runs
               (run_id, created_at, updated_at, status, title, turn,
                done_items, total_items, public, workspace_key, payload)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(run_id) DO UPDATE SET
               updated_at = excluded.updated_at,
               status = excluded.status,
               title = excluded.title,
               turn = excluded.turn,
               done_items = excluded.done_items,
               total_items = excluded.total_items,
               public = excluded.public,
               workspace_key = excluded.workspace_key,
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
              key,
              payload,
            ),
            database.prepare(
              `UPDATE workspace_jobs
                  SET superseded_at = COALESCE(superseded_at, ?)
                WHERE run_id = ? AND workspace_key = ?`
            ).bind(new Date().toISOString(), runId, key),
          ]);
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

    // Begin provider consent through Rally's own origin. The Worker keeps the
    // opaque browser binding in a short-lived HttpOnly cookie and never exposes
    // it to page JavaScript.
    if (request.method === "POST" && path.startsWith(CONNECTOR_START_ROOT)) {
      const connectorId = path.slice(CONNECTOR_START_ROOT.length);
      return proxyConnectorStart(request, connectorId);
    }

    // Provider authorization returns here in the same tab. State identifies
    // the flow; the per-flow HttpOnly cookie proves this browser initiated it.
    if (request.method === "GET" && path === CONNECTOR_CALLBACK_PATH) {
      return proxyConnectorCallback(request, url);
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

      // Resend can deliver outbound lifecycle events to the same webhook.
      // They are acknowledged here, never placed ahead of commissions in D1.
      if (!payload || typeof payload !== "object" || payload.type !== "email.received") {
        console.log(JSON.stringify({
          event: "inbound_event_ignored",
          event_type: typeof payload?.type === "string" ? payload.type.slice(0, 80) : "unknown",
        }));
        return json({ ok: true, stored: false });
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
