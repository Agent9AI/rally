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
  const button = document.querySelector("[data-google-redirect-button]");
  const note = document.querySelector("[data-configuration-note]");
  const loginUri = "https://rally.agent9.dev/admin/google/callback";
  const configured = /^[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$/.test(
    config.googleClientId || ""
  );

  if (!configured) {
    note.textContent = "Secure sign-in is waiting for the Rally Google web client.";
    return;
  }

  const script = document.createElement("script");
  script.src = "https://accounts.google.com/gsi/client";
  script.async = true;
  script.defer = true;
  script.addEventListener("load", () => {
    window.google.accounts.id.initialize({
      client_id: config.googleClientId,
      ux_mode: "redirect",
      login_uri: loginUri,
      auto_select: false,
    });
    window.google.accounts.id.renderButton(button, {
      type: "standard",
      theme: "outline",
      size: "large",
      text: "continue_with",
      shape: "pill",
      width: 300,
    });
    note.textContent = "Your Google password is never shared with Rally.";
  });
  script.addEventListener("error", () => {
    note.textContent = "Google sign-in could not load. Check your connection and retry.";
  });
  document.head.append(script);
})();
