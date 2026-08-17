const INTENT_LABEL = {
  general: "🧠 General AI",
  personal: "📚 Personal Knowledge",
  combined: "🔀 General + Personal",
  web: "🌐 Web (not implemented yet)",
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

// ---------- Tabs ----------

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("is-active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("is-active"));
    btn.classList.add("is-active");
    document.getElementById(`${btn.dataset.tab}-view`).classList.add("is-active");
  });
});

// ---------- Chat ----------

const messagesEl = document.getElementById("messages");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

function renderUserMessage(text) {
  const msg = el("div", "msg user");
  msg.appendChild(el("div", "bubble", text));
  messagesEl.appendChild(msg);
}

function renderAssistantMessage({ answer, intent, sources }, questionForTitle) {
  const msg = el("div", "msg assistant");

  const badge = el("span", `intent-badge intent-${intent}`, INTENT_LABEL[intent] || intent);
  msg.appendChild(badge);

  msg.appendChild(el("div", "bubble", answer));

  if (sources && sources.length) {
    const box = el("div", "sources");
    box.appendChild(el("div", "sources-label", "Sources"));
    for (const s of sources) {
      const line = el("div", "source-item");
      const label = s.heading_path ? `${s.title || s.source_path} — ${s.heading_path}` : (s.title || s.source_path);
      line.innerHTML = `📄 <span>${escapeHtml(label)}</span> · score ${s.score}`;
      box.appendChild(line);
    }
    msg.appendChild(box);
  }

  const actions = el("div", "msg-actions");
  const saveBtn = el("button", "save-note-btn", "💾 Save as note");
  saveBtn.type = "button";
  saveBtn.addEventListener("click", () => saveAsNote(answer, questionForTitle));
  actions.appendChild(saveBtn);
  msg.appendChild(actions);

  messagesEl.appendChild(msg);
}

// Typing a save phrase saves the most recent answer - resolved client-side,
// where the message history already lives, rather than teaching the backend
// to track conversation state just for this. Matched as a substring (unlike
// the greeting check in backend/rag/router.py) since these phrases are
// meant to be typed as their own full instruction, not to appear
// incidentally inside an unrelated real question.
const SAVE_TRIGGERS = [
  "save this as a note", "save this as notes", "save as a note", "save as notes",
  "upload this as a note", "upload this as notes", "add this to my vault",
  "note this down", "save that as a note", "save this to obsidian", "save to my vault",
];

function isSaveTrigger(text) {
  const t = text.toLowerCase().trim();
  return SAVE_TRIGGERS.some((p) => t.includes(p));
}

let lastAssistantAnswer = null;
let lastUserQuestion = null;

async function saveAsNote(content, suggestedTitle) {
  const title = window.prompt("Save as note titled:", suggestedTitle || "Untitled");
  if (!title) return;

  const msg = el("div", "msg assistant");
  const bubble = el("div", "bubble", "Saving to your vault…");
  msg.appendChild(bubble);
  messagesEl.appendChild(msg);
  scrollToBottom();

  try {
    const result = await api("/notes/create", {
      method: "POST",
      body: JSON.stringify({ title, content }),
    });
    const relatedText = result.related.length
      ? ` Linked to ${result.related.length} related note${result.related.length > 1 ? "s" : ""}: ${result.related
          .map((r) => `[[${r.title}]]`)
          .join(", ")}.`
      : " No closely related notes found to link.";
    bubble.textContent = `✅ Saved as "${title}" in your vault.${relatedText}`;
    msg.classList.add("note-saved");
  } catch (err) {
    bubble.textContent = `Couldn't save note: ${err.message}`;
    msg.classList.add("error");
  }
  scrollToBottom();
}

function renderTypingIndicator() {
  const msg = el("div", "msg assistant");
  const bubble = el("div", "bubble");
  const dots = el("div", "typing-dots");
  dots.appendChild(el("span"));
  dots.appendChild(el("span"));
  dots.appendChild(el("span"));
  bubble.appendChild(dots);
  msg.appendChild(bubble);
  return msg;
}

