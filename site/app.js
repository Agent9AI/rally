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

const apiRoot = document.querySelector('meta[name="rally-console-api"]')?.content?.replace(/\/$/, "");
const runList = document.querySelector("[data-run-list]");
const threadPane = document.querySelector("[data-thread-pane]");
const threadHeader = document.querySelector("[data-thread-header]");
const threadStream = document.querySelector("[data-thread-stream]");
const detailPane = document.querySelector("[data-detail-pane]");
const liveIndicator = document.querySelector("[data-console-live]");
const updatedLabel = document.querySelector("[data-console-updated]");
const runSearch = document.querySelector("[data-run-search]");

const consoleState = {
  runs: [],
  selectedId: null,
  query: "",
  detailRequest: null,
  refreshing: false,
};

const element = (tag, className, content) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
};

const replace = (node, ...children) => {
  if (node) node.replaceChildren(...children.filter(Boolean));
};

const statusMeta = (status) => ({
  complete: { label: "Complete", className: "complete" },
  running: { label: "Running", className: "review" },
  blocked: { label: "Blocked", className: "blocked" },
  halted: { label: "Halted", className: "blocked" },
}[status] || { label: "Unknown", className: "blocked" });

const relativeTime = (value) => {
  const stamp = Date.parse(value || "");
  if (!Number.isFinite(stamp)) return "Unknown";
  const seconds = Math.max(0, Math.round((Date.now() - stamp) / 1000));
  if (seconds < 60) return "Now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
};

const clockTime = (value) => {
  const stamp = Date.parse(value || "");
  if (!Number.isFinite(stamp)) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(stamp);
};

const setLiveState = (state, label) => {
  if (!liveIndicator) return;
  liveIndicator.classList.toggle("is-live", state === "live");
  liveIndicator.classList.toggle("is-error", state === "error");
  const textNode = liveIndicator.querySelector("span");
  if (textNode) textNode.textContent = label;
};

