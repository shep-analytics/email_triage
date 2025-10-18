const state = {
  token: null,
  user: null,
  config: null,
  criteria: [],
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
const requiresResponseList = document.getElementById("requires-response-list");
const shouldReadList = document.getElementById("should-read-list");
const batchSizeInput = document.getElementById("batch-size");
const runCleanupBtn = document.getElementById("run-cleanup");
const logoutBtn = document.getElementById("logout-btn");
const newCriterionForm = document.getElementById("new-criterion-form");
const newCriterionText = document.getElementById("new-criterion-text");
const criteriaListEl = document.getElementById("criteria-list");
const refreshCriteriaBtn = document.getElementById("refresh-criteria");
const criteriaStatus = document.getElementById("criteria-status");

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
  if (allowed.length) {
    hintEl.textContent = `Allowed account: ${allowed.join(", ")}`;
  }
}

function setupEventHandlers() {
  if (runCleanupBtn) {
    runCleanupBtn.addEventListener("click", handleRunCleanup);
  }
  if (logoutBtn) {
    logoutBtn.addEventListener("click", handleLogout);
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
}

function handleLogout() {
  state.token = null;
  state.user = null;
  cleanupSummary.classList.add("hidden");
  cleanupCounts.innerHTML = "";
  requiresResponseList.innerHTML = "";
  shouldReadList.innerHTML = "";
  setStatus(cleanupStatus, "Signed out.", false);
  setStatus(criteriaStatus, "", false);
  appView.classList.add("hidden");
  loginView.classList.remove("hidden");
  if (window.google?.accounts?.id) {
    window.google.accounts.id.disableAutoSelect();
  }
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
  setStatus(cleanupStatus, "Processing inbox batch...", false);
  runCleanupBtn.disabled = true;
  try {
    const result = await apiFetch("/api/cleanup/run", {
      method: "POST",
      body: JSON.stringify({ batch_size: batchSize }),
    });
    displayCleanupResult(result);
    const processed = result.processed_messages ?? 0;
    const batches = result.batches_processed ?? 0;
    setStatus(cleanupStatus, `Processed ${processed} message(s) across ${batches} batch(es).`, false);
  } catch (error) {
    setStatus(cleanupStatus, error.message, true);
  } finally {
    runCleanupBtn.disabled = false;
  }
}

function displayCleanupResult(result) {
  cleanupSummary.classList.remove("hidden");
  renderCounts(result.counts || {});
  renderMessageList(requiresResponseList, result.requires_response || []);
  renderMessageList(shouldReadList, result.should_read || []);
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

function renderMessageList(container, items) {
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("p");
    empty.textContent = "Nothing in this category.";
    empty.className = "message-empty";
    container.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    container.appendChild(buildMessageCard(item));
  });
}

function buildMessageCard(item) {
  const card = document.createElement("div");
  card.className = "message-card";
  card.dataset.gmailId = item.gmail_id;
  card.dataset.subject = item.subject || "";
  card.dataset.from = item.from || "";
  const subject = escapeHtml(item.subject || "(no subject)");
  const sender = escapeHtml(item.from || "");
  const summary = escapeHtml(item.summary || "");
  const reason = escapeHtml(item.reason || "");
  card.innerHTML = `
    <h4>${subject}</h4>
    <p class="message-meta">From: ${sender}</p>
    <p class="message-summary">${summary}</p>
    <p class="message-reason">${reason}</p>
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
  `;
  const actionSelect = card.querySelector(".action-select");
  const labelWrapper = card.querySelector(".label-input");
  const labelInput = card.querySelector(".label-value");
  const applyButton = card.querySelector(".apply-feedback");
  const statusEl = card.querySelector(".feedback-status");
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
      statusEl.textContent = "Submitting feedback...";
      statusEl.classList.remove("error");
      const payload = {
        gmail_id: card.dataset.gmailId,
        desired_category: actionSelect.value,
        label: ACTIONS_REQUIRING_LABEL.has(actionSelect.value) ? labelInput.value.trim() || "Filed" : null,
        comment: card.querySelector(".comment-input").value.trim(),
      };
      const response = await apiFetch("/api/cleanup/feedback", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      statusEl.textContent = "Feedback applied and prompt updated.";
      labelWrapper.classList.remove("visible");
      setTimeout(() => {
        statusEl.textContent = "";
      }, 4000);
      await loadCriteria();
    } catch (error) {
      statusEl.textContent = error.message;
      statusEl.classList.add("error");
      applyButton.disabled = false;
    }
  });
  return card;
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