function renderErrorMessage(text) {
  const msg = el("div", "msg assistant error");
  msg.appendChild(el("div", "bubble", text));
  messagesEl.appendChild(msg);
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = chatInput.value.trim();
  if (!question) return;

  document.querySelector(".empty-state")?.remove();
  renderUserMessage(question);
  chatInput.value = "";
  chatInput.disabled = true;
  scrollToBottom();

  if (isSaveTrigger(question)) {
    if (!lastAssistantAnswer) {
      renderErrorMessage('Nothing to save yet — ask something first, then say "save this as a note".');
    } else {
      await saveAsNote(lastAssistantAnswer, lastUserQuestion);
    }
    chatInput.disabled = false;
    chatInput.focus();
    scrollToBottom();
    return;
  }

  const typing = renderTypingIndicator();
  messagesEl.appendChild(typing);
  scrollToBottom();

  try {
    const result = await api("/chat", { method: "POST", body: JSON.stringify({ question }) });
    typing.remove();
    renderAssistantMessage(result, question);
    lastAssistantAnswer = result.answer;
    lastUserQuestion = question;
  } catch (err) {
    typing.remove();
    renderErrorMessage(`Something went wrong: ${err.message}`);
  } finally {
    chatInput.disabled = false;
    chatInput.focus();
    scrollToBottom();
  }
});

// ---------- Search ----------

const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchResultsEl = document.getElementById("search-results");

searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;

  searchResultsEl.textContent = "Searching…";
  try {
    const { results } = await api("/knowledge/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    searchResultsEl.innerHTML = "";
    if (!results.length) {
      searchResultsEl.textContent = "No results.";
      return;
    }
    for (const r of results) {
      const item = el("div", "result-item");
      const meta = el("div", "meta");
      meta.innerHTML = `<span>${escapeHtml(r.document_title || r.source_path)}${r.heading_path ? " — " + escapeHtml(r.heading_path) : ""}</span><span class="score">${r.score}</span>`;
      item.appendChild(meta);
      item.appendChild(el("div", null, r.content.slice(0, 220) + (r.content.length > 220 ? "…" : "")));
      searchResultsEl.appendChild(item);
    }
  } catch (err) {
    searchResultsEl.textContent = `Search failed: ${err.message}`;
  }
});

// ---------- Vault sync ----------

const vaultPathEl = document.getElementById("vault-path");
const syncBtn = document.getElementById("sync-vault-btn");
const syncStatusEl = document.getElementById("sync-status");
let obsidianVaultPath = null;

async function loadConfig() {
  try {
    const config = await api("/config");
    obsidianVaultPath = config.obsidian_vault_path;
    vaultPathEl.textContent = obsidianVaultPath
      ? `Configured vault: ${obsidianVaultPath}`
      : "No OBSIDIAN_VAULT_PATH configured in .env.";
    syncBtn.disabled = !obsidianVaultPath;
  } catch (err) {
    vaultPathEl.textContent = `Couldn't load config: ${err.message}`;
  }
}

syncBtn.addEventListener("click", async () => {
  if (!obsidianVaultPath) return;
  syncBtn.disabled = true;
  syncStatusEl.className = "status";
  syncStatusEl.textContent = "Syncing…";
  try {
    const result = await api("/documents/index", {
      method: "POST",
      body: JSON.stringify({ path: obsidianVaultPath, source_type: "obsidian" }),
    });
    const created = result.results.filter((r) => r.status === "created").length;
    const updated = result.results.filter((r) => r.status === "updated").length;
    const unchanged = result.results.filter((r) => r.status === "unchanged").length;
    syncStatusEl.className = "status ok";
    syncStatusEl.textContent =
      `${created} created, ${updated} updated, ${unchanged} unchanged, ${result.deleted.length} deleted.`;
  } catch (err) {
    syncStatusEl.className = "status error";
    syncStatusEl.textContent = `Sync failed: ${err.message}`;
  } finally {
    syncBtn.disabled = false;
  }
});

// ---------- Upload ----------

const uploadForm = document.getElementById("upload-form");
const uploadFileInput = document.getElementById("upload-file");
const uploadStatusEl = document.getElementById("upload-status");

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = uploadFileInput.files[0];
  if (!file) return;

  uploadStatusEl.className = "status";
  uploadStatusEl.textContent = "Uploading…";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/documents/upload", { method: "POST", body: formData });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Upload failed (${res.status})`);
    }
    const r = await res.json();
    uploadStatusEl.className = "status ok";
    if (r.saved_as_note) {
      const relatedText = r.related.length
        ? ` Linked to ${r.related.length} related note${r.related.length > 1 ? "s" : ""}: ${r.related
            .map((x) => `[[${x.title}]]`)
            .join(", ")}.`
        : " No closely related notes found to link.";
      uploadStatusEl.textContent = `Saved as an Obsidian note (${r.chunk_count} chunks).${relatedText}`;
    } else {
      uploadStatusEl.textContent = `${r.status}: ${r.source_path} (${r.chunk_count} chunks)`;
    }
    uploadForm.reset();
  } catch (err) {
    uploadStatusEl.className = "status error";
    uploadStatusEl.textContent = `Upload failed: ${err.message}`;
  }
});

loadConfig();
