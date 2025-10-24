const state = {
  token: null,
  user: null,
  config: null,
  criteria: [],
  summaries: new Map(),
  summaryPromises: new Map(),
  draftPromises: new Map(),
  viewer: {
    label: null,
    nextPageToken: null,
    loading: false,
    pageSize: 10,
    loadedCount: 0,
  },
};

const CATEGORY_LABELS = {
  spam: "Delete as spam",
  receipt: "Receipt (archive)",
  useful_archive: "Archive with label",
  requires_response: "Keep in inbox - requires response",
  should_read: "Keep in inbox - should read",
};

const ACTIONS_REQUIRING_LABEL = new Set(["useful_archive"]);

const loginView = document.getElementById("login-view");
const appView = document.getElementById("app-view");
const userEmailEl = document.getElementById("user-email");
const cleanupStatus = document.getElementById("cleanup-status");
const cleanupSummary = document.getElementById("cleanup-summary");
const cleanupCounts = document.getElementById("cleanup-counts");
const cleanupLog = document.getElementById("cleanup-log");
const cleanupShortcuts = document.getElementById("cleanup-shortcuts");
const batchSizeInput = document.getElementById("batch-size");
const runCleanupBtn = document.getElementById("run-cleanup");
const cancelCleanupBtn = document.getElementById("cancel-cleanup");
const logoutBtn = document.getElementById("logout-btn");
const connectGmailBtn = document.getElementById("connect-gmail");
const newCriterionForm = document.getElementById("new-criterion-form");
const newCriterionText = document.getElementById("new-criterion-text");
const criteriaListEl = document.getElementById("criteria-list");
const refreshCriteriaBtn = document.getElementById("refresh-criteria");
const criteriaStatus = document.getElementById("criteria-status");
// Viewer elements
const viewerStatus = document.getElementById("viewer-status");
const viewerList = document.getElementById("viewer-list");
const loadInboxBtn = document.getElementById("load-inbox");
const loadRequiresBtn = document.getElementById("load-requires");
const loadShouldBtn = document.getElementById("load-should");
const loadMoreBtn = document.getElementById("viewer-load-more");
const loadMoreRow = document.getElementById("viewer-load-more-row");

document.addEventListener("DOMContentLoaded", () => {
  init().catch((error) => {
    console.error("Failed to initialise UI", error);
    setStatus(cleanupStatus, `Failed to load configuration: ${error.message}`, true);
  });
});

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function sanitizeAndCloneHtml(html) {
  const template = document.createElement("template");
  template.innerHTML = html || "";
  const forbiddenSelector = "script,style,link,meta,iframe,object,embed";
  template.content.querySelectorAll(forbiddenSelector).forEach((node) => node.remove());
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_ELEMENT, null);
  while (walker.nextNode()) {
    const el = walker.currentNode;
    if (!(el instanceof Element)) continue;
    [...el.attributes].forEach((attr) => {
      if (attr.name.startsWith("on") || attr.name === "style") {
        el.removeAttribute(attr.name);
      }
    });
  }
  return template.content.cloneNode(true);
}

function stripCodeFences(text) {
  if (!text) return "";
  const trimmed = text.trim();
  if (trimmed.startsWith("```") && trimmed.endsWith("```")) {
    const lines = trimmed.split(/\r?\n/);
    if (lines.length >= 3) {
      return lines.slice(1, -1).join("\n").trim();
    }
  }
  return trimmed;
}

async function init() {
  state.config = await fetchConfig();
  updateLoginHint();
  setupEventHandlers();
  initGoogleSignIn();
}

function updateLoginHint() {
  const hintEl = loginView.querySelector(".hint");
  if (!hintEl || !state.config) {
    return;
  }
  const allowed = state.config.allowed_emails || [];
  if (allowed.includes("*")) {
    hintEl.textContent = "Any Google account can sign in.";
  } else if (allowed.length) {
    hintEl.textContent = `Allowed account: ${allowed.join(", ")}`;
  }
  if (connectGmailBtn) {
    if (state.config?.oauth_connect_enabled) {
      connectGmailBtn.classList.remove("hidden");
    } else {
      connectGmailBtn.classList.add("hidden");
    }
  }
}

