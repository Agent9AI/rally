(() => {
  "use strict";

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
  const setupLink = document.querySelector("[data-setup-link]");
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
  let idToken = "";
  let sessionToken = "";
  let activeConnector = null;
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
    account_required: "Enter the provider account email associated with this credential.",
    policy_configuration_required: "Add at least one approved n8n workflow ID.",
    policy_scope_invalid: "Check the workflow IDs and try again.",
  };

  async function api(path, options = {}) {
    if (!idToken && !sessionToken) throw new Error("Sign in again to continue");
    const headers = new Headers(options.headers || {});
    if (idToken) headers.set("X-Rally-ID-Token", idToken);
    if (sessionToken) headers.set("X-Rally-Session", sessionToken);
    if (options.body) headers.set("Content-Type", "application/json");
    const response = await fetch(`${safeApiBase()}${path}`, { ...options, headers });
    if (response.status === 401) {
      resetSession("Your Google session expired. Sign in again.");
      throw new Error("Your Google session expired");
    }
    if (!response.ok) {
      let detail = "";
      try {
        detail = (await response.json()).detail || "";
      } catch (_) {
        // The public error remains intentionally generic.
      }
      throw new Error(safeErrors[detail] || "Rally could not complete that secure request");
    }
    return response.json();
  }

  function resetSession(message = "") {
    idToken = "";
    sessionToken = "";
    signedOut.hidden = false;
    dashboard.hidden = true;
    signOutButton.hidden = true;
    configurationNote.textContent = message;
    if (window.google?.accounts?.id) window.google.accounts.id.disableAutoSelect();
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
      return record.tool_count ? `Ready · ${record.tool_count} tools` : "Ready";
    }
    if (record?.status === "needs_attention") return "Needs attention";
    if (record) return "Secured · verifying";
    if (item?.readiness === "provider_app") return "App setup needed";
    if (item?.oauth_ready) return "OAuth ready";
    return "Token required";
  }

  function primaryLabel(item, record) {
    if (item?.readiness === "provider_app") return "See setup";
    if (record?.status === "ready") return item?.oauth_ready ? "Reconnect" : "Replace";
    if (record?.status === "needs_attention") return item?.oauth_ready ? "Try again" : "Replace";
    return "Connect";
  }

  function updateCards(records) {
    connectionRecords = new Map(records.map((record) => [record.connector_id, record]));
    document.querySelectorAll("[data-connector]").forEach((card) => {
      const item = connectors.get(card.dataset.connector);
      const record = connectionRecords.get(card.dataset.connector);
      const state = card.querySelector(".connection-state");
      const primary = card.querySelector("[data-primary-action]");
      card.classList.toggle("is-secured", record?.status === "ready");
      card.classList.toggle("needs-attention", record?.status === "needs_attention");
      state.textContent = cardState(item, record);
      primary.textContent = primaryLabel(item, record);
      const alternative = card.querySelector("[data-token-action]");
      if (alternative) alternative.hidden = !item?.token_ready;
    });
    connectionCount.textContent = String(records.length);
  }

  async function showDashboard(account) {
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
  }

  async function finishSignIn(credential) {
    idToken = credential;
    sessionToken = "";
    const account = await api("/v1/me");
    await showDashboard(account);
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
    await showDashboard(result.account);
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
      showToast(`${name} is ready. Rally verified ${count || "its"} live tools and applied the safe preset.`);
    } else if (status === "cancelled") {
      showToast(`${name} authorization was cancelled. Nothing was enabled.`, "neutral");
    } else if (status === "needs-attention") {
      showToast(`${name} returned, but its live capability check did not pass. No tools were enabled.`, "warning");
    } else if (status === "invalid-or-expired") {
      showToast("That authorization return expired. Start the connection again.", "warning");
    }
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
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
    setupLink.hidden = true;
    dialogSubmit.hidden = false;
    formStatus.textContent = "";
    activeConnector = null;
  }

  function openDialog(item, mode, kind = "bearer_token") {
    clearDialog();
    activeConnector = { item, mode, kind };
    if (mode === "setup") {
      dialogEyebrow.textContent = "One-time provider setup";
      dialogTitle.textContent = `${item.name} needs an app registration`;
      dialogCopy.textContent = item.credential_help;
      setupLink.href = safeExternalUrl(item.setup_url);
      setupLink.hidden = false;
      dialogSubmit.hidden = true;
    } else if (mode === "oauth") {
      dialogEyebrow.textContent = "Hosted OAuth";
      dialogTitle.textContent = `Connect ${item.name}`;
      dialogCopy.textContent = "Enter the provider’s exact MCP server URL. Rally will open consent here, then return to this card for live verification.";
      endpointField.hidden = false;
      endpointInput.required = true;
      if (item.id === "n8n") {
        workflowField.hidden = false;
        workflowInput.required = true;
      }
      dialogSubmit.textContent = `Continue to ${item.name}`;
    } else {
      dialogEyebrow.textContent = "Tenant-isolated vault";
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
      dialogSubmit.textContent = "Encrypt and verify";
    }
    dialog.showModal();
    window.setTimeout(() => {
      if (!endpointField.hidden) endpointInput.focus();
      else if (!workflowField.hidden) workflowInput.focus();
      else if (!credentialField.hidden) credentialInput.focus();
      else setupLink.focus();
    });
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
    try {
      const result = await api(`/v1/connections/${encodeURIComponent(item.id)}/oauth/start`, {
        method: "POST",
        body: JSON.stringify({ endpoint, workflow_ids: approvedWorkflows }),
      });
      window.location.assign(safeExternalUrl(result.authorization_url));
    } catch (error) {
      formStatus.textContent = error.message || "Provider authorization could not start.";
      if (!dialog.open) showToast(formStatus.textContent, "warning");
      trigger.disabled = false;
      trigger.textContent = previous;
    }
  }

  grid.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    const card = event.target.closest("[data-connector]");
    if (!button || !card) return;
    const item = connectors.get(card.dataset.connector);
    if (!item) return;
    if (button.matches("[data-token-action]")) {
      openDialog(item, "token", card.dataset.kind || "bearer_token");
      return;
    }
    if (!button.matches("[data-primary-action]")) return;
    if (item.readiness === "provider_app") {
      openDialog(item, "setup");
    } else if (item.oauth_ready && item.endpoint_required) {
      openDialog(item, "oauth");
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
    if (mode === "oauth") {
      await startOAuth(item, dialogSubmit, endpointInput.value.trim(), workflowIds());
      return;
    }
    if (mode !== "token" || !credentialInput.value) return;
    dialogSubmit.disabled = true;
    formStatus.textContent = "Encrypting → discovering live tools → applying the safe preset…";
    const credential = credentialInput.value;
    credentialInput.value = "";
    try {
      const record = await api(`/v1/connections/${encodeURIComponent(item.id)}`, {
        method: "PUT",
        body: JSON.stringify({
          credential,
          kind,
          endpoint: endpointInput.value.trim() || null,
          scheme: "bearer",
          workflow_ids: workflowIds(),
        }),
      });
      const stored = await api("/v1/connections");
      updateCards(stored.connections || []);
      dialog.close();
      if (record.status === "ready") {
        showToast(`${item.name} is ready. Rally discovered ${record.tool_count} live tools without exposing the credential.`);
      } else {
        showToast(`${item.name} is encrypted, but verification did not pass. No tools were enabled.`, "warning");
      }
      document.querySelector(`[data-connector="${CSS.escape(item.id)}"] [data-primary-action]`)?.focus();
      clearDialog();
    } catch (error) {
      formStatus.textContent = error.message || "Rally could not secure this credential.";
    } finally {
      dialogSubmit.disabled = false;
    }
  });

  document.querySelector("[data-dialog-close]").addEventListener("click", () => {
    clearDialog();
    dialog.close();
  });
  dialog.addEventListener("cancel", clearDialog);
  signOutButton.addEventListener("click", () => resetSession("Signed out safely."));

  async function start() {
    const redirect = takeRedirectState();
    if (redirect.error) {
      configurationNote.textContent = "Google sign-in did not complete. Please try again.";
    } else if (redirect.code) {
      try {
        await exchangeRedirectCode(redirect.code);
        if (redirect.connector || redirect.connectionStatus) {
          revealConnector(redirect.connector, redirect.connectionStatus);
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
