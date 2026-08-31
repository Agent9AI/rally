import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../src/worker/index.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const worker = (await import(moduleUrl)).default;

const providerCode = "provider-code-that-must-never-reach-page-html";
const providerState = "s".repeat(43);
const loginCode = "l".repeat(43);
let upstreamCalls = 0;
let connectorReturnStatus = "verifying";
let failConnectorCallback = false;
const capturedRequests = [];

globalThis.fetch = async (input, init = {}) => {
  upstreamCalls += 1;
  capturedRequests.push({
    input: input instanceof Request ? input.url : String(input),
    init,
    headers: Object.fromEntries(
      new Headers(input instanceof Request ? input.headers : init.headers || {}).entries(),
    ),
  });
  if ((input instanceof Request ? input.url : String(input)).endsWith(
    "/v1/connections/google-workspace/oauth/start",
  )) {
    return Response.json({
      connector_id: "google-workspace",
      authorization_url:
        `https://accounts.google.com/o/oauth2/v2/auth?client_id=rally&state=${providerState}`,
      browser_binding: "b".repeat(43),
      return_to: "https://rally.agent9.dev/admin/",
    });
  }
  if (
    failConnectorCallback &&
    (input instanceof Request ? input.url : String(input)).endsWith(
      "/auth/connector/callback",
    )
  ) {
    throw new Error("simulated transient control-plane failure");
  }
  return new Response(null, {
    status: 303,
    headers: {
      location:
        `https://rally.agent9.dev/admin/#rally-login-code=${loginCode}` +
        `&rally-connection=google-workspace&rally-connection-status=${connectorReturnStatus}`,
    },
  });
};

const startResponse = await worker.fetch(new Request(
  "https://rally.agent9.dev/admin/connect/start/google-workspace",
  {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-rally-id-token": "i".repeat(120),
    },
    body: JSON.stringify({ endpoint: null, workflow_ids: [] }),
  },
), {}, {});
assert.equal(startResponse.status, 200);
const startCookie = startResponse.headers.get("set-cookie") || "";
assert.match(startCookie, /^__Secure-rally-oauth-[a-f0-9]{32}=/);
assert.match(startCookie, /HttpOnly/);
assert.match(startCookie, /Secure/);
assert.match(startCookie, /SameSite=Lax/);
const startBody = await startResponse.text();
assert.doesNotMatch(startBody, /b{43}/);
assert.equal(upstreamCalls, 1);

const callback = new URL("https://rally.agent9.dev/admin/connect/callback");
callback.searchParams.set("state", providerState);
callback.searchParams.set("code", providerCode);
callback.searchParams.set("scope", "openid email profile");
callback.searchParams.set("authuser", "0");
callback.searchParams.set("hd", "example.com");
callback.searchParams.set("prompt", "consent");
callback.searchParams.set("iss", "https://accounts.google.com");

const response = await worker.fetch(new Request(callback, {
  headers: { cookie: startCookie.split(";", 1)[0] },
}), {}, {});
assert.equal(response.status, 200);
assert.match(response.headers.get("cache-control") || "", /no-store/);
assert.equal(response.headers.get("referrer-policy"), "no-referrer");
assert.match(response.headers.get("content-security-policy") || "", /script-src 'nonce-/);
const html = await response.text();
assert.match(html, /Approval received/);
assert.match(html, /window\.location\.replace/);
assert.doesNotMatch(html, new RegExp(providerCode));
assert.doesNotMatch(html, new RegExp(providerState));
assert.match(response.headers.get("set-cookie") || "", /Max-Age=0/);
assert.equal(upstreamCalls, 2);
const capturedRequest = capturedRequests[1];
assert.equal(
  capturedRequest.input,
  "https://rally-control-plane-1000134647783.us-east1.run.app/auth/connector/callback",
);
assert.deepEqual(JSON.parse(capturedRequest.init.body), {
  state: providerState,
  code: providerCode,
  error: null,
  issuer: "https://accounts.google.com",
});
assert.equal(
  capturedRequest.init.headers["x-rally-oauth-binding"],
  "b".repeat(43),
);

connectorReturnStatus = "provider-cleanup-required";
const cleanupStart = await worker.fetch(new Request(
  "https://rally.agent9.dev/admin/connect/start/google-workspace",
  {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-rally-id-token": "i".repeat(120),
    },
    body: JSON.stringify({ endpoint: null, workflow_ids: [] }),
  },
), {}, {});
const cleanupCallback = await worker.fetch(new Request(callback, {
  headers: { cookie: (cleanupStart.headers.get("set-cookie") || "").split(";", 1)[0] },
}), {}, {});
assert.equal(cleanupCallback.status, 200);
assert.match(await cleanupCallback.text(), /provider-cleanup-required/);
assert.equal(upstreamCalls, 4);

const retryStart = await worker.fetch(new Request(
  "https://rally.agent9.dev/admin/connect/start/google-workspace",
  {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-rally-id-token": "i".repeat(120),
    },
    body: JSON.stringify({ endpoint: null, workflow_ids: [] }),
  },
), {}, {});
const retryCookie = retryStart.headers.get("set-cookie") || "";
failConnectorCallback = true;
const retryableFailure = await worker.fetch(new Request(callback, {
  headers: { cookie: retryCookie.split(";", 1)[0] },
}), {}, {});
failConnectorCallback = false;
assert.equal(retryableFailure.status, 200);
assert.equal(retryableFailure.headers.get("set-cookie"), null);
const uncertainReturn = await retryableFailure.text();
assert.match(uncertainReturn, /could not confirm whether this provider return completed/);
assert.doesNotMatch(uncertainReturn, /Try again/);
assert.equal(upstreamCalls, 6);

const contradictory = new URL(callback);
contradictory.searchParams.set("error", "access_denied");
const rejected = await worker.fetch(new Request(contradictory), {}, {});
assert.equal(rejected.status, 400);
assert.equal(upstreamCalls, 6);

const duplicate = new URL(callback);
duplicate.searchParams.append("scope", "second-value");
const duplicateRejected = await worker.fetch(new Request(duplicate), {}, {});
assert.equal(duplicateRejected.status, 400);
assert.equal(upstreamCalls, 6);

const staticResponse = await worker.fetch(new Request(
  "https://rally.agent9.dev/admin/app.js",
  {
    headers: {
      authorization: "Bearer must-not-cross-origins",
      cookie: "g_csrf_token=must-not-cross-origins",
      "x-rally-id-token": "identity-must-not-cross-origins",
      "x-rally-oauth-binding": "binding-must-not-cross-origins",
      "x-rally-session": "session-must-not-cross-origins",
    },
  },
), {}, {});
assert.equal(staticResponse.status, 303);
const staticProxy = capturedRequests.at(-1);
assert.equal(staticProxy.input, "https://agent9-rally.pages.dev/admin/app.js");
for (const name of [
  "authorization",
  "cookie",
  "proxy-authorization",
  "x-rally-id-token",
  "x-rally-oauth-binding",
  "x-rally-session",
]) {
  assert.equal(staticProxy.headers[name], undefined);
}

console.log("worker callback contract passed");
