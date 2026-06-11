// [desc] Page session: polling incrémental des blocs HTML, réponse aux questions, kill, onglet diffs. [/desc]
"use strict";

let nextIndex = 0;
let lastState = "";
let diffsLoaded = false;
const isAgent = SESSION_KEY.startsWith("agent/");
const agentId = isAgent ? SESSION_KEY.split("/")[1] : "";

const conv = document.getElementById("conv");
const badge = document.getElementById("s-badge");

function pinnedToBottom() {
  return window.innerHeight + window.scrollY >= document.body.scrollHeight - 120;
}

function setStatus(status) {
  lastState = status.state;
  badge.textContent = status.state;
  badge.className = `badge st-${status.state}`;
  document.getElementById("kill-btn").hidden = !(isAgent && status.state === "running");
  document.getElementById("composer").hidden = !(isAgent && status.state !== "running");
  const panel = document.getElementById("question-panel");
  const awaiting = status.state === "awaiting_input" && status.question;
  panel.hidden = !awaiting;
  if (awaiting) {
    document.getElementById("question-text").textContent = status.question;
    const options = document.getElementById("question-options");
    options.replaceChildren();
    (status.options || []).forEach((option) => {
      const button = document.createElement("button");
      button.className = "option";
      button.textContent = option.label || String(option);
      button.addEventListener("click", () => sendText(button.textContent));
      options.appendChild(button);
    });
  }
}

function setMeta(meta) {
  if (!meta || !meta.first_message) return;
  document.getElementById("s-title").textContent = meta.first_message.slice(0, 160);
  const tokens = `${Math.round((meta.input_tokens || 0) / 1000)}k in / ${Math.round((meta.output_tokens || 0) / 1000)}k out`;
  document.getElementById("s-meta").textContent =
    [meta.model, `${meta.turn_count} tours`, tokens, meta.saved_at].filter(Boolean).join(" · ");
  document.getElementById("diff-count").textContent = meta.files_edited ? `(${meta.files_edited})` : "";
}

async function poll() {
  const response = await fetch(`/api/sessions/${SESSION_KEY}/blocks?after=${nextIndex}`);
  if (response.ok) {
    const data = await response.json();
    const pinned = pinnedToBottom();
    data.blocks.forEach((block) => conv.insertAdjacentHTML("beforeend", block.html));
    if (data.blocks.length) {
      nextIndex = data.total;
      if (pinned) window.scrollTo(0, document.body.scrollHeight);
    }
    setMeta(data.meta);
    setStatus(data.status || { state: "cli" });
  }
  const active = lastState === "running" || lastState === "awaiting_input";
  setTimeout(poll, active ? 1500 : 5000);
}

async function sendText(text) {
  if (!text.trim() || !isAgent) return;
  const response = await fetch(`/api/agents/${agentId}/continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const data = await response.json();
  if (data.error) { badge.textContent = data.error; return; }
  document.getElementById("composer-text").value = "";
  document.getElementById("question-panel").hidden = true;
}

function mountMonacoDiff(monaco, body, file) {
  const lineCount = Math.max(file.before.split("\n").length, file.after.split("\n").length);
  const box = document.createElement("div");
  box.className = "monaco-diff-box";
  box.style.height = `${Math.min(520, Math.max(140, lineCount * 19 + 40))}px`;
  body.replaceChildren(box);
  const editor = monaco.editor.createDiffEditor(box, {
    readOnly: true, theme: "vs-dark", renderSideBySide: true,
    automaticLayout: true, minimap: { enabled: false }, scrollBeyondLastLine: false,
  });
  const language = monacoLanguage(file.path);
  editor.setModel({
    original: monaco.editor.createModel(file.before, language),
    modified: monaco.editor.createModel(file.after, language),
  });
}

async function loadDiffs() {
  if (diffsLoaded) return;
  diffsLoaded = true;
  const response = await fetch(`/api/sessions/${SESSION_KEY}/files?raw=1`);
  const data = await response.json();
  const container = document.getElementById("tab-diffs");
  container.replaceChildren();
  if (!data.files.length) {
    container.innerHTML = '<p class="muted">Aucun fichier modifié dans cette session.</p>';
    return;
  }
  const monaco = await loadMonaco();
  data.files.forEach((file, index) => {
    const details = document.createElement("details");
    details.className = "diff-file";
    const summary = document.createElement("summary");
    summary.textContent = `${file.is_new ? "NOUVEAU " : ""}${file.path} (+${file.added})`;
    details.appendChild(summary);
    const body = document.createElement("div");
    body.className = "diff-body";
    body.innerHTML = file.html;
    details.appendChild(body);
    let mounted = false;
    details.addEventListener("toggle", () => {
      if (details.open && monaco && !mounted) { mounted = true; mountMonacoDiff(monaco, body, file); }
    });
    if (index === 0) details.open = true;
    container.appendChild(details);
  });
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    ["conv", "diffs", "turns"].forEach((name) => {
      document.getElementById(`tab-${name}`).hidden = name !== tab.dataset.tab;
    });
    if (tab.dataset.tab === "diffs") loadDiffs();
    if (tab.dataset.tab === "turns") loadTurns();
  });
});

document.getElementById("composer-send").addEventListener("click", () =>
  sendText(document.getElementById("composer-text").value));

document.getElementById("kill-btn").addEventListener("click", async () => {
  await fetch(`/api/agents/${agentId}/kill`, { method: "POST" });
});

poll();