function setupEventHandlers() {
  if (runCleanupBtn) {
    runCleanupBtn.addEventListener("click", handleRunCleanup);
  }
  if (cancelCleanupBtn) {
    cancelCleanupBtn.addEventListener("click", handleCancelCleanup);
  }
  if (logoutBtn) {
    logoutBtn.addEventListener("click", handleLogout);
  }
  if (connectGmailBtn) {
    connectGmailBtn.addEventListener("click", () => startGmailConnect().catch((e) => setStatus(cleanupStatus, e.message, true)));
  }
  if (refreshCriteriaBtn) {
    refreshCriteriaBtn.addEventListener("click", () => loadCriteria().catch(console.error));
  }
  if (newCriterionForm) {
    newCriterionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = newCriterionText.value.trim();
      if (!text) {
        setStatus(criteriaStatus, "Please enter criterion text before submitting.", true);
        return;
      }
      try {
        await apiFetch("/api/criteria", {
          method: "POST",
          body: JSON.stringify({ text }),
        });
        newCriterionText.value = "";
        setStatus(criteriaStatus, "Criterion added.", false);
        await loadCriteria();
      } catch (error) {
        setStatus(criteriaStatus, error.message, true);
      }
    });
  }
  if (criteriaListEl) {
    criteriaListEl.addEventListener("click", handleCriteriaAction);
  }
  if (loadInboxBtn) loadInboxBtn.addEventListener("click", () => loadViewer("inbox"));
  if (loadRequiresBtn) loadRequiresBtn.addEventListener("click", () => loadViewer("requires_response"));
  if (loadShouldBtn) loadShouldBtn.addEventListener("click", () => loadViewer("should_read"));
  if (loadMoreBtn) loadMoreBtn.addEventListener("click", () => loadViewerNextPage());
}

function initGoogleSignIn() {
  if (!state.config?.google_client_id) {
    setStatus(cleanupStatus, "GOOGLE_OAUTH_CLIENT_ID is not configured on the server.", true);
    return;
  }
  if (!window.google || !window.google.accounts || !window.google.accounts.id) {
    setStatus(cleanupStatus, "Google Identity script failed to load.", true);
    return;
  }
  window.google.accounts.id.initialize({
    client_id: state.config.google_client_id,
    callback: async (response) => {
      await handleCredentialResponse(response);
    },
    auto_select: false,
  });
  const buttonContainer = document.getElementById("google-signin");
  if (buttonContainer) {
    window.google.accounts.id.renderButton(buttonContainer, {
      theme: "outline",
      size: "large",
      type: "standard",
    });
  }
}

async function handleCredentialResponse(response) {
  if (!response || !response.credential) {
    setStatus(cleanupStatus, "No credential returned from Google sign-in.", true);
    return;
  }
  try {
    state.token = response.credential;
    state.user = decodeJwt(response.credential);
    showMainView();
    setStatus(cleanupStatus, "Signed in. Ready to run cleanup.", false);
    // If the server has OAuth web client configured, try to connect Gmail
    // immediately so first‑time users get set up without hunting for a button.
    if (state.config?.oauth_connect_enabled) {
      try {
        await startGmailConnect();
      } catch (e) {
        // Popup may be blocked; leave the Connect button visible.
      }
    }
    await loadCriteria();
  } catch (error) {
    console.error("Failed to process credential", error);
    setStatus(cleanupStatus, `Authentication failed: ${error.message}`, true);
  }
}

function showMainView() {
  loginView.classList.add("hidden");
  appView.classList.remove("hidden");
  const email = state.user?.email || "";
  if (userEmailEl) {
    userEmailEl.textContent = email;
  }
  if (state.config?.oauth_connect_enabled && connectGmailBtn) {
    connectGmailBtn.classList.remove("hidden");
  }
}

function handleLogout() {
  state.token = null;
  state.user = null;
  state.summaries.clear();
  state.summaryPromises.clear();
  state.draftPromises.clear();
  cleanupSummary.classList.add("hidden");
  cleanupCounts.innerHTML = "";
  if (cleanupShortcuts) cleanupShortcuts.innerHTML = "";
  setStatus(cleanupStatus, "Signed out.", false);
  setStatus(criteriaStatus, "", false);
  appView.classList.add("hidden");
  loginView.classList.remove("hidden");
  if (connectGmailBtn) connectGmailBtn.classList.add("hidden");
  if (window.google?.accounts?.id) {
    window.google.accounts.id.disableAutoSelect();
  }
}

async function startGmailConnect() {
  const resp = await apiFetch(`/oauth/start`);
  const url = resp?.url;
  if (!url) throw new Error("Server did not provide auth URL.");
  const popup = window.open(url, "oauth", "width=520,height=650");
  if (!popup) throw new Error("Popup blocked. Allow popups and try again.");
  return new Promise((resolve) => {
    const handler = (event) => {
      try {
        const data = event?.data;
        if (data && data.status === "ok") {
          window.removeEventListener("message", handler);
          setStatus(cleanupStatus, "Gmail connected.", false);
          fetch("/gmail/watch", { method: "POST" }).catch(() => {});
          resolve();
        }
      } catch (_e) {}
    };
    window.addEventListener("message", handler);
  });
}

