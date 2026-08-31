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
  const magicLinkForm = document.querySelector("[data-magic-link-form]");
  const magicLinkEmail = document.querySelector("[data-magic-link-email]");
  const magicLinkSubmit = document.querySelector("[data-magic-link-submit]");
  const magicLinkStatus = document.querySelector("[data-magic-link-status]");
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
  const connectionCounts = document.querySelectorAll("[data-connection-count]");
  const toast = document.querySelector("[data-connection-toast]");
  const signinTitle = document.querySelector("[data-signin-title]");
  const dashboardTitle = document.querySelector("[data-dashboard-title]");
  const workspaceNav = document.querySelectorAll("[data-workspace-nav]");
  const workspaceViews = document.querySelectorAll("[data-workspace-view]");
  const runList = document.querySelector("[data-work-run-list]");
  const runDetail = document.querySelector("[data-work-run-detail]");
  const workSearch = document.querySelector("[data-work-search]");
  const runFilters = document.querySelectorAll("[data-run-filter]");
  const metricActive = document.querySelector("[data-metric-active]");
  const metricAttention = document.querySelector("[data-metric-attention]");
  const metricComplete = document.querySelector("[data-metric-complete]");
  const workspaceLiveStatus = document.querySelector("[data-workspace-live-status]");
  const commissionHub = document.querySelector(".commission-hub");
  const commissionTitle = document.querySelector("#commission-title");
  const commissionSummary = document.querySelector("[data-commission-summary]");
  const assistantSetupToggle = document.querySelector("[data-toggle-assistant-setup]");
  const openJobComposerButtons = document.querySelectorAll("[data-open-job-composer]");
  const assistantPersonaButtons = document.querySelectorAll("[data-assistant-persona]");
  const expertiseButtons = document.querySelectorAll("[data-expertise]");
  const autonomyButtons = document.querySelectorAll("[data-autonomy]");
  const jobForm = document.querySelector("[data-job-form]");
  const jobComposerTitle = document.querySelector("#job-composer-title");
  const jobTitle = document.querySelector("[data-job-title]");
  const jobGoal = document.querySelector("[data-job-goal]");
  const jobSourceRun = document.querySelector("[data-job-source-run]");
  const jobSecondWind = document.querySelector("[data-job-second-wind]");
  const jobFormStatus = document.querySelector("[data-job-form-status]");
  const jobSubmit = document.querySelector("[data-job-submit]");
  const jobReceipt = document.querySelector("[data-job-receipt]");
  const jobReceiptTitle = document.querySelector("[data-job-receipt-title]");
  const jobReceiptId = document.querySelector("[data-job-receipt-id]");
  const jobReceiptDetail = document.querySelector("[data-job-receipt-detail]");
  const composerPersona = document.querySelector("[data-composer-persona]");
  const composerExpertise = document.querySelector("[data-composer-expertise]");
  const composerAutonomy = document.querySelector("[data-composer-autonomy]");
  const postureNote = document.querySelector("[data-posture-note]");
  const teammateList = document.querySelector("[data-teammate-list]");
  const teammateForm = document.querySelector("[data-teammate-form]");
  const teammateFormTitle = document.querySelector("#teammate-form-title");
  const teammateName = document.querySelector("[data-teammate-name]");
  const teammateRole = document.querySelector("[data-teammate-role]");
  const customRoleField = document.querySelector("[data-custom-role-field]");
  const customRole = document.querySelector("[data-custom-role]");
  const teammateOwner = document.querySelector("[data-teammate-owner]");
  const emailProviderOptions = document.querySelector("[data-email-provider-options]");
  const emailLocal = document.querySelector("[data-email-local]");
  const emailDomain = document.querySelector("[data-email-domain]");
  const emailMethods = document.querySelector("[data-email-methods]");
  const providerReadiness = document.querySelector("[data-provider-readiness]");
  const teammateReachability = document.querySelector("[data-teammate-reachability]");
  const allowedSenders = document.querySelector("[data-allowed-senders]");
  const teammateFormStatus = document.querySelector("[data-teammate-form-status]");
  const teammateSubmit = document.querySelector("[data-teammate-submit]");
  const teammateOnboardingStep = document.querySelector("[data-teammate-onboarding-step]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let idToken = "";
  let sessionToken = "";
  let activeConnector = null;
  let dialogReturnFocus = null;
  let connectors = new Map();
  let connectionRecords = new Map();
  let workspaceRuns = [];
  let activeRunId = "";
  let activeRunFilter = "all";
  let teammateRecords = [];
  let emailProviders = new Map();
  let trialEmailDomain = "updates.agent9.dev";
  let pilotCommissionAddress = "";
  let currentAccount = null;
  let acceptedRunId = "";
  let composerReturnFocus = null;
  let pendingJobIdempotencyKey = "";
  let selectedAssistant = "strategist";
  let selectedExpertise = "balanced";
  let selectedAutonomy = "resilient";
  let lastSuggestedDraft = { title: "", goal: "" };
  let assistantSetupManuallyToggled = false;
  const WORKSPACE_REFRESH_INTERVAL_MS = 13000;
  let workspaceRefreshTimer = 0;
  let workspaceRefreshInFlight = false;
  let workspaceRefreshController = null;

  const configuredApi = /^https:\/\//.test(config.apiBase || "");
  const configuredGoogle = configuredApi &&
    /^[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$/.test(config.googleClientId || "");

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
    "email address is already assigned": "That email address already belongs to a Rally teammate.",
    "could not create teammate": "Rally could not save this teammate securely. Try again in a moment.",
    "could not read teammates": "Rally could not load this workspace’s teammates.",
    "email domain is reserved for Rally trials": "Choose Temporary Rally trial for that domain, or use a company-owned domain.",
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
      resetSession("Your secure session expired. Sign in again.");
      const error = new Error("Your secure session expired. Sign in again.");
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

  async function workspaceApi(path, options = {}) {
    if (!idToken && !sessionToken) throw new Error("Sign in again to continue");
    const headers = new Headers(options.headers || {});
    if (idToken) headers.set("X-Rally-ID-Token", idToken);
    if (sessionToken) headers.set("X-Rally-Session", sessionToken);
    if (options.body) headers.set("Content-Type", "application/json");
    const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    if (response.status === 401) {
      resetSession("Your secure session expired. Sign in again.");
      throw new Error("Your secure session expired. Sign in again.");
    }
    if (!response.ok) {
      let detail = "";
      try {
        detail = (await response.json()).detail || "";
      } catch (_) {
        // Keep the user-facing boundary generic.
      }
      throw new Error(detail || "Your Rally work queue is temporarily unavailable");
    }
    return response.status === 204 ? {} : response.json();
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
      resetSession("Your secure session expired. Sign in again.");
      const error = new Error("Your secure session expired. Sign in again.");
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
    stopWorkspacePolling();
    idToken = "";
    sessionToken = "";
    if (dialog.open) dialog.close();
    clearDialog();
    dialogReturnFocus = null;
    signedOut.hidden = false;
    dashboard.hidden = true;
    signOutButton.hidden = true;
    workspaceRuns = [];
    activeRunId = "";
    teammateRecords = [];
    emailProviders = new Map();
    pilotCommissionAddress = "";
    currentAccount = null;
    acceptedRunId = "";
    pendingJobIdempotencyKey = "";
    jobForm.reset();
    jobForm.hidden = true;
    jobReceipt.hidden = true;
    selectedAssistant = "strategist";
    selectedExpertise = "balanced";
    selectedAutonomy = "resilient";
    lastSuggestedDraft = { title: "", goal: "" };
    syncAssistantSetup();
    commissionHub.classList.remove("is-composing");
    openJobComposerButtons.forEach((button) => button.setAttribute("aria-expanded", "false"));
    configurationNote.textContent = message;
    if (window.google?.accounts?.id) window.google.accounts.id.disableAutoSelect();
    focusSoon(signinTitle);
  }

  function setAccount(account) {
    currentAccount = account;
    document.querySelector("[data-user-name]").textContent = account.name || "Rally administrator";
    document.querySelector("[data-user-email]").textContent = account.email || "";
    document.querySelector("[data-user-initial]").textContent = (account.name || account.email || "R").charAt(0).toUpperCase();
    const picture = document.querySelector("[data-user-picture]");
    picture.hidden = true;
    document.querySelector("[data-user-initial]").hidden = false;
    if (account.picture && /^https:\/\/lh3\.googleusercontent\.com\//.test(account.picture)) {
      picture.src = account.picture;
      picture.hidden = false;
      document.querySelector("[data-user-initial]").hidden = true;
    }
  }

  function showWorkspaceView(name, { focusHeading = true } = {}) {
    const target = [...workspaceViews].find((view) => view.dataset.workspaceView === name);
    if (!target) return;
    workspaceViews.forEach((view) => { view.hidden = view !== target; });
    workspaceNav.forEach((button) => {
      const active = button.dataset.workspaceNav === name;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    if (focusHeading) focusSoon(target.querySelector("h1"));
  }

  function element(tag, className = "", copy = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (copy) node.textContent = copy;
    return node;
  }

  const providerBadges = {
    google_workspace: "Company mailbox",
    microsoft_365: "Company mailbox",
    company_subdomain: "Recommended",
    resend: "Email infrastructure",
    cloudflare_email: "Email infrastructure",
    existing_address: "Bring your own",
    advanced_provider: "Advanced",
    rally_trial: "Temporary only",
  };

  const methodLabels = {
    oauth: "OAuth",
    api_key: "API key",
    dns: "DNS routing",
    existing: "Already routes to Rally",
    trial: "Temporary trial",
  };

  const teammateStatusLabels = {
    ready: "Live",
    trial_activation_required: "Trial activation required",
    authorization_required: "Authorization required",
    dns_required: "DNS required",
    verification_required: "Verification required",
    configuration_required: "Configuration required",
  };

  const reachabilityLabels = {
    selected_senders: "Selected senders",
    entire_company: "Entire company",
    approved_domains: "Approved people or domains",
    public_intake: "Public intake",
  };

  function roleLabel(record) {
    if (record.role === "custom") return record.custom_role || "Custom role";
    return String(record.role || "general")
      .replaceAll("_", " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function selectedEmailProvider() {
    const selected = emailProviderOptions.querySelector('input[name="email_provider"]:checked');
    return selected ? emailProviders.get(selected.value) : null;
  }

  function renderEmailMethods(provider) {
    emailMethods.replaceChildren();
    if (!provider) return;
    (provider.connection_methods || []).forEach((method, index) => {
      const label = element("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "connection_method";
      input.value = method;
      input.required = true;
      input.checked = method === provider.default_method || (!provider.default_method && index === 0);
      input.defaultChecked = input.checked;
      const suffix = method === "oauth" && provider.connection_methods.includes("api_key")
        ? " (recommended)"
        : method === "api_key" && provider.connection_methods.includes("oauth")
          ? " (optional)"
          : "";
      label.append(input, document.createTextNode(`${methodLabels[method] || method}${suffix}`));
      emailMethods.append(label);
    });
  }

  function syncProviderForm() {
    const provider = selectedEmailProvider();
    if (!provider) {
      providerReadiness.textContent = "Choose where this teammate’s email identity should live.";
      return;
    }
    const isTrial = provider.id === "rally_trial";
    if (isTrial) {
      if (!emailDomain.disabled) emailDomain.dataset.companyDomain = emailDomain.value;
      emailDomain.value = trialEmailDomain;
      emailDomain.disabled = true;
      emailDomain.required = false;
    } else {
      const previousCompanyDomain = emailDomain.dataset.companyDomain || "";
      emailDomain.disabled = false;
      emailDomain.required = true;
      if (emailDomain.value === trialEmailDomain) emailDomain.value = previousCompanyDomain;
    }
    renderEmailMethods(provider);
    providerReadiness.classList.toggle("is-actionable", Boolean(provider.setup_available));
    const boundary = provider.resulting_status === "trial_activation_required"
      ? "The identity is not production-ready."
      : provider.resulting_status === "authorization_required"
        ? "The address stays inactive until authorization and a live mail check pass."
        : provider.resulting_status === "dns_required"
          ? "The address stays inactive until DNS and a live mail check pass."
          : provider.resulting_status === "verification_required"
            ? "The address stays inactive until Rally verifies inbound and outbound mail."
            : "The address stays inactive until configuration and a live mail check pass.";
    providerReadiness.textContent = `${provider.activation_note} ${boundary}`;
  }

  function renderEmailProviders(providers) {
    emailProviderOptions.replaceChildren();
    const createProviderOption = (provider) => {
      const label = element(
        "label",
        `email-provider-option${provider.id === "rally_trial" ? " is-trial" : ""}`,
      );
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "email_provider";
      input.value = provider.id;
      input.required = true;
      input.checked = provider.id === "company_subdomain";
      input.defaultChecked = input.checked;
      const copy = element("span");
      copy.append(element("b", "", provider.name), element("small", "", provider.description));
      label.append(input, copy, element("em", "", providerBadges[provider.id] || "Email provider"));
      input.addEventListener("change", syncProviderForm);
      return label;
    };
    const preferredOrder = [
      "company_subdomain",
      "existing_address",
      "google_workspace",
      "microsoft_365",
    ];
    const primary = providers
      .filter((provider) => provider.group === "company")
      .sort((left, right) => preferredOrder.indexOf(left.id) - preferredOrder.indexOf(right.id));
    const primaryGrid = element("div", "provider-option-grid");
    primary.forEach((provider) => primaryGrid.append(createProviderOption(provider)));
    emailProviderOptions.append(
      element("p", "provider-group-label", "Best for most teams"),
      primaryGrid,
    );

    const secondary = providers.filter((provider) => provider.group === "infrastructure");
    const trials = providers.filter((provider) => provider.group === "trial");
    if (secondary.length || trials.length) {
      const more = element("details", "provider-more");
      more.append(element("summary", "", "Email infrastructure, API, and trial options"));
      const moreCopy = element(
        "p",
        "",
        "For teams that already operate mail infrastructure—or need a temporary evaluation identity.",
      );
      const secondaryGrid = element("div", "provider-option-grid");
      [...secondary, ...trials].forEach((provider) => {
        secondaryGrid.append(createProviderOption(provider));
      });
      more.append(moreCopy, secondaryGrid);
      emailProviderOptions.append(more);
    }
    syncProviderForm();
  }

  const teammateSuggestions = {
    research: ["Rally Research", "research"],
    security: ["Rally Security", "security"],
    operations: ["Rally Operations", "operations"],
    finance: ["Rally Finance", "finance"],
    customer_success: ["Rally Customer Success", "customer-success"],
    general: ["Rally", "rally"],
  };

  function applyRoleSuggestion() {
    const previousName = teammateName.dataset.suggestedValue || "";
    const previousLocal = emailLocal.dataset.suggestedValue || "";
    const suggestion = teammateSuggestions[teammateRole.value];
    if (!suggestion) return;
    if (!teammateName.value || teammateName.value === previousName) {
      teammateName.value = suggestion[0];
    }
    if (!emailLocal.value || emailLocal.value === previousLocal) {
      emailLocal.value = suggestion[1];
    }
    teammateName.dataset.suggestedValue = suggestion[0];
    emailLocal.dataset.suggestedValue = suggestion[1];
  }

  const assistantProfiles = Object.freeze({
    strategist: {
      label: "Executive strategist",
      title: "Prepare an executive decision brief",
      goal: "Research and synthesize the available evidence into an executive-ready recommendation. Compare the strongest options, cite every consequential claim, make the tradeoffs explicit, and return a clear decision with next actions and residual risk.",
    },
    security: {
      label: "Security lead",
      title: "Assess and prioritize security risk",
      goal: "Inspect the available evidence for material security risk, validate the highest-impact findings, and return a prioritized remediation plan. Separate confirmed issues from assumptions, preserve an auditable evidence trail, and state the residual risk after each recommended control.",
    },
    creative: {
      label: "Creative director",
      title: "Develop a campaign-ready creative direction",
      goal: "Turn the brief and approved source material into a distinctive creative direction with a clear audience, narrative, channel plan, and production-ready deliverables. Reconcile conflicting feedback, explain the strongest choices, and have a different model challenge the final work before approval.",
    },
  });

  function assistantDraft() {
    const profile = assistantProfiles[selectedAssistant] || assistantProfiles.strategist;
    const depth = selectedExpertise === "deep"
      ? "Investigate deeply, reconcile conflicting evidence, and document important uncertainty before reaching a conclusion."
      : "Keep the result focused, decision-ready, and proportionate to the evidence available.";
    return { title: profile.title, goal: `${profile.goal}\n\n${depth}` };
  }

  function syncAssistantSetup({ prefill = false } = {}) {
    const previousDraft = lastSuggestedDraft;
    const draft = assistantDraft();
    const profile = assistantProfiles[selectedAssistant] || assistantProfiles.strategist;
    assistantPersonaButtons.forEach((button) => {
      const selected = button.dataset.assistantPersona === selectedAssistant;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    expertiseButtons.forEach((button) => {
      const selected = button.dataset.expertise === selectedExpertise;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    autonomyButtons.forEach((button) => {
      const selected = button.dataset.autonomy === selectedAutonomy;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    jobSecondWind.checked = selectedAutonomy === "resilient";
    jobTitle.placeholder = draft.title;
    jobGoal.placeholder = draft.goal;
    composerPersona.textContent = profile.label;
    composerExpertise.textContent = selectedExpertise === "deep"
      ? "Deep-specialist brief"
      : "Focused brief";
    composerAutonomy.textContent = selectedAutonomy === "resilient"
      ? "Resilient recovery"
      : "Guarded execution";
    postureNote.textContent = selectedAutonomy === "resilient"
      ? "One bounded recovery handoff is allowed. A different model must still approve the work."
      : "The run stops at the first unrecoverable blocker. A different model must still approve completed work.";
    if (prefill) {
      if (!jobTitle.value || jobTitle.value === previousDraft.title) jobTitle.value = draft.title;
      if (!jobGoal.value || jobGoal.value === previousDraft.goal) jobGoal.value = draft.goal;
    }
    lastSuggestedDraft = draft;
  }

  function commissionMailto(address, subject = "New Rally job") {
    const query = new URLSearchParams({
      subject,
      body: "Outcome:\n\nContext or attachments:\n\nDue date:",
    });
    return `mailto:${address}?${query.toString()}`;
  }

  function activeCommissionAddress() {
    const active = teammateRecords.find((record) => record.email?.status === "ready");
    return active?.email?.address || pilotCommissionAddress;
  }

  function updateCommissionLinks() {
    const address = activeCommissionAddress();
    document.querySelectorAll("[data-commission-address]").forEach((label) => {
      label.textContent = address || "Finish email setup";
    });
    document.querySelectorAll("[data-first-job-link]").forEach((link) => {
      const kind = link.dataset.firstJobLink;
      if (!address) {
        link.href = "?view=teammates";
        if (kind !== "email-door") link.textContent = "Finish email setup";
        return;
      }
      link.href = commissionMailto(address, kind === "queue" ? "My first Rally job" : "New Rally job");
      if (kind === "queue") link.textContent = "Email the first request";
      if (kind === "onboarding") {
        link.textContent = teammateRecords.some((record) => record.email?.status === "ready")
          ? `Email ${address}`
          : "Use current pilot address";
      }
    });
  }

  function setComposerExpanded(expanded, { focus = true, restoreFocus = false } = {}) {
    jobForm.hidden = !expanded;
    commissionHub.classList.toggle("is-composing", expanded);
    openJobComposerButtons.forEach((button) => {
      button.setAttribute("aria-expanded", String(expanded));
    });
    if (expanded && focus) {
      jobForm.scrollIntoView({
        behavior: reducedMotion.matches ? "auto" : "smooth",
        block: "nearest",
      });
      focusSoon(jobTitle.value ? jobComposerTitle : jobTitle);
    } else if (!expanded && restoreFocus) {
      focusSoon(composerReturnFocus);
    }
  }

  function setAssistantSetupCollapsed(collapsed) {
    commissionHub.classList.toggle("is-collapsed", collapsed);
    assistantSetupToggle.setAttribute("aria-expanded", String(!collapsed));
    assistantSetupToggle.textContent = collapsed ? "Edit team setup" : "Hide setup";
    commissionTitle.textContent = collapsed
      ? "Your AI team is ready."
      : "Choose the role. Rally assembles the team.";
    commissionSummary.textContent = collapsed
      ? "Start a job from the dashboard or email. Every request enters the same governed queue and returns with independent verification."
      : "You define the business outcome. Rally quietly routes the right models, approved systems, recovery, and independent verification underneath.";
  }

  function openJobComposer(trigger = null) {
    composerReturnFocus = trigger || document.activeElement;
    jobReceipt.hidden = true;
    acceptedRunId = "";
    jobFormStatus.textContent = "";
    syncAssistantSetup({ prefill: true });
    setComposerExpanded(true);
  }

  function closeJobComposer() {
    setComposerExpanded(false, { restoreFocus: true });
  }

  function acceptedRunIdFrom(result) {
    return result?.run_id || result?.job?.run_id || result?.run?.run_id ||
      result?.job_id || result?.id || "";
  }

  function newJobIdempotencyKey() {
    if (typeof crypto.randomUUID === "function") return `job:${crypto.randomUUID()}`;
    const entropy = new Uint32Array(4);
    crypto.getRandomValues(entropy);
    return `job:${[...entropy].map((value) => value.toString(16).padStart(8, "0")).join("")}`;
  }

  function showJobAcceptance({ runId, title, status, acceptedAt, secondWind }) {
    acceptedRunId = runId;
    jobReceiptTitle.textContent = title;
    jobReceiptId.textContent = runId;
    const acceptedTime = shortTime(acceptedAt);
    const queueState = status === "running" ? "Started" : "Queued";
    jobReceiptDetail.textContent = `${queueState}${acceptedTime ? ` ${acceptedTime}` : ""} · ` +
      `Second Wind ${secondWind ? "on" : "off"} · policy and independent verification attached.`;
    setComposerExpanded(false);
    jobReceipt.hidden = false;
    focusSoon(jobReceipt);
  }

  function renderTeammates() {
    teammateList.replaceChildren();
    if (!teammateRecords.length) {
      const empty = element("div", "teammate-empty");
      empty.append(
        element("span", "", "+"),
        element("h3", "", "No teammates yet"),
        element("p", "", "Create a durable role, address, owner, and commissioning boundary."),
      );
      teammateList.append(empty);
    } else {
      teammateRecords.forEach((record) => {
        const card = element("article", "teammate-card");
        const header = element("header");
        const identity = element("div");
        const avatar = element(
          "span",
          "teammate-avatar",
          (record.name || "R").charAt(0).toUpperCase(),
        );
        const copy = element("div");
        copy.append(element("h3", "", record.name), element("p", "", roleLabel(record)));
        identity.append(avatar, copy);
        const status = record.email?.status || "configuration_required";
        const statusBadge = element(
          "span",
          `teammate-email-status${status === "trial_activation_required" ? " is-trial" : ""}${status === "ready" ? " is-ready" : ""}`,
          teammateStatusLabels[status] || "Setup required",
        );
        header.append(identity, statusBadge);
        const footer = element("footer");
        const provider = emailProviders.get(record.email?.provider);
        const providerMeta = element(
          "small",
          "teammate-provider",
          `${provider?.name || "Email provider"} · ${methodLabels[record.email?.connection_method] || "Setup"}`,
        );
        footer.append(
          element("span", "", `Owner · ${record.human_owner_email}`),
          element("span", "", reachabilityLabels[record.reachability] || "Restricted"),
        );
        card.append(
          header,
          element("p", "", record.email?.address || "Address pending"),
          providerMeta,
          footer,
        );
        teammateList.append(card);
      });
    }
    const onboardingButton = teammateOnboardingStep?.querySelector("button");
    teammateOnboardingStep?.classList.toggle("is-ready", teammateRecords.length > 0);
    if (onboardingButton) {
      const live = teammateRecords.some((record) => record.email?.status === "ready");
      onboardingButton.textContent = live
        ? "View teammates"
        : teammateRecords.length
          ? "Finish activation"
          : "Create teammate";
    }
    updateCommissionLinks();
  }

  function inferredCompanyDomain(account) {
    const hosted = String(account?.hosted_domain || "").trim().toLowerCase();
    if (hosted && hosted.includes(".")) return hosted;
    const domain = String(account?.email || "").split("@").pop().toLowerCase();
    const consumerDomains = new Set([
      "gmail.com",
      "googlemail.com",
      "outlook.com",
      "hotmail.com",
      "live.com",
      "icloud.com",
      "yahoo.com",
    ]);
    return domain.includes(".") && !consumerDomains.has(domain) ? domain : "";
  }

  async function loadTeammateSetup(account) {
    const [providerResult, teammateResult] = await Promise.allSettled([
      api("/v1/email-provider-options"),
      api("/v1/teammates"),
    ]);
    teammateOwner.value = account.email || "";
    applyRoleSuggestion();
    const companyDomain = inferredCompanyDomain(account);
    if (companyDomain && !emailDomain.value) emailDomain.value = `ai.${companyDomain}`;
    if (providerResult.status === "fulfilled") {
      const providers = Array.isArray(providerResult.value.providers)
        ? providerResult.value.providers
        : [];
      trialEmailDomain = providerResult.value.trial_domain || trialEmailDomain;
      pilotCommissionAddress = providerResult.value.pilot_address || "";
      emailProviders = new Map(providers.map((provider) => [provider.id, provider]));
      renderEmailProviders(providers);
      teammateSubmit.disabled = providers.length === 0;
      updateCommissionLinks();
    } else {
      emailProviderOptions.replaceChildren(
        element("p", "provider-loading", "Email provider options are temporarily unavailable."),
      );
      providerReadiness.textContent = providerResult.reason?.message
        || "Rally could not load provider options.";
      teammateSubmit.disabled = true;
    }
    if (teammateResult.status === "fulfilled") {
      teammateRecords = Array.isArray(teammateResult.value.teammates)
        ? teammateResult.value.teammates
        : [];
      renderTeammates();
    } else {
      teammateRecords = [];
      const failed = element("div", "teammate-empty");
      failed.append(
        element("span", "", "!"),
        element("h3", "", "Teammates unavailable"),
        element(
          "p",
          "",
          teammateResult.reason?.message || "Rally could not load this workspace’s teammates.",
        ),
      );
      teammateList.replaceChildren(failed);
    }
  }

  function runStatus(status) {
    return {
      queued: "Queued",
      accepted: "Queued",
      running: "In progress",
      complete: "Complete",
      blocked: "Needs attention",
      halted: "Stopped",
    }[status] || "Unknown";
  }

  function shortTime(value) {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "";
    const elapsed = Math.max(0, Date.now() - date.getTime());
    const minutes = Math.floor(elapsed / 60000);
    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 8) return `${days}d ago`;
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
  }

  function visibleRuns() {
    const query = (workSearch?.value || "").trim().toLocaleLowerCase();
    return workspaceRuns.filter((run) => {
      const statusMatches = activeRunFilter === "all" ||
        (activeRunFilter === "attention" && new Set(["blocked", "halted"]).has(run.status)) ||
        (activeRunFilter === "running" && new Set(["queued", "accepted", "running"]).has(run.status)) ||
        run.status === activeRunFilter;
      const queryMatches = !query || `${run.title || ""} ${run.run_id || ""}`
        .toLocaleLowerCase()
        .includes(query);
      return statusMatches && queryMatches;
    });
  }

  function updateWorkMetrics() {
    metricActive.textContent = String(
      workspaceRuns.filter((run) => new Set(["queued", "accepted", "running"]).has(run.status)).length,
    );
    metricAttention.textContent = String(
      workspaceRuns.filter((run) => new Set(["blocked", "halted"]).has(run.status)).length,
    );
    metricComplete.textContent = String(workspaceRuns.filter((run) => run.status === "complete").length);
  }

  function renderRunList() {
    const runs = visibleRuns();
    runList.replaceChildren();
    if (!runs.length) {
      const empty = element("div", "run-empty");
      empty.append(
        element("span", "", workspaceRuns.length ? "⌕" : "+"),
        element("h3", "", workspaceRuns.length ? "No jobs match this view" : "Your queue is ready"),
        element(
          "p",
          "",
          workspaceRuns.length
            ? "Try another status or search term."
            : "Email a teammate or write a request above. Every accepted commission appears here with one accountable record.",
        ),
      );
      if (!workspaceRuns.length) {
        const address = activeCommissionAddress();
        const start = element(
          "a",
          "queue-start",
          address ? "Commission the first job" : "Finish email setup",
        );
        start.dataset.firstJobLink = "queue";
        start.href = address
          ? commissionMailto(address, "My first Rally job")
          : "?view=teammates";
        if (!address) {
          start.addEventListener("click", (event) => {
            event.preventDefault();
            showWorkspaceView("teammates");
          });
        }
        empty.append(start);
      }
      runList.append(empty);
      return;
    }

    runs.forEach((run) => {
      const button = element("button", "run-row");
      button.type = "button";
      button.classList.toggle("is-active", run.run_id === activeRunId);
      button.dataset.runId = run.run_id;
      const status = element("span", `run-status is-${run.status}`, runStatus(run.status));
      const heading = element("b", "", run.title || run.run_id);
      const meta = element("small", "", `${run.run_id} · ${shortTime(run.updated_at)}`);
      const progress = element("span", "run-progress");
      const total = Math.max(0, Number(run.total_items) || 0);
      const done = Math.min(total, Math.max(0, Number(run.done_items) || 0));
      const bar = element("i");
      bar.style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
      progress.append(bar);
      const count = element("em", "", `${done}/${total} checked`);
      button.append(status, heading, meta, progress, count);
      button.addEventListener("click", () => {
        void openWorkspaceRun(run.run_id, {
          queuedFallback: new Set(["queued", "accepted"]).has(run.status),
          fallbackTitle: run.title || "",
        });
      });
      runList.append(button);
    });
  }

  function receiptMetric(value, label) {
    const metric = element("div");
    metric.append(element("b", "", String(value ?? 0)), element("span", "", label));
    return metric;
  }

  function renderRunDetail(record) {
    runDetail.replaceChildren();
    const header = element("header", "run-detail-header");
    const copy = element("div");
    copy.append(
      element("span", `run-status is-${record.status}`, runStatus(record.status)),
      element("h2", "", record.title || record.run_id),
      element("p", "", `${record.run_id} · updated ${shortTime(record.updated_at)}`),
    );
    const total = Math.max(0, Number(record.progress?.total) || 0);
    const done = Math.min(total, Math.max(0, Number(record.progress?.done) || 0));
    const score = element("div", "run-score");
    score.style.setProperty("--progress", `${total ? Math.round((done / total) * 100) : 0}%`);
    score.append(element("b", "", `${done}/${total}`), element("span", "", "checked"));
    header.append(copy, score);

    const receipts = element("section", "receipt-metrics");
    receipts.setAttribute("aria-label", "Value receipt");
    receipts.append(
      receiptMetric(record.value_receipt?.independently_verified, "independent checks"),
      receiptMetric(record.value_receipt?.evidence_receipts, "evidence receipts"),
      receiptMetric(record.value_receipt?.model_families, "model families"),
      receiptMetric(record.value_receipt?.self_approved, "self-approved"),
    );

    const checklistSection = element("section", "detail-section");
    checklistSection.append(element("p", "detail-label", "Authoritative checklist"));
    const checklist = element("ol", "detail-checklist");
    (record.checklist || []).forEach((item) => {
      const row = element("li");
      const mark = element("span", `check-state is-${item.state}`, item.state === "done" ? "✓" : "·");
      const body = element("div");
      body.append(element("b", "", item.description || item.id));
      const custody = item.verified_by
        ? `${item.owner || "Worker"} → verified by ${item.verified_by}`
        : item.owner ? `Owned by ${item.owner}` : "Awaiting assignment";
      body.append(element("small", "", custody));
      if (item.evidence) body.append(element("p", "", item.evidence));
      row.append(mark, body);
      checklist.append(row);
    });
    if (!checklist.children.length) checklist.append(element("li", "detail-empty-line", "Rally is preparing the checklist."));
    checklistSection.append(checklist);

    const activitySection = element("section", "detail-section");
    activitySection.append(element("p", "detail-label", "Latest activity"));
    const activity = element("div", "detail-activity");
    (record.timeline || []).slice(-8).reverse().forEach((entry) => {
      const item = element("article");
      const top = element("div");
      top.append(
        element("b", "", entry.label || entry.actor || "Rally"),
        element("time", "", shortTime(entry.at)),
      );
      item.append(top, element("p", "", entry.narrative || "State updated."));
      activity.append(item);
    });
    if (!activity.children.length) activity.append(element("p", "detail-empty-line", "No activity has been recorded yet."));
    activitySection.append(activity);

    runDetail.append(header, receipts, checklistSection, activitySection);
  }

  function renderQueuedRun(runId, title) {
    const waiting = element("div", "run-detail-empty is-queued");
    waiting.append(
      element("span", "", "✓"),
      element("h2", "", "Accepted and queued"),
      element(
        "p",
        "",
        `${title || "This job"} is safely in Rally. Its checklist and worker activity will appear here as execution starts.`,
      ),
      element("code", "", runId),
    );
    runDetail.replaceChildren(waiting);
  }

  async function openWorkspaceRun(
    runId,
    { queuedFallback = false, fallbackTitle = "", silent = false, signal = null } = {},
  ) {
    if (!silent) {
      activeRunId = runId;
      renderRunList();
      runDetail.setAttribute("aria-busy", "true");
      const loading = element("div", "run-detail-empty");
      loading.append(element("span", "", "↻"), element("h2", "", "Opening the evidence record…"));
      runDetail.replaceChildren(loading);
    }
    try {
      const record = await workspaceApi(
        `/v1/workspace/runs/${encodeURIComponent(runId)}`,
        signal ? { signal } : {},
      );
      if (activeRunId === runId) renderRunDetail(record);
      return true;
    } catch (error) {
      if (silent || dashboard.hidden) {
        return false;
      } else if (queuedFallback) {
        renderQueuedRun(runId, fallbackTitle);
      } else {
        const failed = element("div", "run-detail-empty is-error");
        failed.append(element("span", "", "!"), element("h2", "", "Could not open this job"), element("p", "", error.message));
        runDetail.replaceChildren(failed);
      }
      return false;
    } finally {
      if (!silent) runDetail.setAttribute("aria-busy", "false");
    }
  }

  async function loadWorkspaceRuns({
    openRunId = "",
    provisional = null,
    refreshActive = false,
    silent = false,
    signal = null,
  } = {}) {
    try {
      const result = await workspaceApi(
        "/v1/workspace/runs?limit=60",
        signal ? { signal } : {},
      );
      workspaceRuns = Array.isArray(result.runs) ? result.runs : [];
      if (provisional && !workspaceRuns.some((run) => run.run_id === provisional.run_id)) {
        workspaceRuns.unshift(provisional);
      }
      updateWorkMetrics();
      if (!assistantSetupManuallyToggled && !commissionHub.classList.contains("is-composing")) {
        setAssistantSetupCollapsed(workspaceRuns.length > 0);
      }
      renderRunList();
      const activeRunStillVisible = workspaceRuns.some((run) => run.run_id === activeRunId);
      const nextRunId = openRunId ||
        (refreshActive && activeRunStillVisible ? activeRunId : "") ||
        (!activeRunId && workspaceRuns[0]?.run_id) || "";
      if (nextRunId) {
        await openWorkspaceRun(nextRunId, {
          queuedFallback: Boolean(provisional && nextRunId === provisional.run_id),
          fallbackTitle: provisional?.title || "",
          silent,
          signal,
        });
      }
      return true;
    } catch (error) {
      if (silent || dashboard.hidden) return false;
      workspaceRuns = provisional ? [provisional] : [];
      updateWorkMetrics();
      if (provisional) {
        activeRunId = provisional.run_id;
        renderRunList();
        renderQueuedRun(provisional.run_id, provisional.title);
      } else {
        const failed = element("div", "run-empty is-error");
        failed.append(element("span", "", "!"), element("h3", "", "Work queue unavailable"), element("p", "", error.message));
        runList.replaceChildren(failed);
      }
      return false;
    }
  }

  function canPollWorkspace() {
    return Boolean((idToken || sessionToken) && !dashboard.hidden && !document.hidden);
  }

  function setWorkspaceLiveStatus(state) {
    if (!workspaceLiveStatus) return;
    workspaceLiveStatus.dataset.state = state;
    workspaceLiveStatus.textContent = state === "fresh"
      ? "Live · updated now"
      : state === "retrying"
        ? "Live · reconnecting"
        : state === "syncing"
          ? "Connecting live updates"
          : "Updates paused";
  }

  function stopWorkspacePolling() {
    if (workspaceRefreshTimer) window.clearTimeout(workspaceRefreshTimer);
    workspaceRefreshTimer = 0;
    workspaceRefreshController?.abort();
  }

  function scheduleWorkspaceRefresh(delay = WORKSPACE_REFRESH_INTERVAL_MS) {
    if (workspaceRefreshTimer) window.clearTimeout(workspaceRefreshTimer);
    workspaceRefreshTimer = 0;
    if (!canPollWorkspace()) return;
    workspaceRefreshTimer = window.setTimeout(() => {
      workspaceRefreshTimer = 0;
      void refreshWorkspaceFromRunner();
    }, delay);
  }

  async function refreshWorkspaceFromRunner() {
    if (!canPollWorkspace() || workspaceRefreshInFlight) return;
    workspaceRefreshInFlight = true;
    const controller = new AbortController();
    workspaceRefreshController = controller;
    try {
      const refreshed = await loadWorkspaceRuns({
        refreshActive: true,
        silent: true,
        signal: controller.signal,
      });
      if (!controller.signal.aborted && canPollWorkspace()) {
        setWorkspaceLiveStatus(refreshed ? "fresh" : "retrying");
      }
    } finally {
      if (workspaceRefreshController === controller) workspaceRefreshController = null;
      workspaceRefreshInFlight = false;
      scheduleWorkspaceRefresh(controller.signal.aborted ? 0 : WORKSPACE_REFRESH_INTERVAL_MS);
    }
  }

  function startWorkspacePolling(initialLoadSucceeded) {
    stopWorkspacePolling();
    if (!canPollWorkspace()) return;
    setWorkspaceLiveStatus(initialLoadSucceeded ? "fresh" : "retrying");
    scheduleWorkspaceRefresh();
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
    if (!item?.activation_available || item?.readiness === "provider_app") return "Rally setup pending";
    if (item.oauth_ready && item.endpoint_required) return "Configure & connect";
    if (item.oauth_ready) return `Connect with ${item.name}`;
    return "Add restricted token";
  }

  function connectionMethod(item) {
    if (!item?.activation_available || item?.readiness === "provider_app") {
      return "Provider app registration required";
    }
    if (item.oauth_ready && item.endpoint_required) return "OAuth · one setup detail";
    if (item.oauth_ready) return "One-click OAuth";
    return "Restricted credential · advanced";
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
      const method = card.querySelector("[data-connection-method]");
      const footer = card.querySelector("footer");
      let apiKeyAction = card.querySelector("[data-api-key-action]");
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
      if (method) method.textContent = connectionMethod(item);
      const showApiKeyChoice = Boolean(item?.oauth_ready && item?.token_ready && !record);
      if (showApiKeyChoice && !apiKeyAction) {
        apiKeyAction = document.createElement("button");
        apiKeyAction.type = "button";
        apiKeyAction.className = "api-key-action";
        apiKeyAction.dataset.apiKeyAction = "";
        apiKeyAction.textContent = "Advanced setup";
        apiKeyAction.setAttribute("aria-label", `Advanced: use an existing ${item.name} API key`);
        footer.insertBefore(apiKeyAction, primary);
      }
      if (apiKeyAction) apiKeyAction.hidden = !showApiKeyChoice;
      primary.textContent = primaryLabel(item, record);
      primary.disabled = !record && (!item?.activation_available || item?.readiness === "provider_app");
    });
    const certified = records.filter(
      (record) => record.status === "ready" && record.certification?.live_read,
    ).length;
    connectionCounts.forEach((count) => { count.textContent = String(certified); });
  }

  async function loadConnectionSetup() {
    grid.setAttribute("aria-busy", "true");
    document.querySelectorAll("[data-connector]").forEach((card) => {
      const state = card.querySelector(".connection-state");
      const primary = card.querySelector("[data-primary-action]");
      if (state) state.textContent = "Loading…";
      if (primary) primary.disabled = true;
    });
    try {
      const [catalog, stored] = await Promise.all([
        api("/v1/connectors"),
        api("/v1/connections"),
      ]);
      connectors = new Map((catalog.connectors || []).map((item) => [item.id, item]));
      updateCards(stored.connections || []);
    } catch (error) {
      connectors = new Map();
      connectionRecords = new Map();
      connectionCounts.forEach((count) => { count.textContent = "0"; });
      document.querySelectorAll("[data-connector]").forEach((card) => {
        card.classList.add("needs-attention");
        const state = card.querySelector(".connection-state");
        const primary = card.querySelector("[data-primary-action]");
        if (state) state.textContent = "Temporarily unavailable";
        if (primary) primary.disabled = true;
      });
      const connectionsView = [...workspaceViews]
        .find((view) => view.dataset.workspaceView === "connections");
      if (connectionsView && !connectionsView.hidden) {
        showToast(error.message || "Connections are temporarily unavailable.", "warning");
      }
    } finally {
      grid.setAttribute("aria-busy", "false");
    }
  }

  async function showDashboard(account, { focusHeading = true } = {}) {
    setAccount(account);
    signedOut.hidden = true;
    dashboard.hidden = false;
    signOutButton.hidden = false;
    setWorkspaceLiveStatus("syncing");
    const requestedView = new URLSearchParams(window.location.search).get("view");
    const initialView = new Set(["work", "teammates", "workforce", "connections", "policy"])
      .has(requestedView) ? requestedView : "work";
    showWorkspaceView(initialView, { focusHeading: false });
    const [workspaceLoaded] = await Promise.all([
      loadWorkspaceRuns(),
      loadTeammateSetup(account),
      loadConnectionSetup(),
    ]);
    startWorkspacePolling(workspaceLoaded);
    if (focusHeading) {
      const activeView = [...workspaceViews]
        .find((view) => view.dataset.workspaceView === initialView);
      focusSoon(activeView?.querySelector("h1") || dashboardTitle);
    }
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
      magicLink: state.get("rally-magic-link") || "",
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

  async function consumeMagicLink(token) {
    configurationNote.textContent = "Verifying your one-time company email link…";
    const response = await fetch(`${safeApiBase()}/v1/auth/magic-link/consume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!response.ok) {
      if (response.status >= 500) {
        throw new Error("Secure email sign-in is temporarily unavailable. Try again shortly.");
      }
      throw new Error("That secure link expired or was already used. Request a new one.");
    }
    const result = await response.json();
    if (!result || typeof result.login_code !== "string") {
      throw new Error("Rally received an invalid sign-in response. Request a new link.");
    }
    await exchangeRedirectCode(result.login_code);
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
    if (!configuredGoogle) {
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
      advancedTokenButton.textContent = "Advanced: use an existing API key";
      dialogSafetyCopy.textContent = "Provider tokens are exchanged and encrypted server-side. This page receives only connection status.";
      dialogSubmit.textContent = `Continue to ${item.name}`;
    } else {
      dialogEyebrow.textContent = "API credential option";
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
      formStatus.textContent = dialog.open ? message : "";
      if (!dialog.open) {
        showToast(`${message} Retry provider sign-in from this card.`, "warning");
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
    if (button.matches("[data-api-key-action]")) {
      openDialog(item, "token", card.dataset.kind || "bearer_token");
      return;
    }
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

  workspaceNav.forEach((button) => {
    button.addEventListener("click", () => showWorkspaceView(button.dataset.workspaceNav));
  });
  document.querySelectorAll("[data-open-teammates]").forEach((button) => {
    button.addEventListener("click", () => showWorkspaceView("teammates"));
  });
  document.querySelectorAll("[data-first-job-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (activeCommissionAddress()) return;
      event.preventDefault();
      showWorkspaceView("teammates");
    });
  });
  document.querySelector("[data-focus-teammate-form]").addEventListener("click", () => {
    teammateForm.scrollIntoView({
      behavior: reducedMotion.matches ? "auto" : "smooth",
      block: "start",
    });
    focusSoon(teammateFormTitle);
  });
  document.querySelectorAll("[data-open-connections]").forEach((button) => {
    button.addEventListener("click", () => showWorkspaceView("connections"));
  });
  document.querySelectorAll("[data-back-to-work]").forEach((button) => {
    button.addEventListener("click", () => showWorkspaceView("work"));
  });
  workSearch.addEventListener("input", renderRunList);
  runFilters.forEach((button) => {
    button.addEventListener("click", () => {
      activeRunFilter = button.dataset.runFilter;
      runFilters.forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
      renderRunList();
    });
  });

  assistantPersonaButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectedAssistant = button.dataset.assistantPersona;
      syncAssistantSetup({ prefill: !jobForm.hidden });
    });
  });
  expertiseButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectedExpertise = button.dataset.expertise;
      syncAssistantSetup({ prefill: !jobForm.hidden });
    });
  });
  autonomyButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectedAutonomy = button.dataset.autonomy;
      syncAssistantSetup();
    });
  });
  jobSecondWind.addEventListener("change", () => {
    selectedAutonomy = jobSecondWind.checked ? "resilient" : "guarded";
    syncAssistantSetup();
  });

  openJobComposerButtons.forEach((button) => {
    button.addEventListener("click", () => openJobComposer(button));
  });
  assistantSetupToggle.addEventListener("click", () => {
    assistantSetupManuallyToggled = true;
    setAssistantSetupCollapsed(!commissionHub.classList.contains("is-collapsed"));
  });
  document.querySelector("[data-close-job-composer]").addEventListener("click", closeJobComposer);
  document.querySelector("[data-compose-another]").addEventListener("click", (event) => {
    openJobComposer(event.currentTarget);
  });
  document.querySelector("[data-view-accepted-job]").addEventListener("click", async () => {
    if (!acceptedRunId) return;
    await openWorkspaceRun(acceptedRunId, {
      queuedFallback: true,
      fallbackTitle: jobReceiptTitle.textContent,
    });
    runDetail.scrollIntoView({
      behavior: reducedMotion.matches ? "auto" : "smooth",
      block: "start",
    });
    focusSoon(runDetail);
  });

  jobForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!jobForm.reportValidity()) return;
    const title = jobTitle.value.trim();
    const goal = jobGoal.value.trim();
    const sourceRunId = jobSourceRun.value.trim();
    const secondWind = jobSecondWind.checked;
    if (!title || !goal) {
      jobFormStatus.textContent = "Add a title and a clear definition of done.";
      focusSoon(!title ? jobTitle : jobGoal);
      return;
    }
    const payload = { title, goal, second_wind: secondWind };
    if (sourceRunId) payload.source_run_id = sourceRunId;
    if (!pendingJobIdempotencyKey) pendingJobIdempotencyKey = newJobIdempotencyKey();

    jobSubmit.disabled = true;
    jobForm.setAttribute("aria-busy", "true");
    jobFormStatus.textContent = "Accepting the job and attaching workspace policy…";
    try {
      const result = await workspaceApi("/v1/workspace/jobs", {
        method: "POST",
        headers: { "Idempotency-Key": pendingJobIdempotencyKey },
        body: JSON.stringify(payload),
      });
      const runId = acceptedRunIdFrom(result);
      if (!runId) {
        throw new Error("Rally did not return a job receipt. Check the queue before retrying.");
      }
      const acceptedAt = result.accepted_at || result.job?.accepted_at || new Date().toISOString();
      const status = result.status || result.job?.status || "queued";
      const provisional = {
        run_id: runId,
        title,
        status,
        updated_at: acceptedAt,
        done_items: 0,
        total_items: 0,
      };

      jobForm.reset();
      pendingJobIdempotencyKey = "";
      jobSecondWind.checked = selectedAutonomy === "resilient";
      jobForm.querySelector(".job-continuity").open = false;
      jobFormStatus.textContent = "";
      showJobAcceptance({ runId, title, status, acceptedAt, secondWind });
      showToast(`${title} was accepted into Rally. Its governed record is open below.`);
      await loadWorkspaceRuns({ openRunId: runId, provisional });
    } catch (error) {
      jobFormStatus.textContent = error.message || "Rally could not accept this job. Nothing was queued.";
    } finally {
      jobSubmit.disabled = false;
      jobForm.setAttribute("aria-busy", "false");
    }
  });
  jobForm.addEventListener("input", () => {
    if (jobForm.getAttribute("aria-busy") !== "true") pendingJobIdempotencyKey = "";
  });

  teammateRole.addEventListener("change", () => {
    applyRoleSuggestion();
    const isCustom = teammateRole.value === "custom";
    customRoleField.hidden = !isCustom;
    customRole.required = isCustom;
    if (isCustom) focusSoon(customRole);
  });

  teammateForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const provider = selectedEmailProvider();
    const method = emailMethods.querySelector('input[name="connection_method"]:checked');
    if (!provider || !method || !teammateForm.reportValidity()) return;
    const senderValues = allowedSenders.value
      .split(/[\n,]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    const payload = {
      name: teammateName.value.trim(),
      role: teammateRole.value,
      custom_role: teammateRole.value === "custom" ? customRole.value.trim() : null,
      human_owner_email: teammateOwner.value.trim(),
      email_local_part: emailLocal.value.trim(),
      email_domain: provider.id === "rally_trial" ? null : emailDomain.value.trim(),
      email_provider: provider.id,
      connection_method: method.value,
      reachability: teammateReachability.value,
      allowed_senders: senderValues,
    };
    teammateSubmit.disabled = true;
    teammateForm.setAttribute("aria-busy", "true");
    teammateFormStatus.textContent = "Reserving this workspace identity…";
    try {
      const created = await api("/v1/teammates", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      teammateRecords.push(created);
      renderTeammates();
      teammateForm.reset();
      teammateOwner.value = currentAccount?.email || "";
      const companyDomain = inferredCompanyDomain(currentAccount);
      emailDomain.disabled = false;
      emailDomain.required = true;
      emailDomain.value = companyDomain ? `ai.${companyDomain}` : "";
      customRoleField.hidden = true;
      customRole.required = false;
      applyRoleSuggestion();
      syncProviderForm();
      const state = teammateStatusLabels[created.email?.status] || "Setup required";
      teammateFormStatus.textContent = `${created.email.address} is reserved. ${state}; it has not been labeled live.`;
      showToast(
        `${created.name} now belongs to this workspace. ${state} before anyone can commission it.`,
        "neutral",
      );
    } catch (error) {
      teammateFormStatus.textContent = error.message || "Rally could not save this teammate.";
    } finally {
      teammateSubmit.disabled = emailProviders.size === 0;
      teammateForm.setAttribute("aria-busy", "false");
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
    stopWorkspacePolling();
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

  magicLinkForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!configuredApi || !magicLinkForm.reportValidity()) return;
    magicLinkSubmit.disabled = true;
    magicLinkStatus.dataset.tone = "pending";
    magicLinkStatus.textContent = "Preparing a one-time link…";
    try {
      const response = await fetch(`${safeApiBase()}/v1/auth/magic-link/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: magicLinkEmail.value }),
      });
      if (!response.ok) throw new Error("Secure email sign-in is temporarily unavailable.");
      magicLinkStatus.dataset.tone = "success";
      magicLinkStatus.textContent = "Check your inbox. If this company email is invited, your secure link is on its way.";
      magicLinkEmail.value = "";
    } catch (error) {
      magicLinkStatus.dataset.tone = "error";
      magicLinkStatus.textContent = error.message || "Secure email sign-in is temporarily unavailable.";
    } finally {
      magicLinkSubmit.disabled = false;
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopWorkspacePolling();
      if (!dashboard.hidden) setWorkspaceLiveStatus("paused");
      return;
    }
    if (canPollWorkspace()) void refreshWorkspaceFromRunner();
  });

  async function start() {
    const redirect = takeRedirectState();
    if (redirect.error) {
      configurationNote.textContent = "Secure sign-in did not complete. Please try again.";
    } else if (redirect.magicLink) {
      try {
        await consumeMagicLink(redirect.magicLink);
      } catch (error) {
        resetSession(error.message || "Secure email sign-in failed. Request a new link.");
      }
    } else if (redirect.code) {
      try {
        await exchangeRedirectCode(redirect.code);
        if (redirect.connector || redirect.connectionStatus) {
          showWorkspaceView("connections", { focusHeading: false });
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

  syncAssistantSetup();
  start().catch((error) => resetSession(error.message || "Sign-in failed. Try again."));
})();
