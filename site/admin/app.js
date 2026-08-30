(() => {
  "use strict";

  const config = window.RALLY_ADMIN_CONFIG || {};
  const signedOut = document.querySelector("[data-signed-out]");
  const dashboard = document.querySelector("[data-dashboard]");
  const configurationNote = document.querySelector("[data-configuration-note]");
  const googleButton = document.querySelector("[data-google-button]");
  const signOutButton = document.querySelector("[data-sign-out]");
  const dialog = document.querySelector("[data-credential-dialog]");
  const dialogForm = document.querySelector("[data-credential-form]");
  const dialogTitle = document.querySelector("#credential-title");
  const dialogCopy = document.querySelector("[data-dialog-copy]");
  const credentialInput = document.querySelector("#credential-value");
  const formStatus = document.querySelector("[data-form-status]");
  const connectionCount = document.querySelector("[data-connection-count]");
  let idToken = "";
  let sessionToken = "";
  let activeConnector = null;

  const configured =
    /^[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$/.test(config.googleClientId || "") &&
    /^https:\/\//.test(config.apiBase || "");

  function safeApiBase() {
    const url = new URL(config.apiBase);
    if (url.protocol !== "https:") throw new Error("Rally control plane is not secure");
    return url.href.replace(/\/$/, "");
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
      throw new Error("Your Google session expired");
    }
    if (!response.ok) throw new Error("Rally could not complete that secure request");
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

  function updateCards(connections) {
    const byId = new Map(connections.map((connection) => [connection.connector_id, connection]));
    document.querySelectorAll("[data-connector]").forEach((card) => {
      if (!card.dataset.kind) return;
      const record = byId.get(card.dataset.connector);
      const state = card.querySelector(".connection-state");
      card.classList.toggle("is-secured", Boolean(record));
      state.textContent = record ? "Secured · verify next" : "Not secured";
      card.querySelector("button").textContent = record ? "Replace credential" : "Secure credential";
    });
    connectionCount.textContent = String(connections.length);
  }

  async function showDashboard(account) {
    const connections = await api("/v1/connections");
    setAccount(account);
    updateCards(connections.connections || []);
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
    const code = state.get("rally-login-code") || "";
    const error = state.get("rally-login-error") || "";
    if (code || error) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }
    return { code, error };
  }

  async function exchangeRedirectCode(code) {
    configurationNote.textContent = "Completing secure Google sign-in…";
    const response = await fetch(`${safeApiBase()}/v1/auth/exchange`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!response.ok) throw new Error("That sign-in link expired or was already used. Try again.");
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

  document.querySelectorAll("[data-connector] button:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest("[data-connector]");
      activeConnector = { id: card.dataset.connector, kind: card.dataset.kind, name: card.querySelector("h3").textContent };
      dialogTitle.textContent = `Secure ${activeConnector.name}`;
      dialogCopy.textContent = `${activeConnector.name} will remain disabled until Rally verifies its live capabilities and safe preset.`;
      formStatus.textContent = "";
      credentialInput.value = "";
      dialog.showModal();
      credentialInput.focus();
    });
  });

  dialogForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!activeConnector || !credentialInput.value) return;
    const submit = dialogForm.querySelector("[type=submit]");
    submit.disabled = true;
    formStatus.textContent = "Encrypting for your account…";
    const credential = credentialInput.value;
    credentialInput.value = "";
    try {
      await api(`/v1/connections/${encodeURIComponent(activeConnector.id)}`, {
        method: "PUT",
        body: JSON.stringify({ credential, kind: activeConnector.kind }),
      });
      const connections = await api("/v1/connections");
      updateCards(connections.connections || []);
      dialog.close();
    } catch (error) {
      formStatus.textContent = error.message || "Rally could not secure this credential.";
    } finally {
      submit.disabled = false;
      activeConnector = null;
    }
  });

  document.querySelector("[data-dialog-close]").addEventListener("click", () => {
    credentialInput.value = "";
    activeConnector = null;
    dialog.close();
  });
  dialog.addEventListener("cancel", () => {
    credentialInput.value = "";
    activeConnector = null;
  });
  signOutButton.addEventListener("click", () => resetSession("Signed out safely."));

  async function start() {
    const redirect = takeRedirectState();
    if (redirect.error) {
      configurationNote.textContent = "Google sign-in did not complete. Please try again.";
    } else if (redirect.code) {
      try {
        await exchangeRedirectCode(redirect.code);
      } catch (error) {
        resetSession(error.message || "Sign-in failed. Try again.");
      }
    }
    installGoogleSignIn();
  }

  start().catch((error) => resetSession(error.message || "Sign-in failed. Try again."));
})();