async function handleRunCleanup() {
  if (!state.token) {
    setStatus(cleanupStatus, "Sign in to run cleanup.", true);
    return;
  }
  const batchSize = Number.parseInt(batchSizeInput.value, 10) || 50;
  if (batchSize < 1 || batchSize > 500) {
    setStatus(cleanupStatus, "Batch size must be between 1 and 500.", true);
    return;
  }
  // Start streaming job
  if (cleanupLog) cleanupLog.innerHTML = "";
  cleanupSummary.classList.add("hidden");
  if (cleanupShortcuts) cleanupShortcuts.innerHTML = "";
  displayCounts({});
  setStatus(cleanupStatus, "Starting cleanup...", false);
  runCleanupBtn.disabled = true;
  cancelCleanupBtn.classList.remove("hidden");
  cancelCleanupBtn.disabled = false;
  try {
    const { job_id } = await apiFetch("/api/cleanup/start", {
      method: "POST",
      body: JSON.stringify({ batch_size: batchSize }),
    });
    state.currentJobId = job_id;
    streamCleanupEvents(job_id);
  } catch (error) {
    setStatus(cleanupStatus, error.message, true);
    runCleanupBtn.disabled = false;
    cancelCleanupBtn.classList.add("hidden");
  }
}

async function handleCancelCleanup() {
  if (!state.currentJobId) {
    return;
  }
  try {
    cancelCleanupBtn.disabled = true;
    await apiFetch("/api/cleanup/cancel", {
      method: "POST",
      body: JSON.stringify({ job_id: state.currentJobId }),
    });
    appendLog("Cancellation requested. Waiting for current step to finish...");
  } catch (error) {
    appendLog(`Failed to cancel: ${error.message}`);
    cancelCleanupBtn.disabled = false;
  }
}

function streamCleanupEvents(jobId) {
  const url = `/api/cleanup/events/${encodeURIComponent(jobId)}?token=${encodeURIComponent(state.token)}`;
  const es = new EventSource(url);
  const counts = {};
  appendLog(`Connected to job ${jobId}`);
  es.onmessage = (evt) => {
    if (!evt.data) return;
    try {
      const msg = JSON.parse(evt.data);
      handleCleanupEvent(msg, counts, es);
    } catch (_e) {
      // ignore malformed
    }
  };
  es.addEventListener("ping", () => {
    // keepalive
  });
  es.onerror = () => {
    // Connection broken; UI will reflect completion or error from last message.
    es.close();
  };
}

function handleCleanupEvent(event, counts, es) {
  switch (event.type) {
    case "ok": {
      // initial connect
      break;
    }
    case "job_started": {
      setStatus(cleanupStatus, `Processing up to ${event.batch_size} messages...`, false);
      appendLog(`Job started for ${event.email}`);
      break;
    }
    case "batch_started": {
      appendLog(`Batch ${event.batch_number} started`);
      break;
    }
    case "message": {
      if (event.status === "processed") {
        const cat = event.category || "unknown";
        counts[cat] = (counts[cat] || 0) + 1;
        displayCounts(counts);
        appendLog(`✔ ${event.subject || "(no subject)"} — ${cat}${event.label ? ` [${event.label}]` : ""}`);
      } else if (event.status === "error") {
        appendLog(`✖ Error on a message: ${event.error || "unknown"}`);
      }
      break;
    }
    case "batch_summary": {
      // Currently not emitted; reserved for future use
      break;
    }
    case "cancelled": {
      appendLog("Job cancelled by user.");
      break;
    }
    case "complete": {
      const result = event.result || {};
      displayCleanupResult(result);
      const processed = result.processed_messages ?? 0;
      const batches = result.batches_processed ?? 0;
      setStatus(cleanupStatus, `Processed ${processed} message(s) across ${batches} batch(es).`, false);
      appendLog("Job complete.");
      endCleanupSession(es);
      break;
    }
    case "error": {
      setStatus(cleanupStatus, event.error || "Unexpected error", true);
      appendLog(`Error: ${event.error || "Unexpected error"}`);
      endCleanupSession(es);
      break;
    }
    case "end": {
      // Stream end
      endCleanupSession(es);
      break;
    }
    default: {
      // ignore
    }
  }
}

function endCleanupSession(es) {
  try { es && es.close && es.close(); } catch (_e) {}
  runCleanupBtn.disabled = false;
  cancelCleanupBtn.classList.add("hidden");
  state.currentJobId = null;
}

function appendLog(line) {
  if (!cleanupLog) return;
  const el = document.createElement("div");
  el.className = "log-line";
  el.textContent = line;
  cleanupLog.appendChild(el);
  cleanupLog.scrollTop = cleanupLog.scrollHeight;
}

