(() => {
  "use strict";

  if (
    window.location.hostname.endsWith(".pages.dev") ||
    window.location.hostname.endsWith(".workers.dev")
  ) {
    window.location.replace(
      `https://rally.agent9.dev${window.location.pathname}${window.location.search}${window.location.hash}`,
    );
    return;
  }

  const config = window.RALLY_ADMIN_CONFIG || {};
  const signedOut = document.querySelector("[data-signed-out]");
  const dashboard = document.querySelector("[data-dashboard]");
  const configurationNote = document.querySelector("[data-configuration-note]");
  const googleButton = document.querySelector("[data-google-button]");
  const signOutButton = document.querySelector("[data-sign-out]");
  const grid = document.querySelector("[data-connection-grid]");
  const dialog = document.querySelector("[data-credential-dialog]");
  const dialogForm = document.querySelector("[data-credential-form]");
  const dialogEyebrow = document.querySelector("[data-dialog-eyebrow]");
  const dialogTitle = document.querySelector("#credential-title");
  const dialogCopy = document.querySelector("[data-dialog-copy]");
  const dialogSubmit = document.querySelector("[data-dialog-submit]");
  const activationRail = document.querySelector("[data-activation-rail]");
  const dialogSafetyCopy = document.querySelector("[data-dialog-safety] p");
  const advancedTokenButton = document.querySelector("[data-advanced-token]");
  const endpointField = document.querySelector("[data-endpoint-field]");
  const endpointInput = document.querySelector("#connector-endpoint");
  const workflowField = document.querySelector("[data-workflow-field]");
  const workflowInput = document.querySelector("#workflow-ids");
  const credentialField = document.querySelector("[data-credential-field]");
  const credentialLabel = document.querySelector("[data-credential-label]");
  const credentialInput = document.querySelector("#credential-value");
  const tokenGuide = document.querySelector("[data-token-guide]");
  const formStatus = document.querySelector("[data-form-status]");
  const connectionCount = document.querySelector("[data-connection-count]");
  const toast = document.querySelector("[data-connection-toast]");
  const signinTitle = document.querySelector("[data-signin-title]");
  const dashboardTitle = document.querySelector("[data-dashboard-title]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let idToken = "";
  let sessionToken = "";
  let activeConnector = null;
  let dialogReturnFocus = null;
  let connectors = new Map();
  let connectionRecords = new Map();

  const configured =
    /^[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$/.test(config.googleClientId || "") &&
    /^https:\/\//.test(config.apiBase || "");

  function safeApiBase() {
    const url = new URL(config.apiBase);
    if (url.protocol !== "https:") throw new Error("Rally control plane is not secure");
    return url.href.replace(/\/$/, "");
  }

  function safeExternalUrl(value) {
    const url = new URL(value);
    if (url.protocol !== "https:") throw new Error("Provider returned an unsafe URL");
    return url.href;
  }

  const safeErrors = {
    endpoint_required: "Enter the MCP server URL from your provider settings.",
    endpoint_invalid: "That is not a valid HTTPS MCP server URL.",
    endpoint_not_allowed: "That URL is outside this connector’s verified provider boundary.",
    credential_invalid: "Use a valid provider credential without spaces or line breaks.",
    credential_scheme_not_allowed: "That credential type is not enabled for this connector.",
    account_required: "Enter the provider account email associated with this credential.",
    policy_configuration_required: "Add at least one approved n8n workflow ID.",
    policy_scope_invalid: "Check the workflow IDs and try again.",
    canary_unavailable: "The provider did not expose Rally's fixed safe-read check.",
    canary_schema_invalid: "The provider returned an unexpected tool contract.",
    canary_failed: "Authorization worked, but the safe live read did not pass.",
    capability_check_failed: "Authorization worked, but the provider returned an invalid tool catalog.",
    safe_preset_mismatch: "Authorization worked, but none of the live tools matched Rally’s safe policy.",
    verification_failed: "The provider did not complete Rally’s safe connection test. Try again in a moment.",
    verification_timeout: "The provider took too long to answer. Your approval remains secure; choose Finish setup to retry the test.",
    recertification_required: "This connection predates live-read certification. Reconnect it once to upgrade the proof.",
    reconnect_required: "Provider access changed or expired. Disconnect it, then connect again.",
    disconnect_pending: "Rally has disabled every tool while provider access is being removed.",
    connection_busy: "A safe read is finishing. Rally kept the connection sealed; try again in a moment.",
    connection_changed: "The connection changed while Rally was working. Refresh the card and try again.",
    disconnect_existing_connection: "Disconnect the existing connection before authorizing a replacement.",
    oauth_in_progress: "A previous connection request is still pending. Cancel that safe handshake before starting again.",
    "provider authorization is unavailable": "The provider’s authorization service is temporarily unavailable. Nothing was enabled; try again shortly.",
    "provider revocation did not complete; the connection remains sealed": "The provider did not confirm revocation, so Rally kept the encrypted credential sealed and every tool disabled. Try disconnecting again.",
  };

  function safeErrorMessage(code, fallback) {
    return safeErrors[code] || fallback;
  }

  const retryableVerificationErrors = new Set([
    "verification_timeout",
    "verification_failed",
    "capability_check_failed",
    "canary_unavailable",
    "canary_failed",
  ]);

  function canFinishSetup(record) {
    if (!record || record.credential_kind !== "oauth_refresh_token") return false;
    if (record.status === "stored_unverified" || record.status === "verifying") return true;
    return record.status === "needs_attention" && retryableVerificationErrors.has(record.error_code || "");
  }

  function requiresReconnect(record) {
    return Boolean(
      record &&
      record.credential_kind === "oauth_refresh_token" &&
      record.status === "needs_attention" &&
      record.error_code !== "disconnect_pending" &&
      !canFinishSetup(record),
    );
  }

  function focusSoon(element) {
    window.requestAnimationFrame(() => element?.focus({ preventScroll: true }));
  }

  async function api(path, options = {}) {
    if (!idToken && !sessionToken) throw new Error("Sign in again to continue");
    const headers = new Headers(options.headers || {});
    if (idToken) headers.set("X-Rally-ID-Token", idToken);
    if (sessionToken) headers.set("X-Rally-Session", sessionToken);
    if (options.body) headers.set("Content-Type", "application/json");
    const response = await fetch(`${safeApiBase()}${path}`, { ...options, headers });
    if (response.status === 401) {
      resetSession("Your Google session expired. Sign in again.");
      const error = new Error("Your Google session expired. Sign in again.");
      error.code = "authentication_required";
      throw error;
    }
    if (!response.ok) {
      let detail = "";
      try {
        detail = (await response.json()).detail || "";
      } catch (_) {
        // The public error remains intentionally generic.
      }
      const error = new Error(safeErrorMessage(detail, "Rally could not complete that secure request"));
      error.code = detail;
      throw error;
    }
    return response.json();
  }

  async function startOAuthApi(connectorId, body) {
    if (!idToken && !sessionToken) throw new Error("Sign in again to continue");
    const headers = new Headers({ "Content-Type": "application/json" });
    if (idToken) headers.set("X-Rally-ID-Token", idToken);
    if (sessionToken) headers.set("X-Rally-Session", sessionToken);
    const response = await fetch(
      `/admin/connect/start/${encodeURIComponent(connectorId)}`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        credentials: "same-origin",
      },
    );
    if (response.status === 401) {
      resetSession("Your Google session expired. Sign in again.");
      const error = new Error("Your Google session expired. Sign in again.");
      error.code = "authentication_required";
      throw error;
    }
    if (!response.ok) {
      let detail = "";
      try {
        detail = (await response.json()).detail || "";
      } catch (_) {
        // The public error remains intentionally generic.
      }
      const error = new Error(
        safeErrorMessage(detail, "Rally could not open secure provider consent"),
      );
      error.code = detail;
      throw error;
    }
    return response.json();
  }

  function resetSession(message = "") {
    idToken = "";
    sessionToken = "";
    if (dialog.open) dialog.close();
    clearDialog();
    dialogReturnFocus = null;
    signedOut.hidden = false;
    dashboard.hidden = true;
    signOutButton.hidden = true;
    configurationNote.textContent = message;
    if (window.google?.accounts?.id) window.google.accounts.id.disableAutoSelect();
    focusSoon(signinTitle);
  }

  function setAccount(account) {
    document.querySelector("[data-user-name]").textContent = account.name || "Rally administrator";
    document.querySelector("[data-user-email]").textContent = account.email || "";
    document.querySelector("[data-user-initial]").textContent = (account.name || account.email || "R").charAt(0).toUpperCase();
    const picture = document.querySelector("[data-user-picture]");
    if (account.picture && /^https:\/\/lh3\.googleusercontent\.com\//.test(account.picture)) {
      picture.src = account.picture;
      picture.hidden = false;
      document.querySelector("[data-user-initial]").hidden = true;
    }
  }

  function cardState(item, record) {
    if (record?.status === "ready") {
      return record.certification?.live_read ? "Certified · live read passed" : "Recertify";
    }
    if (record?.error_code === "disconnect_pending") return "Disconnect pending";
    if (canFinishSetup(record)) return "Safe test needs attention";
    if (requiresReconnect(record)) return "Reconnect required";
    if (record?.status === "needs_attention") {
      return record.credential_kind === "oauth_refresh_token" ? "Reconnect required" : "Replace required";
    }
    if (record?.status === "verifying") return "Awaiting safe test";
    if (record) return "Not certified";
    if (!item?.activation_available || item?.readiness === "provider_app") return "Coming soon";
    return "Ready to connect";
  }

  function primaryLabel(item, record) {
    if (canFinishSetup(record)) return "Finish setup";
    if (record?.error_code === "disconnect_pending") return "Retry disconnect";
    if (requiresReconnect(record)) return "Disconnect & reconnect";
    if (record?.status === "ready") return "Disconnect";
    if (record?.status === "needs_attention") return "Disconnect & replace";
    if (record) return "Disconnect";
    if (!item?.activation_available || item?.readiness === "provider_app") return "Not available yet";
    return "Connect";
  }

  function updateCards(records) {
    connectionRecords = new Map(records.map((record) => [record.connector_id, record]));
    document.querySelectorAll("[data-connector]").forEach((card) => {
      const item = connectors.get(card.dataset.connector);
      const record = connectionRecords.get(card.dataset.connector);
      const state = card.querySelector(".connection-state");
      const primary = card.querySelector("[data-primary-action]");
      const heading = card.querySelector("h3");
      const description = card.querySelector(":scope > p");
      const semanticId = item?.id || card.dataset.connector;
      heading.id = `connection-${semanticId}-title`;
      description.id = `connection-${semanticId}-description`;
      state.id = `connection-${semanticId}-state`;
      card.setAttribute("aria-labelledby", heading.id);
      card.setAttribute("aria-describedby", `${description.id} ${state.id}`);
      primary.setAttribute("aria-describedby", `${state.id} ${description.id}`);
      card.classList.toggle("is-secured", record?.status === "ready");
      card.classList.toggle("needs-attention", record?.status === "needs_attention");
      card.classList.toggle("is-verifying", record?.status === "verifying");
      // A persisted `verifying` record means work is ready to resume, not that a
      // request is currently in flight.  The active verifier sets this to true.
      card.setAttribute("aria-busy", "false");
      state.textContent = cardState(item, record);
      primary.textContent = primaryLabel(item, record);
      primary.disabled = !record && (!item?.activation_available || item?.readiness === "provider_app");
    });
    connectionCount.textContent = String(
      records.filter((record) => record.status === "ready" && record.certification?.live_read).length,
    );
  }

  async function showDashboard(account, { focusHeading = true } = {}) {
    const [catalog, stored] = await Promise.all([
      api("/v1/connectors"),
      api("/v1/connections"),
    ]);
    connectors = new Map((catalog.connectors || []).map((item) => [item.id, item]));
    setAccount(account);
    updateCards(stored.connections || []);
    signedOut.hidden = true;
    dashboard.hidden = false;
    signOutButton.hidden = false;
    if (focusHeading) focusSoon(dashboardTitle);
  }

  async function finishSignIn(credential) {
    idToken = credential;
    sessionToken = "";
    const account = await api("/v1/me");
    await showDashboard(account, { focusHeading: true });
  }

  function takeRedirectState() {
    if (!window.location.hash) return {};
    const state = new URLSearchParams(window.location.hash.slice(1));
    const redirect = {
      code: state.get("rally-login-code") || "",
      error: state.get("rally-login-error") || "",
      connector: state.get("rally-connection") || "",
      connectionStatus: state.get("rally-connection-status") || "",
    };
    if (Object.values(redirect).some(Boolean)) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }
    return redirect;
  }

  async function exchangeRedirectCode(code) {
    configurationNote.textContent = "Restoring your secure Rally session…";
    const response = await fetch(`${safeApiBase()}/v1/auth/exchange`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!response.ok) throw new Error("That return link expired or was already used. Sign in again.");
    const result = await response.json();
    if (
      !result ||
      typeof result.session_token !== "string" ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(result.session_token) ||
      !result.account
    ) {
      throw new Error("Rally received an invalid sign-in response. Try again.");
    }
    idToken = "";
    sessionToken = result.session_token;
    await showDashboard(result.account, { focusHeading: false });
  }

  function showToast(message, tone = "success") {
    toast.textContent = message;
    toast.dataset.tone = tone;
    toast.hidden = false;
    window.clearTimeout(showToast.timeout);
    showToast.timeout = window.setTimeout(() => { toast.hidden = true; }, 7000);
  }

  function revealConnector(connectorId, status) {
    const card = document.querySelector(`[data-connector="${CSS.escape(connectorId)}"]`);
    const name = connectors.get(connectorId)?.name || "Connection";
    if (status === "ready") {
      const count = connectionRecords.get(connectorId)?.tool_count || 0;
      showToast(`${name} is certified. Rally matched ${count || "its"} approved tools and passed its fixed safe live read.`);
    } else if (status === "cancelled") {
      showToast(`${name} authorization was cancelled. Nothing was enabled.`, "neutral");
    } else if (status === "needs-attention") {
      const detail = connectionRecords.get(connectorId)?.error_code || "";
      const guidance = safeErrorMessage(
        detail,
        "The provider returned, but its live capability check did not pass.",
      );
      showToast(`${name} was not enabled. ${guidance} Every tool remains off.`, "warning");
    } else if (status === "invalid-or-expired") {
      showToast("That authorization return expired. Start the connection again.", "warning");
    } else if (status === "verifying") {
      showToast(`${name} approved access. Rally is testing the exact tools it may use now.`, "neutral");
    } else if (status === "disconnect-first") {
      showToast(`${name} is still connected. Disconnect it before authorizing a replacement; the existing grant was not changed.`, "warning");
    } else if (status === "provider-cleanup-required") {
      showToast(`Rally could not confirm revocation of the ${name} approval. Open ${name} security settings and revoke Rally before trying again. No Rally tool was enabled.`, "warning");
    }
    if (!card) return;
    card.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "center" });
    card.classList.add("is-returned");
    card.querySelector("[data-primary-action]")?.focus({ preventScroll: true });
    window.setTimeout(() => card.classList.remove("is-returned"), 5000);
  }

  function installGoogleSignIn() {
    if (!configured) {
      configurationNote.textContent = "Secure sign-in is waiting for the Rally Google web client.";
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.addEventListener("load", () => {
      window.google.accounts.id.initialize({
        client_id: config.googleClientId,
        callback: async ({ credential }) => {
          configurationNote.textContent = "Verifying your Google account…";
          try {
            await finishSignIn(credential);
          } catch (error) {
            resetSession(error.message || "Sign-in failed. Try again.");
          }
        },
        auto_select: false,
        cancel_on_tap_outside: true,
        use_fedcm_for_button: true,
      });
      window.google.accounts.id.renderButton(googleButton, {
        type: "standard",
        theme: "outline",
        size: "large",
        text: "continue_with",
        shape: "pill",
        width: 280,
      });
      configurationNote.textContent = "Your password is handled by Google—not Rally.";
    });
    script.addEventListener("error", () => {
      configurationNote.textContent = "Google sign-in could not load. Check your connection and retry.";
    });
    document.head.append(script);
  }

  function clearDialog() {
    dialogForm.reset();
    credentialInput.value = "";
    credentialInput.required = false;
    endpointInput.required = false;
    workflowInput.required = false;
    credentialField.hidden = true;
    endpointField.hidden = true;
    workflowField.hidden = true;
    activationRail.hidden = false;
    advancedTokenButton.hidden = true;
    dialogSafetyCopy.textContent = "Never saved to browser storage. Cleared from this form before verification. Never placed in model context.";
    dialogSubmit.hidden = false;
    dialogSubmit.disabled = false;
    dialogForm.setAttribute("aria-busy", "false");
    activationRail.setAttribute("aria-busy", "false");
    formStatus.textContent = "";
    activeConnector = null;
    setActivationStage(0);
  }

  function setActivationStage(
    index,
    { busy = false, completeBefore = false, completeCurrent = false } = {},
  ) {
    const steps = [...activationRail.querySelectorAll("li")];
    steps.forEach((step, stepIndex) => {
      const current = stepIndex === index;
      step.classList.toggle("is-active", current);
      step.classList.toggle(
        "is-complete",
        (completeBefore && stepIndex < index) || (completeCurrent && current),
      );
      if (current) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    });
    activationRail.setAttribute("aria-busy", String(busy));
    dialogForm.setAttribute("aria-busy", String(busy));
  }

  function openDialog(item, mode, kind = "bearer_token") {
    if (!dialog.open) {
      const cardAction = document.querySelector(
        `[data-connector="${CSS.escape(item.id)}"] [data-primary-action]`,
      );
      dialogReturnFocus = cardAction || document.activeElement;
    }
    clearDialog();
    activeConnector = { item, mode, kind };
    if (mode === "disconnect" || mode === "disconnect-pending") {
      dialogEyebrow.textContent = "Connection custody";
      dialogTitle.textContent = mode === "disconnect-pending"
        ? `Finish disconnecting ${item.name}?`
        : `Disconnect ${item.name}?`;
      dialogCopy.textContent = mode === "disconnect-pending"
        ? "Every tool is already disabled. Rally will retry provider revocation, then delete the sealed credential only after revocation succeeds."
        : "Rally will revoke the provider grant first when the provider supports it, then delete the encrypted credential and disable every approved tool.";
      activationRail.hidden = true;
      dialogSafetyCopy.textContent = "If this connection uses a manually created key, Rally will tell you where provider-side deletion is still required.";
      dialogSubmit.textContent = mode === "disconnect-pending"
        ? "Retry disconnect"
        : `Disconnect ${item.name}`;
    } else if (mode === "reconnect") {
      dialogEyebrow.textContent = "Safe reconnection";
      dialogTitle.textContent = `Reconnect ${item.name}?`;
      dialogCopy.textContent = "Rally will revoke the old provider grant and delete its encrypted copy before opening a fresh, least-privilege authorization. The old grant is never overwritten.";
      activationRail.hidden = true;
      dialogSafetyCopy.textContent = "Every approved tool stays disabled until the replacement grant passes Rally’s fixed safe live test.";
      dialogSubmit.textContent = "Disconnect & reconnect";
    } else if (mode === "cancel-oauth") {
      dialogEyebrow.textContent = "Pending authorization";
      dialogTitle.textContent = `Cancel the pending ${item.name} request?`;
      dialogCopy.textContent = "This removes only Rally’s unfinished authorization handshake so you can start again. It does not revoke or change any connected provider account.";
      activationRail.hidden = true;
      advancedTokenButton.hidden = true;
      dialogSafetyCopy.textContent = "The operation is bound to this signed-in administrator and this connector. No provider credential is deleted.";
      dialogSubmit.textContent = "Cancel & restart";
    } else if (mode === "oauth") {
      dialogEyebrow.textContent = "Secure provider sign-in";
      dialogTitle.textContent = `Connect ${item.name}`;
      dialogCopy.textContent = "Paste the connection URL from n8n Settings, choose the workflows Rally may use, then continue to n8n sign-in. You will return to this card automatically.";
      endpointField.hidden = false;
      endpointInput.required = true;
      if (item.id === "n8n") {
        workflowField.hidden = false;
        workflowInput.required = true;
      }
      advancedTokenButton.hidden = !item.token_ready;
      advancedTokenButton.textContent = "Advanced: use a restricted credential";
      dialogSafetyCopy.textContent = "Provider tokens are exchanged and encrypted server-side. This page receives only connection status.";
      dialogSubmit.textContent = `Continue to ${item.name}`;
    } else {
      dialogEyebrow.textContent = "Advanced secure connection";
      dialogTitle.textContent = `Connect ${item.name}`;
      dialogCopy.textContent = item.credential_help;
      credentialField.hidden = false;
      credentialInput.required = true;
      credentialLabel.textContent = item.credential_label;
      tokenGuide.href = safeExternalUrl(item.token_url || item.docs_url);
      if (item.endpoint_required) {
        endpointField.hidden = false;
        endpointInput.required = true;
      }
      if (item.id === "n8n") {
        workflowField.hidden = false;
        workflowInput.required = true;
      }
      dialogSubmit.textContent = "Secure and test";
    }
    if (!dialog.open) dialog.showModal();
    window.setTimeout(() => {
      if (!endpointField.hidden) endpointInput.focus();
      else if (!workflowField.hidden) workflowInput.focus();
      else if (!credentialField.hidden) credentialInput.focus();
      else dialogSubmit.focus();
    });
  }

  function focusCardAction(connectorId) {
    focusSoon(document.querySelector(
      `[data-connector="${CSS.escape(connectorId)}"] [data-primary-action]`,
    ));
  }

  function closeDialog({ restoreFocus = true } = {}) {
    const returnFocus = dialogReturnFocus;
    if (dialog.open) dialog.close();
    clearDialog();
    dialogReturnFocus = null;
    if (restoreFocus) focusSoon(returnFocus);
  }

  function workflowIds() {
    return [...new Set(
      workflowInput.value
        .split(/[\s,]+/)
        .map((value) => value.trim())
        .filter(Boolean),
    )];
  }

  async function startOAuth(item, trigger, endpoint = null, approvedWorkflows = []) {
    trigger.disabled = true;
    const previous = trigger.textContent;
    trigger.textContent = "Opening secure consent…";
    formStatus.textContent = "Discovering the provider’s protected authorization service…";
    setActivationStage(0, { busy: true });
    try {
      const result = await startOAuthApi(item.id, {
        endpoint,
        workflow_ids: approvedWorkflows,
      });
      window.location.assign(safeExternalUrl(result.authorization_url));
    } catch (error) {
      if (error.code === "authentication_required") {
        trigger.disabled = false;
        trigger.textContent = previous;
        return;
      }
      const message = error.message || "Provider authorization could not start.";
      if (error.code === "oauth_in_progress") {
        trigger.disabled = false;
        openDialog(
          item,
          "cancel-oauth",
          document.querySelector(`[data-connector="${CSS.escape(item.id)}"]`)?.dataset.kind || "bearer_token",
        );
        formStatus.textContent = message;
        return;
      }
      if (
        !dialog.open &&
        item.token_ready &&
        !new Set(["disconnect_existing_connection", "oauth_in_progress"]).has(error.code)
      ) {
        openDialog(
          item,
          "token",
          document.querySelector(`[data-connector="${CSS.escape(item.id)}"]`)?.dataset.kind || "bearer_token",
        );
        dialogEyebrow.textContent = "Advanced fallback";
        dialogCopy.textContent = "Provider consent could not open. If your administrator already issued a dedicated restricted credential, Rally can encrypt and verify it here. Otherwise close this window and retry consent.";
        formStatus.textContent = message;
      } else {
        formStatus.textContent = message;
        if (!dialog.open) showToast(message, "warning");
      }
      trigger.disabled = false;
      trigger.textContent = previous;
      setActivationStage(0);
    }
  }

  async function verifyReturnedConnector(connectorId) {
    const item = connectors.get(connectorId);
    const card = document.querySelector(`[data-connector="${CSS.escape(connectorId)}"]`);
    if (!item || !card) return;
    const primary = card.querySelector("[data-primary-action]");
    const state = card.querySelector(".connection-state");
    primary.disabled = true;
    primary.textContent = "Testing…";
    state.textContent = "Testing safe access";
    card.classList.add("is-verifying");
    card.setAttribute("aria-busy", "true");
    try {
      const record = await api(`/v1/connections/${encodeURIComponent(connectorId)}/verify`, {
        method: "POST",
      });
      const stored = await api("/v1/connections");
      updateCards(stored.connections || []);
      if (record.status === "ready") {
        showToast(`${item.name} is connected. Rally matched ${record.tool_count} approved tools and passed its fixed safe live read.`);
      } else {
        const guidance = safeErrorMessage(
          record.error_code || "",
          "The provider did not complete Rally’s safe connection test.",
        );
        showToast(`${item.name} was not enabled. ${guidance} Every tool remains off.`, "warning");
      }
    } catch (error) {
      try {
        const stored = await api("/v1/connections");
        updateCards(stored.connections || []);
      } catch (_) {
        // The original safe error is more useful than a secondary refresh error.
      }
      showToast(error.message || "Rally could not finish testing this connection. Every tool remains off.", "warning");
    } finally {
      const record = connectionRecords.get(connectorId);
      card.classList.toggle("is-verifying", record?.status === "verifying");
      card.setAttribute("aria-busy", "false");
      primary.textContent = primaryLabel(item, record);
      primary.disabled = !record && (!item.activation_available || item.readiness === "provider_app");
      primary.focus({ preventScroll: true });
    }
  }

  grid.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    const card = event.target.closest("[data-connector]");
    if (!button || !card) return;
    const item = connectors.get(card.dataset.connector);
    if (!item) return;
    if (!button.matches("[data-primary-action]")) return;
    const record = connectionRecords.get(item.id);
    if (canFinishSetup(record)) {
      await verifyReturnedConnector(item.id);
    } else if (record?.error_code === "disconnect_pending") {
      openDialog(item, "disconnect-pending", card.dataset.kind || "bearer_token");
    } else if (requiresReconnect(record)) {
      openDialog(item, "reconnect", card.dataset.kind || "bearer_token");
    } else if (record) {
      openDialog(item, "disconnect", card.dataset.kind || "bearer_token");
    } else if (!item.activation_available || item.readiness === "provider_app") {
      return;
    } else if (item.oauth_ready && item.endpoint_required) {
      openDialog(item, "oauth", card.dataset.kind || "bearer_token");
    } else if (item.oauth_ready) {
      await startOAuth(item, button);
    } else {
      openDialog(item, "token", card.dataset.kind || "bearer_token");
    }
  });

  dialogForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!activeConnector) return;
    const { item, mode, kind } = activeConnector;
    if (new Set(["disconnect", "disconnect-pending", "reconnect"]).has(mode)) {
      const reconnect = mode === "reconnect";
      dialogSubmit.disabled = true;
      dialogForm.setAttribute("aria-busy", "true");
      formStatus.textContent = reconnect
        ? "Revoking the old grant → deleting encrypted material → preparing fresh consent…"
        : "Revoking provider access → deleting encrypted material → disabling tools…";
      try {
        const result = await api(`/v1/connections/${encodeURIComponent(item.id)}`, {
          method: "DELETE",
        });
        const stored = await api("/v1/connections");
        updateCards(stored.connections || []);
        if (result.provider_action_required) {
          closeDialog();
          showToast(`${item.name} is removed from Rally. Delete or revoke the manually created credential in ${item.name} to finish provider-side cleanup.`, "warning");
        } else if (reconnect) {
          closeDialog({ restoreFocus: false });
          showToast(`${item.name}’s old grant is removed. Opening fresh approval now…`, "neutral");
          if (item.endpoint_required) {
            openDialog(item, "oauth", kind);
            formStatus.textContent = "Enter the connection details again to begin a fresh approval.";
          } else {
            const cardAction = document.querySelector(
              `[data-connector="${CSS.escape(item.id)}"] [data-primary-action]`,
            );
            await startOAuth(item, cardAction);
          }
        } else {
          closeDialog();
          showToast(`${item.name} is disconnected. Provider access was revoked before Rally deleted its encrypted copy.`);
        }
      } catch (error) {
        try {
          const stored = await api("/v1/connections");
          updateCards(stored.connections || []);
        } catch (_) {
          // Preserve the original disconnect guidance.
        }
        formStatus.textContent = error.message || "Rally kept the credential sealed because provider revocation did not complete.";
      } finally {
        dialogSubmit.disabled = false;
        dialogForm.setAttribute("aria-busy", "false");
      }
      return;
    }
    if (mode === "cancel-oauth") {
      dialogSubmit.disabled = true;
      dialogForm.setAttribute("aria-busy", "true");
      formStatus.textContent = "Removing the unfinished Rally handshake…";
      try {
        const result = await api(`/v1/connections/${encodeURIComponent(item.id)}/oauth/pending`, {
          method: "DELETE",
        });
        const message = result.cancelled
          ? `${item.name}’s pending request is cancelled. Restarting securely…`
          : `No pending ${item.name} request remained. Starting securely…`;
        showToast(message, "neutral");
        closeDialog({ restoreFocus: false });
        if (item.endpoint_required) {
          openDialog(item, "oauth", kind);
          formStatus.textContent = "Enter the connection details again to start a fresh approval.";
        } else {
          const cardAction = document.querySelector(
            `[data-connector="${CSS.escape(item.id)}"] [data-primary-action]`,
          );
          await startOAuth(item, cardAction);
        }
      } catch (error) {
        formStatus.textContent = error.message || "Rally could not cancel that pending request.";
      } finally {
        dialogSubmit.disabled = false;
        dialogForm.setAttribute("aria-busy", "false");
      }
      return;
    }
    if (mode === "oauth") {
      await startOAuth(item, dialogSubmit, endpointInput.value.trim(), workflowIds());
      return;
    }
    if (mode !== "token" || !credentialInput.value) return;
    dialogSubmit.disabled = true;
    setActivationStage(1, { busy: true, completeBefore: true });
    formStatus.textContent = "Encrypting → discovering → safe live read → locking policy…";
    const credential = credentialInput.value;
    credentialInput.value = "";
    try {
      const record = await api(`/v1/connections/${encodeURIComponent(item.id)}`, {
        method: "PUT",
        body: JSON.stringify({
          credential,
          kind,
          endpoint: endpointInput.value.trim() || null,
          scheme: item.token_scheme || "bearer",
          workflow_ids: workflowIds(),
        }),
      });
      const stored = await api("/v1/connections");
      updateCards(stored.connections || []);
      closeDialog({ restoreFocus: false });
      if (record.status === "ready") {
        showToast(`${item.name} is certified. Rally matched ${record.tool_count} approved tools and passed its fixed safe live read.`);
      } else {
        const guidance = safeErrorMessage(
          record.error_code || "",
          "The provider did not complete Rally’s safe connection test.",
        );
        showToast(`${item.name} was not enabled. ${guidance} Every tool remains off.`, "warning");
      }
      focusCardAction(item.id);
    } catch (error) {
      formStatus.textContent = error.message || "Rally could not secure this credential.";
      setActivationStage(0);
    } finally {
      dialogSubmit.disabled = false;
      dialogForm.setAttribute("aria-busy", "false");
    }
  });

  advancedTokenButton.addEventListener("click", () => {
    if (!activeConnector) return;
    const { item, kind } = activeConnector;
    const endpoint = endpointInput.value;
    const workflows = workflowInput.value;
    openDialog(item, "token", kind);
    endpointInput.value = endpoint;
    workflowInput.value = workflows;
  });

  document.querySelector("[data-dialog-close]").addEventListener("click", () => {
    closeDialog();
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDialog();
  });
  signOutButton.addEventListener("click", async () => {
    const currentSession = sessionToken;
    try {
      if (currentSession) {
        await fetch(`${safeApiBase()}/v1/auth/logout`, {
          method: "POST",
          headers: { "X-Rally-Session": currentSession },
        });
      }
    } finally {
      resetSession("Signed out.");
    }
  });

  async function start() {
    const redirect = takeRedirectState();
    if (redirect.error) {
      configurationNote.textContent = "Google sign-in did not complete. Please try again.";
    } else if (redirect.code) {
      try {
        await exchangeRedirectCode(redirect.code);
        if (redirect.connector || redirect.connectionStatus) {
          revealConnector(redirect.connector, redirect.connectionStatus);
          if (redirect.connector && redirect.connectionStatus === "verifying") {
            await verifyReturnedConnector(redirect.connector);
          }
        }
      } catch (error) {
        resetSession(error.message || "Sign-in failed. Try again.");
      }
    } else if (redirect.connectionStatus) {
      configurationNote.textContent = "That provider return expired. Sign in and reconnect it.";
    }
    installGoogleSignIn();
  }

  start().catch((error) => resetSession(error.message || "Sign-in failed. Try again."));
})();