async function fetchJson(path, signal) {
  const response = await fetch(`${apiRoot}${path}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new Error(`Live console returned ${response.status}`);
  return response.json();
}

function loadingState(title, detail) {
  const wrapper = element("div", "console-loading large");
  wrapper.append(element("i"), element("b", "", title), element("span", "", detail));
  return wrapper;
}

function errorState(title, detail, retry) {
  const wrapper = element("div", "console-error");
  wrapper.append(element("span", "error-icon", "!"), element("b", "", title), element("p", "", detail));
  if (retry) {
    const button = element("button", "", "Try again");
    button.type = "button";
    button.addEventListener("click", retry);
    wrapper.append(button);
  }
  return wrapper;
}

function emptyState() {
  const wrapper = element("div", "console-empty");
  wrapper.append(
    element("span", "empty-icon", "◇"),
    element("b", "", consoleState.query ? "No matching public runs" : "No public runs yet"),
    element("p", "", consoleState.query
      ? "Try a different run ID, title, or status."
      : "A run appears only after the authoritative runner publishes an explicitly public record."),
  );
  return wrapper;
}

function filteredRuns() {
  const query = consoleState.query.trim().toLowerCase();
  if (!query) return consoleState.runs;
  return consoleState.runs.filter((run) =>
    [run.run_id, run.title, run.status].some((value) => String(value || "").toLowerCase().includes(query))
  );
}

function renderRunList() {
  if (!runList) return;
  const runs = filteredRuns();
  if (!runs.length) {
    replace(runList, emptyState());
    return;
  }
  const fragment = document.createDocumentFragment();
  runs.forEach((run) => {
    const status = statusMeta(run.status);
    const button = element("button", `run-row${run.run_id === consoleState.selectedId ? " selected" : ""}`);
    button.type = "button";
    button.dataset.runId = run.run_id;
    button.setAttribute("aria-pressed", String(run.run_id === consoleState.selectedId));
    button.addEventListener("click", () => selectRun(run.run_id));
    const avatar = element("span", `run-avatar ${run.status === "complete" ? "gemini" : "human"}`,
      run.status === "complete" ? "✓" : "R");
    const copy = element("span", "run-copy");
    const heading = element("span");
    heading.append(element("b", "", run.title || run.run_id), element("time", "", relativeTime(run.updated_at)));
    const summary = element("p", "", `${run.done_items || 0}/${run.total_items || 0} verified · ${run.turn || 0} turns`);
    const chip = element("span", `status-chip ${status.className}`, status.label);
    copy.append(heading, summary, chip);
    button.append(avatar, copy);
    fragment.append(button);
  });
  replace(runList, fragment);
}

function avatarFor(entry) {
  if (entry.kind === "commission") return { letter: "T", className: "human" };
  if (entry.kind === "coordination") return { letter: "G", className: "coordinator" };
  if (entry.actor === "claude") return { letter: "C", className: "claude" };
  return { letter: "G", className: "gemini" };
}

function messageBadge(entry) {
  if (entry.kind === "coordination") return "Governed";
  if (entry.kind === "report") return "Final report";
  if ((entry.changes || []).some((change) => change.verified_by)) return "Verifier";
  return entry.kind === "turn" ? "Worker" : "Commissioner";
}

function markdownText(value) {
  return String(value || "")
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function narrativeNode(entry) {
  if (entry.kind !== "report") return element("p", "message-narrative", entry.narrative || "No narrative recorded.");
  const wrapper = element("div", "report-copy");
  const blocks = String(entry.narrative || "No report recorded.").split(/\n{2,}/);
  blocks.forEach((block) => {
    const lines = block.split("\n").filter((line) => line.trim());
    lines.forEach((line) => {
      if (/^#{1,4}\s+/.test(line)) {
        wrapper.append(element("h4", "", markdownText(line.replace(/^#{1,4}\s+/, ""))));
      } else {
        const bullet = /^-\s+/.test(line);
        wrapper.append(element("p", bullet ? "report-line" : "", `${bullet ? "• " : ""}${markdownText(line.replace(/^-\s+/, ""))}`));
      }
    });
  });
  return wrapper;
}

function renderChange(change) {
  if (change.state === "done" && change.verified_by) {
    const receipt = element("div", "verification-receipt");
    const icon = element("span", "", "✓");
    const copy = element("div");
    copy.append(
      element("b", "", `${change.id} independently verified`),
      element("small", "", `owner=${change.owner || "unclaimed"} · verified_by=${change.verified_by}`),
    );
    receipt.append(icon, copy);
    if (change.evidence) receipt.append(element("p", "receipt-evidence", change.evidence));
    return receipt;
  }
  const update = element("div", "state-update");
  update.append(
    element("span", "", change.id || "item"),
    element("b", "", String(change.state || "updated").replaceAll("-", " ")),
    element("span", "", change.owner ? `owner=${change.owner}` : "unclaimed"),
  );
  if (change.evidence) update.append(element("small", "state-evidence", change.evidence));
  return update;
}

function renderMessage(entry, run) {
  const avatar = avatarFor(entry);
  const wrapper = element("div", `thread-message${entry.kind === "commission" ? " compact-message" : ""}`);
  wrapper.append(element("span", `message-avatar ${avatar.className}`, avatar.letter));
  const cardClasses = ["message-card"];
  if (entry.kind === "commission") cardClasses.push("human-message");
  if (entry.kind === "coordination") cardClasses.push("coordinator-message");
  if ((entry.changes || []).some((change) => change.verified_by)) cardClasses.push("verification-message");
  if (entry.kind === "report") cardClasses.push("report-message");
  const card = element("div", cardClasses.join(" "));
  const meta = element("div", "message-meta");
  const identity = element("div");
  identity.append(element("b", "", entry.label || entry.actor || "Rally"));
  identity.append(element("span", "verified-mark", messageBadge(entry)));
  const when = entry.kind === "turn" ? `Turn ${entry.turn}` : clockTime(entry.at);
  meta.append(identity, element("time", "", when));
  card.append(meta, narrativeNode(entry));

  const tags = [];
  if (entry.model) tags.push(entry.model);
  if (entry.kind === "coordination") {
    if (run.coordination?.framework) tags.push(run.coordination.framework);
    tags.push(...(run.coordination?.services || []));
  }
  if (tags.length) {
    const tagRow = element("div", "message-tags");
    tags.forEach((tag) => tagRow.append(element("span", "", tag)));
    card.append(tagRow);
  }
  if (entry.commit) {
    const receipt = element("div", "code-receipt");
    const line = element("div");
    line.append(element("span", "file-dot"), element("code", "", `git commit ${entry.commit}`), element("span", "diff", "recorded"));
    receipt.append(line);
    card.append(receipt);
  }
  (entry.changes || []).forEach((change) => card.append(renderChange(change)));
  wrapper.append(card);
  return wrapper;
}

function svgRing(done, total) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 96 96");
  svg.setAttribute("aria-hidden", "true");
  const track = document.createElementNS(svg.namespaceURI, "circle");
  track.setAttribute("class", "ring-track");
  track.setAttribute("cx", "48"); track.setAttribute("cy", "48"); track.setAttribute("r", "39");
  const value = document.createElementNS(svg.namespaceURI, "circle");
  value.setAttribute("class", "ring-value");
  value.setAttribute("cx", "48"); value.setAttribute("cy", "48"); value.setAttribute("r", "39");
  const ratio = total ? Math.max(0, Math.min(done / total, 1)) : 0;
  value.style.strokeDashoffset = String(245 * (1 - ratio));
  svg.append(track, value);
  return svg;
}

function renderDetail(run) {
  if (!detailPane) return;
  const fragment = document.createDocumentFragment();
  const heading = element("div", "detail-heading");
  heading.append(element("p", "label", "Run summary"), element("span", "source-badge live", "D1 LIVE"));
  fragment.append(heading);

  const done = run.progress?.done || 0;
  const total = run.progress?.total || 0;
  const ring = element("div", "completion-ring");
  ring.setAttribute("aria-label", `${done} of ${total} items verified`);
  const ringCopy = element("div");
  ringCopy.append(element("strong", "", `${done}/${total}`), element("span", "", "verified"));
  ring.append(svgRing(done, total), ringCopy);
  fragment.append(ring);

  const invariant = element("div", "invariant-box");
  invariant.append(
    element("span", "", "Completion invariant"),
    element("code", "", "owner ≠ verified_by"),
    element("small", "", run.policy?.enforced_by || "Rally deterministic runner"),
  );
  fragment.append(invariant);

  const checklistGroup = element("div", "detail-group checklist-group");
  checklistGroup.append(element("p", "label", "Authoritative checklist"));
  (run.checklist || []).forEach((item) => {
    const row = element("div", "checklist-row");
    const icon = element("span", `check-state ${item.state === "done" ? "done" : ""}`, item.state === "done" ? "✓" : "·");
    const copy = element("div");
    copy.append(element("b", "", item.description || item.id));
    const custody = item.verified_by
      ? `${item.id} · ${item.owner} → ${item.verified_by}`
      : `${item.id} · ${String(item.state || "open").replaceAll("-", " ")}`;
    copy.append(element("small", "", custody));
    row.append(icon, copy);
    checklistGroup.append(row);
  });
  if (!(run.checklist || []).length) checklistGroup.append(element("p", "detail-empty", "Scope is still being negotiated."));
  fragment.append(checklistGroup);

  const agents = element("div", "detail-group");
  agents.append(element("p", "label", "Agent roster"));
  (run.agents || []).forEach((agent) => {
    const row = element("div", "agent-row");
    row.append(element("span", `agent-dot ${agent.family === "google" ? "google" : "anthropic"}`));
    const copy = element("div");
    copy.append(element("b", "", agent.label), element("small", "", `${agent.model} · ${agent.family}`));
    row.append(copy, element("span", "", "Active"));
    agents.append(row);
  });
  fragment.append(agents);

  const provenance = element("div", "detail-group cloud-evidence");
  provenance.append(element("p", "label", "Data provenance"));
  const rows = [
    ["▣", "Runner state", "Allowlisted at source"],
    ["◇", "Cloudflare D1", run.provenance?.published_at ? `Synced ${relativeTime(run.provenance.published_at)} ago` : "Live projection"],
  ];
  if (run.coordination?.framework) {
    rows.push(["G", run.coordination.framework, (run.coordination.services || []).join(" · ")]);
  }
  rows.forEach(([icon, title, copy]) => {
    const row = element("div");
    const body = element("p");
    body.append(element("b", "", title), element("small", "", copy));
    row.append(element("span", "", icon), body, element("span", "green-check", "✓"));
    provenance.append(row);
  });
  fragment.append(provenance);
  replace(detailPane, fragment);
}

function renderRun(run) {
  const status = statusMeta(run.status);
  const headerCopy = element("div");
  const titleWrap = element("div");
  titleWrap.append(
    element("h3", "", run.title || run.run_id),
    element("p", "", `${run.run_id} · ${run.progress?.total || 0} checklist items · ${run.turn || 0} turns`),
  );
  headerCopy.append(element("span", "back-mobile", "‹"), titleWrap);
  const chip = element("span", `status-chip ${status.className}`, `Run ${status.label.toLowerCase()}`);
  replace(threadHeader, headerCopy, chip);

  const fragment = document.createDocumentFragment();
  (run.timeline || []).forEach((entry) => fragment.append(renderMessage(entry, run)));
  if (!(run.timeline || []).length) fragment.append(errorState("No timeline records", "The runner published this run without any public events."));
  replace(threadStream, fragment);
  renderDetail(run);
  threadPane?.setAttribute("aria-busy", "false");
}

function renderEmptyHeader() {
  const headerCopy = element("div");
  const titleWrap = element("div");
  titleWrap.append(
    element("h3", "", "No public runs yet"),
    element("p", "", "Waiting for an explicitly published Rally execution"),
  );
  headerCopy.append(element("span", "back-mobile", "‹"), titleWrap);
  replace(threadHeader, headerCopy, element("span", "status-chip review", "Live feed ready"));
}

async function selectRun(runId, { quiet = false } = {}) {
  if (!runId || !apiRoot) return;
  consoleState.selectedId = runId;
  renderRunList();
  consoleState.detailRequest?.abort();
  const controller = new AbortController();
  consoleState.detailRequest = controller;
  if (!quiet) {
    threadPane?.setAttribute("aria-busy", "true");
    replace(threadStream, loadingState("Loading execution timeline", "Reading the authoritative public record."));
    replace(detailPane, loadingState("Loading evidence", "Checking ownership and verifier records."));
  }
  try {
    const run = await fetchJson(`/runs/${encodeURIComponent(runId)}`, controller.signal);
    if (consoleState.selectedId === runId) renderRun(run);
  } catch (error) {
    if (error.name === "AbortError") return;
    const retry = () => selectRun(runId);
    replace(threadStream, errorState("Run detail unavailable", error.message, retry));
    replace(detailPane, errorState("Evidence unavailable", "The public record could not be read.", retry));
    threadPane?.setAttribute("aria-busy", "false");
    setLiveState("error", "Live feed interrupted");
  }
}

async function refreshConsole({ quiet = false } = {}) {
  if (!apiRoot || consoleState.refreshing) return;
  consoleState.refreshing = true;
  if (!quiet) setLiveState("connecting", "Connecting");
  try {
    const payload = await fetchJson("/runs?limit=20");
    consoleState.runs = Array.isArray(payload.runs) ? payload.runs : [];
    if (!consoleState.runs.some((run) => run.run_id === consoleState.selectedId)) {
      consoleState.selectedId = consoleState.runs[0]?.run_id || null;
    }
    renderRunList();
    if (updatedLabel) updatedLabel.textContent = `D1 updated ${relativeTime(payload.generated_at)}`;
    setLiveState("live", "Live D1 data");
    if (consoleState.selectedId) await selectRun(consoleState.selectedId, { quiet });
    else {
      renderEmptyHeader();
      replace(threadStream, emptyState());
      replace(detailPane, emptyState());
      threadPane?.setAttribute("aria-busy", "false");
    }
  } catch (error) {
    const retry = () => refreshConsole();
    replace(runList, errorState("Live console unavailable", error.message, retry));
    replace(threadStream, errorState("No sample data substituted", "Rally shows an explicit failure instead of presenting a mock as a real run.", retry));
    replace(detailPane, errorState("Evidence unavailable", "The D1 public projection did not answer.", retry));
    threadPane?.setAttribute("aria-busy", "false");
    if (updatedLabel) updatedLabel.textContent = "Live service unavailable";
    setLiveState("error", "Live feed offline");
  } finally {
    consoleState.refreshing = false;
  }
}

runSearch?.addEventListener("input", () => {
  consoleState.query = runSearch.value;
  renderRunList();
});

window.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    runSearch?.focus();
  }
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshConsole({ quiet: true });
});

if (apiRoot && runList && threadStream && detailPane) {
  refreshConsole();
  window.setInterval(() => refreshConsole({ quiet: true }), 15000);
}