function displayCounts(counts) {
  // Update the counts box incrementally
  cleanupCounts.innerHTML = "";
  const entries = Object.entries(counts || {});
  if (!entries.length) return;
  for (const [key, value] of entries) {
    const item = document.createElement("div");
    item.className = "count-item";
    const label = CATEGORY_LABELS[key] || key;
    item.textContent = `${label}: ${value}`;
    cleanupCounts.appendChild(item);
  }
}

function displayCleanupResult(result) {
  cleanupSummary.classList.remove("hidden");
  renderCounts(result.counts || {});
  renderCleanupShortcuts(result);
  const requiresCount = (result.requires_response || []).length;
  const shouldReadCount = (result.should_read || []).length;
  if (requiresCount > 0) {
    setStatus(
      viewerStatus,
      `Cleanup produced ${requiresCount} Requires Response message${requiresCount === 1 ? "" : "s"}. Loading viewer…`,
      false,
    );
    loadViewer("requires_response").catch((error) => console.error("Failed to load requires_response view", error));
  } else if (shouldReadCount > 0) {
    setStatus(
      viewerStatus,
      `Cleanup produced ${shouldReadCount} Should Read message${shouldReadCount === 1 ? "" : "s"}. Loading viewer…`,
      false,
    );
    loadViewer("should_read").catch((error) => console.error("Failed to load should_read view", error));
  } else {
    setStatus(viewerStatus, "No follow-up items produced in this batch.", false);
  }
}

function renderCounts(counts) {
  cleanupCounts.innerHTML = "";
  const entries = Object.entries(counts);
  if (!entries.length) {
    cleanupCounts.innerHTML = "<p>No messages were processed.</p>";
    return;
  }
  for (const [key, value] of entries) {
    const item = document.createElement("div");
    item.className = "count-item";
    const label = CATEGORY_LABELS[key] || key;
    item.textContent = `${label}: ${value}`;
    cleanupCounts.appendChild(item);
  }
}

function renderCleanupShortcuts(result) {
  if (!cleanupShortcuts) return;
  cleanupShortcuts.innerHTML = "";
  const requiresCount = (result.requires_response || []).length;
  const shouldReadCount = (result.should_read || []).length;
  if (!requiresCount && !shouldReadCount) {
    const empty = document.createElement("p");
    empty.className = "message-empty";
    empty.textContent = "No follow-up items generated in this batch.";
    cleanupShortcuts.appendChild(empty);
    return;
  }
  const summaryLine = document.createElement("p");
  summaryLine.className = "cleanup-summary-text";
  const parts = [];
  if (requiresCount) parts.push(`${requiresCount} Requires Response`);
  if (shouldReadCount) parts.push(`${shouldReadCount} Should Read`);
  const totalFollowUps = requiresCount + shouldReadCount;
  summaryLine.textContent = `Review ${parts.join(" and ")} message${totalFollowUps === 1 ? "" : "s"} in the viewer.`;
  cleanupShortcuts.appendChild(summaryLine);

  const buttonRow = document.createElement("div");
  buttonRow.className = "shortcut-buttons";
  if (requiresCount) {
    const btn = document.createElement("button");
    btn.className = "secondary";
    btn.textContent = `Open Requires Response (${requiresCount})`;
    btn.addEventListener("click", () => {
      loadViewer("requires_response").catch((error) => console.error("Failed to load requires_response view", error));
    });
    buttonRow.appendChild(btn);
  }
  if (shouldReadCount) {
    const btn = document.createElement("button");
    btn.className = "secondary";
    btn.textContent = `Open Should Read (${shouldReadCount})`;
    btn.addEventListener("click", () => {
      loadViewer("should_read").catch((error) => console.error("Failed to load should_read view", error));
    });
    buttonRow.appendChild(btn);
  }
  cleanupShortcuts.appendChild(buttonRow);
}

function buildActionOptions() {
  const entries = [
    ["useful_archive", CATEGORY_LABELS.useful_archive],
    ["requires_response", CATEGORY_LABELS.requires_response],
    ["should_read", CATEGORY_LABELS.should_read],
    ["receipt", CATEGORY_LABELS.receipt],
    ["spam", CATEGORY_LABELS.spam],
  ];
  return entries
    .map(
      ([value, label]) =>
        `<option value="${value}">${escapeHtml(label)}</option>`,
    )
    .join("");
}

async function loadCriteria() {
  if (!state.token) {
    return;
  }
  try {
    const data = await apiFetch("/api/criteria");
    state.criteria = data.items || [];
    renderCriteria();
    setStatus(criteriaStatus, `Loaded ${state.criteria.length} criterion${state.criteria.length === 1 ? "" : "s"}.`, false);
  } catch (error) {
    setStatus(criteriaStatus, error.message, true);
  }
}

