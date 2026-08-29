const header = document.querySelector("[data-header]");
const dialog = document.querySelector("[data-setup-dialog]");
const openButtons = document.querySelectorAll("[data-open-setup]");
const closeButton = document.querySelector("[data-close-setup]");
const tabs = document.querySelectorAll("[data-setup-tab]");
const panels = document.querySelectorAll("[data-setup-panel]");

const updateHeader = () => header?.classList.toggle("is-scrolled", window.scrollY > 18);
updateHeader();
window.addEventListener("scroll", updateHeader, { passive: true });

openButtons.forEach((button) => button.addEventListener("click", () => dialog?.showModal()));
closeButton?.addEventListener("click", () => dialog?.close());
dialog?.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const target = tab.dataset.setupTab;
    tabs.forEach((item) => {
      const active = item === tab;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", String(active));
    });
    panels.forEach((panel) => {
      const active = panel.dataset.setupPanel === target;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
  });
});