function renderCriteria() {
  criteriaListEl.innerHTML = "";
  if (!state.criteria.length) {
    criteriaListEl.innerHTML = "<p>No criteria yet.</p>";
    return;
  }
  state.criteria.forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = `criterion-item${item.enabled ? "" : " disabled"}`;
    wrapper.dataset.id = item.id;
    wrapper.dataset.enabled = item.enabled ? "1" : "0";
    wrapper.innerHTML = `
      <textarea class="criterion-text" rows="3">${escapeHtml(item.text)}</textarea>
      <div class="criterion-meta">
        <span>Created: ${formatTimestamp(item.created_at)}</span>
        <span>Updated: ${formatTimestamp(item.updated_at)}</span>
        <span>Status: ${item.enabled ? "Enabled" : "Disabled"}</span>
      </div>
      <div class="criterion-actions">
        <button class="save">Save</button>
        <button class="toggle">${item.enabled ? "Disable" : "Enable"}</button>
        <button class="delete secondary">Delete</button>
      </div>
    `;
    criteriaListEl.appendChild(wrapper);
  });
}

async function handleCriteriaAction(event) {
  const target = event.target;
  const itemEl = target.closest(".criterion-item");
  if (!itemEl) {
    return;
  }
  const id = itemEl.dataset.id;
  if (!id) {
    return;
  }
  if (target.classList.contains("save")) {
    const text = itemEl.querySelector(".criterion-text").value.trim();
    if (!text) {
      setStatus(criteriaStatus, "Criterion text cannot be empty.", true);
      return;
    }
    try {
      await apiFetch(`/api/criteria/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ text }),
      });
      setStatus(criteriaStatus, "Criterion updated.", false);
      await loadCriteria();
    } catch (error) {
      setStatus(criteriaStatus, error.message, true);
    }
  } else if (target.classList.contains("toggle")) {
    const enabled = itemEl.dataset.enabled === "1";
    try {
      await apiFetch(`/api/criteria/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !enabled }),
      });
      setStatus(criteriaStatus, `Criterion ${enabled ? "disabled" : "enabled"}.`, false);
      await loadCriteria();
    } catch (error) {
      setStatus(criteriaStatus, error.message, true);
    }
  } else if (target.classList.contains("delete")) {
    const confirmed = window.confirm("Delete this criterion? This cannot be undone.");
    if (!confirmed) {
      return;
    }
    try {
      await apiFetch(`/api/criteria/${id}`, { method: "DELETE" });
      setStatus(criteriaStatus, "Criterion deleted.", false);
      await loadCriteria();
    } catch (error) {
      setStatus(criteriaStatus, error.message, true);
    }
  }
}

async function fetchConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) {
    throw new Error(`Failed to fetch configuration (${response.status})`);
  }
  return response.json();
}

function decodeJwt(token) {
  const parts = token.split(".");
  if (parts.length !== 3) {
    throw new Error("Invalid ID token.");
  }
  const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
  const decoded = atob(payload);
  const json = decodeURIComponent(
    decoded
      .split("")
      .map((c) => `%${`00${c.charCodeAt(0).toString(16)}`.slice(-2)}`)
      .join(""),
  );
  return JSON.parse(json);
}

async function apiFetch(path, options = {}) {
  if (!state.token) {
    throw new Error("Authentication required.");
  }
  const headers = {
    Authorization: `Bearer ${state.token}`,
    Accept: "application/json",
    ...options.headers,
  };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {
    ...options,
    headers,
  });
  if (response.status === 204) {
    return {};
  }
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_e) {
    data = { message: text };
  }
  if (!response.ok) {
    const detail = data?.detail ?? data?.message ?? data?.error ?? response.statusText;
    throw new Error(formatErrorDetail(detail));
  }
  return data;
}

function formatErrorDetail(detail) {
  if (detail == null) return "Unexpected error";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const msg = item.msg || item.message || JSON.stringify(item);
          const loc = item.loc ? ` (${[].concat(item.loc).join(".")})` : "";
          return `${msg}${loc}`;
        }
        return String(item);
      })
      .join("; ");
  }
  if (typeof detail === "object") {
    if (detail.msg || detail.message) return detail.msg || detail.message;
    try {
      return JSON.stringify(detail);
    } catch (_e) {
      return String(detail);
    }
  }
  return String(detail);
}

function setStatus(element, message, isError) {
  if (!element) {
    return;
  }
  element.textContent = message || "";
  element.classList.remove("error", "success");
  if (!message) {
    return;
  }
  element.classList.add(isError ? "error" : "success");
}

function formatTimestamp(value) {
  if (!value) {
    return "n/a";
  }
  try {
    return new Date(value).toLocaleString();
  } catch (_error) {
    return value;
  }
}

// -----------------------------
// Email Viewer
// -----------------------------

async function loadViewer(label) {
  if (!state.token) {
    setStatus(viewerStatus, "Sign in first.", true);
    return;
  }
  resetViewer(label);
  await loadViewerNextPage();
}

function resetViewer(label) {
  state.viewer.label = label;
  state.viewer.nextPageToken = null;
  state.viewer.loading = false;
  state.viewer.loadedCount = 0;
  viewerList.innerHTML = "";
  if (loadMoreBtn) {
    loadMoreBtn.classList.add("hidden");
    loadMoreBtn.disabled = false;
  }
}

async function loadViewerNextPage() {
  if (!state.viewer.label || state.viewer.loading) return;
  try {
    state.viewer.loading = true;
    const labelText = state.viewer.label.replace("_", " ");
    setStatus(viewerStatus, `Loading ${labelText}…`, false);
    const params = new URLSearchParams({
      label: state.viewer.label,
      max_results: String(state.viewer.pageSize),
    });
    if (state.viewer.nextPageToken) params.set("page_token", state.viewer.nextPageToken);
    const data = await apiFetch(`/api/messages?${params.toString()}`);
    const items = data.items || [];
    if (!items.length && state.viewer.loadedCount === 0) {
      const empty = document.createElement("p");
      empty.textContent = "No messages found.";
      empty.className = "message-empty";
      viewerList.appendChild(empty);
    } else {
      items.forEach((item) => viewerList.appendChild(buildViewerCard(item)));
      state.viewer.loadedCount += items.length;
    }
    // Update next page token and button visibility
    state.viewer.nextPageToken = data.next_page_token || null;
    if (loadMoreBtn) {
      if (state.viewer.nextPageToken) {
        loadMoreBtn.classList.remove("hidden");
        loadMoreBtn.disabled = false;
      } else {
        loadMoreBtn.classList.add("hidden");
      }
    }
    const more = state.viewer.nextPageToken ? " (more available)" : "";
    setStatus(viewerStatus, `Loaded ${state.viewer.loadedCount} message(s)${more}.`, false);
  } catch (error) {
    setStatus(viewerStatus, error.message, true);
    if (loadMoreBtn) loadMoreBtn.disabled = false;
  } finally {
    state.viewer.loading = false;
  }
}

async function fetchMessageSummary(gmailId) {
  if (!gmailId) return "";
  if (state.summaries.has(gmailId)) {
    return state.summaries.get(gmailId) || "";
  }
  if (state.summaryPromises.has(gmailId)) {
    return state.summaryPromises.get(gmailId);
  }
  const promise = (async () => {
    try {
      const response = await apiFetch(`/api/messages/${encodeURIComponent(gmailId)}/summary`);
      const summary = stripCodeFences(response.summary || "").trim();
      if (summary) {
        state.summaries.set(gmailId, summary);
      }
      return summary;
    } finally {
      state.summaryPromises.delete(gmailId);
    }
  })();
  state.summaryPromises.set(gmailId, promise);
  return promise;
}

async function fetchDraftReply(gmailId) {
  if (!gmailId) return "";
  if (state.draftPromises.has(gmailId)) {
    return state.draftPromises.get(gmailId);
  }
  const promise = (async () => {
    try {
      const response = await apiFetch(`/api/messages/${encodeURIComponent(gmailId)}/respond`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      return stripCodeFences(response.draft || "").trim();
    } finally {
      state.draftPromises.delete(gmailId);
    }
  })();
  state.draftPromises.set(gmailId, promise);
  return promise;
}

function buildViewerCard(item) {
  const card = document.createElement("div");
  card.className = "message-card";
  card.dataset.gmailId = item.gmail_id;
  // Preserve the list-time snippet so we can fall back to it
  // when the GET /api/messages/{id} response lacks a snippet
  // (which happens for metadata-scope-only tokens).
  card.dataset.snippet = item.snippet || "";
  card.innerHTML = `
    <h4>${escapeHtml(item.subject || "(no subject)")}</h4>
    <p class="message-meta">From: ${escapeHtml(item.from || "")} • ${escapeHtml(item.date || "")}</p>
    <p class="message-summary">
      <span class="summary-label">Summary:</span>
      <span class="summary-text">${escapeHtml(item.summary || "Generating summary…")}</span>
    </p>
    <p class="message-snippet">${escapeHtml(item.snippet || "")}</p>
    <div class="actions-row">
      <button class="view-btn secondary">View</button>
      <button class="respond-btn">Draft reply</button>
      <button class="reply-btn secondary">Reply</button>
      <button class="archive-btn secondary">Archive</button>
      <button class="delete-btn danger">Delete</button>
    </div>
    <div class="message-actions">
      <label>
        Desired action
        <select class="action-select">
          ${buildActionOptions()}
        </select>
      </label>
      <label class="label-input">
        Label name
        <input type="text" class="label-value" value="Filed" />
      </label>
      <label>
        Comment to add to prompt
        <textarea class="comment-input" rows="2" placeholder="Why should this be treated differently?"></textarea>
      </label>
    </div>
    <div class="actions-row">
      <button class="apply-feedback">Apply feedback</button>
    </div>
    <div class="feedback-status"></div>
    <div class="viewer-body hidden"></div>
    <div class="reply-box hidden">
      <label>
        Your reply
        <textarea class="reply-text" rows="4" placeholder="Type your response..."></textarea>
      </label>
      <div class="actions-row">
        <button class="send-reply">Send</button>
        <button class="cancel-reply secondary">Cancel</button>
      </div>
      <div class="reply-status status"></div>
    </div>
  `;
  const viewBtn = card.querySelector(".view-btn");
  const respondBtn = card.querySelector(".respond-btn");
  const replyBtn = card.querySelector(".reply-btn");
  const archiveBtn = card.querySelector(".archive-btn");
  const deleteBtn = card.querySelector(".delete-btn");
  const bodyEl = card.querySelector(".viewer-body");
  const replyBox = card.querySelector(".reply-box");
  const sendReplyBtn = card.querySelector(".send-reply");
  const cancelReplyBtn = card.querySelector(".cancel-reply");
  const replyText = card.querySelector(".reply-text");
  const replyStatus = card.querySelector(".reply-status");
  const actionSelect = card.querySelector(".action-select");
  const labelWrapper = card.querySelector(".label-input");
  const labelInput = card.querySelector(".label-value");
  const applyButton = card.querySelector(".apply-feedback");
  const feedbackStatus = card.querySelector(".feedback-status");
  const summaryRow = card.querySelector(".message-summary");
  const summaryText = card.querySelector(".summary-text");

  if (item.summary) {
    state.summaries.set(card.dataset.gmailId, item.summary);
    summaryText.textContent = item.summary;
    summaryRow.classList.remove("loading");
    summaryRow.classList.remove("error");
  } else {
    summaryRow.classList.add("loading");
    summaryRow.classList.remove("error");
    if (item.summary_error) {
      summaryRow.classList.add("error");
      summaryText.textContent = item.summary_error;
    } else {
      summaryText.textContent = "Generating summary…";
    }
    fetchMessageSummary(card.dataset.gmailId)
      .then((summary) => {
        summaryText.textContent = summary || "No summary available.";
        summaryRow.classList.remove("loading");
        summaryRow.classList.remove("error");
      })
      .catch((error) => {
        const message = error?.message || "Failed to summarise.";
        summaryText.textContent = message;
        summaryRow.classList.remove("loading");
        summaryRow.classList.add("error");
      });
  }

  let loaded = false;
  viewBtn.addEventListener("click", async () => {
    try {
      if (!loaded) {
        bodyEl.innerHTML = "Loading...";
        bodyEl.classList.remove("hidden");
        const data = await apiFetch(`/api/messages/${encodeURIComponent(card.dataset.gmailId)}`);
        const content = document.createElement("div");
        content.className = "viewer-content";
        if (data.permission_warning) {
          const warning = document.createElement("div");
          warning.className = "viewer-warning";
          warning.textContent = data.permission_warning;
          content.appendChild(warning);
        }
        const hasHtml = Boolean(data.body_html && data.body_html.trim());
        const hasText = Boolean(data.body_text && data.body_text.trim());
        if (hasHtml) {
          const htmlContainer = document.createElement("div");
          htmlContainer.className = "viewer-html";
          try {
            htmlContainer.appendChild(sanitizeAndCloneHtml(data.body_html));
          } catch (err) {
            const fallback = document.createElement("pre");
            fallback.className = "viewer-text";
            fallback.textContent = stripCodeFences(data.body_text || data.body_html || "");
            htmlContainer.appendChild(fallback);
          }
          content.appendChild(htmlContainer);
        }
        if (hasText) {
          const textBlock = document.createElement("pre");
          textBlock.className = "viewer-text";
          textBlock.textContent = stripCodeFences(data.body_text);
          content.appendChild(textBlock);
        }
        if (!hasHtml && !hasText) {
          const fallback = document.createElement("p");
          fallback.className = "viewer-empty";
          // For metadata-only tokens Gmail omits snippet on the get() call.
          // Fall back to the snippet we fetched during list() so users still
          // see something useful when pressing View.
          fallback.textContent = data.snippet || card.dataset.snippet || "(no text body)";
          content.appendChild(fallback);
        }
        bodyEl.innerHTML = "";
        bodyEl.appendChild(content);
        loaded = true;
      } else {
        bodyEl.classList.toggle("hidden");
      }
    } catch (error) {
      bodyEl.textContent = error.message;
      bodyEl.classList.remove("hidden");
    }
  });

  respondBtn.addEventListener("click", async () => {
    replyBox.classList.remove("hidden");
    replyText.focus();
    setStatus(replyStatus, "Drafting reply...", false);
    try {
      respondBtn.disabled = true;
      const draft = await fetchDraftReply(card.dataset.gmailId);
      if (!draft) {
        setStatus(replyStatus, "Draft generator returned no content.", true);
      } else {
        replyText.value = draft;
        setStatus(replyStatus, "Draft generated. Review before sending.", false);
      }
    } catch (error) {
      setStatus(replyStatus, error?.message || "Failed to draft reply.", true);
    } finally {
      respondBtn.disabled = false;
    }
  });

  replyBtn.addEventListener("click", () => {
    replyBox.classList.remove("hidden");
    replyText.focus();
    replyStatus.textContent = "";
    replyStatus.classList.remove("error", "success");
  });
  cancelReplyBtn.addEventListener("click", () => {
    replyBox.classList.add("hidden");
    replyStatus.textContent = "";
    replyStatus.classList.remove("error", "success");
    replyText.value = "";
  });
  sendReplyBtn.addEventListener("click", async () => {
    const text = replyText.value.trim();
    if (!text) {
      setStatus(replyStatus, "Please type a reply.", true);
      return;
    }
    try {
      sendReplyBtn.disabled = true;
      setStatus(replyStatus, "Sending reply...", false);
      await apiFetch(`/api/messages/${encodeURIComponent(card.dataset.gmailId)}/reply`, {
        method: "POST",
        body: JSON.stringify({ body_text: text }),
      });
      setStatus(replyStatus, "Reply sent.", false);
      setTimeout(() => {
        replyBox.classList.add("hidden");
        sendReplyBtn.disabled = false;
        replyStatus.textContent = "";
        replyText.value = "";
      }, 1200);
    } catch (error) {
      sendReplyBtn.disabled = false;
      setStatus(replyStatus, error.message, true);
    }
  });

  archiveBtn.addEventListener("click", async () => {
    try {
      archiveBtn.disabled = true;
      await apiFetch(`/api/messages/${encodeURIComponent(card.dataset.gmailId)}/archive`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      card.remove();
    } catch (error) {
      archiveBtn.disabled = false;
      setStatus(viewerStatus, error.message, true);
    }
  });
  deleteBtn.addEventListener("click", async () => {
    try {
      deleteBtn.disabled = true;
      await apiFetch(`/api/messages/${encodeURIComponent(card.dataset.gmailId)}/delete`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      card.remove();
      state.summaries.delete(card.dataset.gmailId);
      state.summaryPromises.delete(card.dataset.gmailId);
      state.draftPromises.delete(card.dataset.gmailId);
    } catch (error) {
      deleteBtn.disabled = false;
      setStatus(viewerStatus, error.message, true);
    }
  });

  actionSelect.addEventListener("change", () => {
    if (ACTIONS_REQUIRING_LABEL.has(actionSelect.value)) {
      labelWrapper.classList.add("visible");
    } else {
      labelWrapper.classList.remove("visible");
    }
  });
  actionSelect.dispatchEvent(new Event("change"));
  applyButton.addEventListener("click", async () => {
    try {
      applyButton.disabled = true;
      feedbackStatus.textContent = "Submitting feedback...";
      feedbackStatus.classList.remove("error");
      const payload = {
        gmail_id: card.dataset.gmailId,
        desired_category: actionSelect.value,
        label: ACTIONS_REQUIRING_LABEL.has(actionSelect.value) ? labelInput.value.trim() || "Filed" : null,
        comment: card.querySelector(".comment-input").value.trim(),
      };
      await apiFetch("/api/cleanup/feedback", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      feedbackStatus.textContent = "Feedback applied and prompt updated.";
      labelWrapper.classList.remove("visible");
      setTimeout(() => {
        feedbackStatus.textContent = "";
        applyButton.disabled = false;
      }, 1200);
      await loadCriteria();
    } catch (error) {
      feedbackStatus.textContent = error.message;
      feedbackStatus.classList.add("error");
      applyButton.disabled = false;
    }
  });

  return card;
}
