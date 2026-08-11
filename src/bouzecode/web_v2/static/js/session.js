// [desc] Page session: polling incrémental des blocs HTML, réponse aux questions, kill, onglet diffs. [/desc]
"use strict";

let nextIndex = 0;
let lastState = "";
let diffsLoaded = false;
// Streaming token-par-token : poll de /partial qui alimente un `.streaming-block`
// provisoire (texte assistant en cours d'écriture), retiré dès que le vrai bloc
// message complet arrive via poll()/blocks. Calqué sur conversations.js.
let partialActive = false;
let partialPoller = null;
// Snapshot des agents interrompus par le dernier arrêt serveur (GET /api/interrupted,
// boot-figé). Fetché UNE fois par session (ne change pas hors relaunch/dismiss) ; sert
// à décider si CET agent affiche le bandeau « interrompu — Reprendre » dans l'onglet.
let interruptedItems = null;
let interruptedFetched = false;
// Dernier statut / dernière méta reçus : la bascule de langue les redessine sans attendre
// le prochain poll (jusqu'à 5 s d'écart, soit un en-tête à moitié traduit).
let lastStatus = null;
let lastMeta = null;
const isAgent = SESSION_KEY.startsWith("agent/");
const agentId = isAgent ? SESSION_KEY.split("/")[1] : "";

const conv = document.getElementById("conv");
const badge = document.getElementById("s-badge");

function pinnedToBottom() {
  return window.innerHeight + window.scrollY >= document.body.scrollHeight - 120;
}

// La pastille réutilise le vocabulaire d'état PARTAGÉ (`state.*`), celui de la sidebar et des
// chips : un agent ne peut pas être « terminé » ici et « done » ailleurs. Le serveur peut
// inventer un état que le dictionnaire ignore — on rend alors le code brut plutôt que le
// marqueur ⟦state.xxx⟧, qui ferait passer un état inconnu pour un bug de traduction.
function stateLabel(state) {
  const key = `state.${state}`;
  return window.i18n.messages.en[key] === undefined ? state : window.i18n.t(key);
}

function setStatus(status) {
  lastStatus = status;
  lastState = status.state;
  badge.textContent = stateLabel(status.state);
  badge.className = `badge st-${status.state}`;
  document.getElementById("kill-btn").hidden = !(isAgent && status.state === "running");
  document.getElementById("composer").hidden = !(isAgent && status.state !== "running");
  updateInterruptedBanner(status.state);
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

// Cet agent est-il dans le snapshot des interrompus (crash/reboot), avec une action de
// reprise possible (pas "info" = déjà repris auto) ? Le bandeau ne s'affiche que si l'agent
// n'est PAS en train de tourner (dès qu'il redémarre après « Reprendre », state=running → on cache).
function updateInterruptedBanner(state) {
  const banner = document.getElementById("interrupted-banner");
  if (!banner) return;
  // `agentId` est une CHAÎNE (l.18), pas une fonction : la version précédente écrivait
  // `agentId(it.agent_id)` — copier-coller de conversations.js, où agentId() est un helper.
  // Résultat : TypeError ici, donc poll() cassait avant de se replanifier ET avant de
  // relancer pollPartial → page figée, streaming mort. On normalise les deux côtés, la
  // liste des interrompus pouvant renvoyer « <id> » comme « agent/<id> ».
  const item = (interruptedItems || []).find(
    (it) => it && it.action !== "info" && agentId
      && String(it.agent_id || "").replace(/^agent\//, "") === agentId
  );
  banner.hidden = !(isAgent && item && state !== "running");
}

// Branche le bouton « Reprendre » du bandeau : relance l'agent là où il s'est arrêté
// (POST /relaunch = recovery.resume-from, MÊME endpoint que l'ancien chemin 2), purge le
// snapshot interrompus (dismiss global) puis cache le bandeau. Le poll suivant verra
// state=running → le bandeau reste caché.
function wireInterruptedBanner() {
  const btn = document.getElementById("interrupted-resume");
  if (!btn || !isAgent) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    await fetch(`/api/conversations/${agentId}/relaunch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "" }),
    });
    await fetch("/api/interrupted/dismiss", { method: "POST" });
    interruptedItems = [];
    document.getElementById("interrupted-banner").hidden = true;
    btn.disabled = false;
  });
}

function setMeta(meta) {
  if (!meta || !meta.first_message) return;
  lastMeta = meta;
  document.getElementById("s-title").textContent = meta.first_message.slice(0, 160);
  const tokens = `${Math.round((meta.input_tokens || 0) / 1000)}k in / ${Math.round((meta.output_tokens || 0) / 1000)}k out`;
  const turns = window.i18n.t("session.meta_turns", { n: meta.turn_count });
  document.getElementById("s-meta").textContent =
    [meta.model, turns, tokens, meta.saved_at].filter(Boolean).join(" · ");
  document.getElementById("diff-count").textContent = meta.files_edited ? `(${meta.files_edited})` : "";
}

async function poll() {
  // Snapshot interrompus : fetché UNE seule fois (boot-figé). On le récupère avant le 1er
  // setStatus pour que le bandeau s'affiche dès le premier rendu si l'agent est concerné.
  if (isAgent && !interruptedFetched) {
    interruptedFetched = true;
    try {
      const r = await fetch("/api/interrupted");
      if (r.ok) {
        const rep = await r.json();
        interruptedItems = (rep && !rep.dismissed && Array.isArray(rep.items)) ? rep.items : [];
      } else {
        interruptedItems = [];
      }
    } catch (_) {
      interruptedItems = [];
    }
  }
  const response = await fetch(`/api/sessions/${SESSION_KEY}/blocks?after=${nextIndex}`);
  if (response.ok) {
    const data = await response.json();
    const pinned = pinnedToBottom();
    // Un vrai bloc message complet arrive : retire le bloc streaming provisoire
    // (le message rendu le remplace) AVANT d'insérer, pour éviter le doublon.
    if (data.blocks.length) {
      conv.querySelectorAll(".streaming-block, .streaming-thinking, .streaming-tool")
        .forEach((el) => el.remove());
    }
    data.blocks.forEach((block) => conv.insertAdjacentHTML("beforeend", block.html));
    if (data.blocks.length) {
      // Le chrome de ces blocs arrive du serveur avec sa clé et son texte anglais : un
      // utilisateur en français doit le lire en français dès l'insertion. Les clés restent
      // dans le DOM, donc c'est idempotent et une bascule ultérieure les réécrira aussi.
      window.i18n.applyDom(conv);
      nextIndex = data.total;
      if (pinned) window.scrollTo(0, document.body.scrollHeight);
    }
    setMeta(data.meta);
    setStatus(data.status || { state: "cli" });
  }
  const active = lastState === "running" || lastState === "awaiting_input";
  setTimeout(poll, active ? 1500 : 5000);
  // Reprise/démarrage du streaming token-par-token quand l'agent génère.
  if (lastState === "running" && !partialActive && document.visibilityState !== "hidden") {
    partialActive = true;
    pollPartial();
  }
}

// Rend l'état partiel {phase, text, thinking} dans un conteneur (streaming live).
// - thinking non vide -> bloc repliable `.streaming-thinking` (loader "Réflexion en
//   cours…" tant que phase==="thinking", puis se referme .collapsed dès le texte).
// - text -> `.streaming-block` (tokens qui grandissent). Si le texte contient un
//   `<tool_use name="X"`, un header `.streaming-tool` "Outil en cours : X" s'affiche.
// Le vrai bloc rendu (poll()/blocks) retire tout ça dès que le message est complet.
function renderStreamingPartial(container, data) {
  const phase = data.phase || "text";
  const thinking = data.thinking || "";
  const text = data.text || "";

  // --- Bloc thinking repliable ---
  let stk = container.querySelector(".streaming-thinking");
  if (thinking) {
    if (!stk) {
      stk = document.createElement("div");
      stk.className = "streaming-thinking";
      const head = document.createElement("div");
      head.className = "st-head";
      head.innerHTML = '<span class="st-spinner"></span><span class="st-label"></span>';
      head.addEventListener("click", () => stk.classList.toggle("collapsed"));
      const body = document.createElement("div");
      body.className = "st-body";
      stk.appendChild(head);
      stk.appendChild(body);
      container.appendChild(stk);
    }
    const label = stk.querySelector(".st-label");
    const body = stk.querySelector(".st-body");
    if (phase === "thinking") {
      label.textContent = window.i18n.t("session.thinking_live");
      stk.classList.remove("collapsed");
      stk.classList.add("thinking-active");
    } else {
      label.textContent = window.i18n.t("session.thinking");
      stk.classList.add("collapsed");
      stk.classList.remove("thinking-active");
    }
    if (body.textContent !== thinking) body.textContent = thinking;
  } else if (stk) {
    stk.remove();
  }

  // --- Header "outil en cours" (détecté dans le texte partiel) ---
  const toolMatches = [...text.matchAll(/<tool_use\s+name="([^"]+)"/g)];
  const toolName = toolMatches.length ? toolMatches[toolMatches.length - 1][1] : null;
  let stool = container.querySelector(".streaming-tool");
  if (phase === "text" && toolName) {
    if (!stool) {
      stool = document.createElement("div");
      stool.className = "streaming-tool";
      stool.innerHTML = '<span class="st-spinner"></span><span class="st-tool-label"></span>';
      // insérer avant le streaming-block s'il existe déjà, sinon en fin
      const sbExisting = container.querySelector(".streaming-block");
      container.insertBefore(stool, sbExisting || null);
    }
    stool.querySelector(".st-tool-label").textContent =
      window.i18n.t("session.tool_running", { tool: toolName });
  } else if (stool) {
    stool.remove();
  }

  // --- Bloc texte assistant (tokens qui grandissent) ---
  let sb = container.querySelector(".streaming-block");
  if (phase === "text" && text) {
    if (!sb) {
      sb = document.createElement("div");
      sb.className = "streaming-block";
      container.appendChild(sb);
    }
    if (sb.textContent !== text) sb.textContent = text;
  } else if (sb) {
    sb.remove();
  }
}

// Streaming token-par-token : fetch /partial et alimente les blocs live dans #conv.
// Le vrai bloc rendu (via poll()/blocks) les remplace dès que le message est complet.
async function pollPartial() {
  try {
    const response = await fetch(`/api/sessions/${SESSION_KEY}/partial`);
    if (response.ok) {
      const data = await response.json();
      const pinned = pinnedToBottom();
      renderStreamingPartial(conv, data || {});
      if (pinned) window.scrollTo(0, document.body.scrollHeight);
    }
  } catch (_) { /* réseau : on retentera */ }
  // pollPartial ne sert QU'au streaming (running) sur un onglet visible : sinon on
  // STOPPE (aucun re-setTimeout). poll() relancera pollPartial si l'état repasse à running.
  if (lastState === "running" && document.visibilityState !== "hidden") {
    partialActive = true;
    partialPoller = setTimeout(pollPartial, 250);
  } else {
    partialActive = false;
    partialPoller = null;
  }
}

// Hook de test (happy-dom/vitest) : expose poll/pollPartial + un setter de lastState
// pour piloter le streaming token-par-token depuis les tests, sans navigateur.
if (typeof window !== "undefined") {
  window.__sessionTest = {
    poll,
    pollPartial,
    setLastState: (s) => { lastState = s; },
    getPartialActive: () => partialActive,
  };
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
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = window.i18n.t("session.no_files");
    container.appendChild(empty);
    return;
  }
  const monaco = await loadMonaco();
  data.files.forEach((file, index) => {
    const details = document.createElement("details");
    details.className = "diff-file";
    const summary = document.createElement("summary");
    const isNew = file.is_new ? `${window.i18n.t("session.file_new")} ` : "";
    summary.textContent = `${isNew}${file.path} (+${file.added})`;
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

// Bouton « ? » par bulle assistant : ouvre le contexte injecté du tour.
// Délégation sur #conv car les bulles sont injectées dynamiquement par poll().
function closeTurnContextModal() {
  const existing = document.getElementById("turn-context-modal");
  if (existing) existing.remove();
}

function renderTurnContext(html) {
  closeTurnContextModal();
  const overlay = document.createElement("div");
  overlay.id = "turn-context-modal";
  overlay.className = "turn-context-modal";

  const dialog = document.createElement("div");
  dialog.className = "turn-context-dialog";

  const header = document.createElement("div");
  header.className = "turn-context-header";
  const title = document.createElement("h3");
  title.textContent = window.i18n.t("session.turn_context_title");
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "turn-context-close";
  closeBtn.setAttribute("aria-label", window.i18n.t("session.close"));
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", closeTurnContextModal);
  header.append(title, closeBtn);

  const body = document.createElement("div");
  body.className = "turn-context-body";

  // L'endpoint /turns/<n>/context renvoie du HTML riche (delta/cached/tokens,
  // CSS inline) produit par render_context_diag_html — on l'injecte tel quel.
  if (html) body.innerHTML = html;
  else body.textContent = window.i18n.t("session.turn_context_empty");

  dialog.append(header, body);
  overlay.appendChild(dialog);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeTurnContextModal();
  });
  document.body.appendChild(overlay);
}

conv.addEventListener("click", async (e) => {
  const btn = e.target.closest(".turn-context-btn");
  if (!btn) return;
  const turn = btn.dataset.turn;
  if (!turn) return;
  const response = await fetch(
    `/api/sessions/${SESSION_KEY}/turns/${turn}/context`
  );
  if (!response.ok) return;
  const html = await response.text();
  renderTurnContext(html);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeTurnContextModal();
});

document.getElementById("composer-send").addEventListener("click", () =>
  sendText(document.getElementById("composer-text").value));

// Enter (sans Shift) envoie ; Shift+Enter insère un saut de ligne.
document.getElementById("composer-text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendText(event.target.value);
  }
});

document.getElementById("kill-btn").addEventListener("click", async () => {
  await fetch(`/api/agents/${agentId}/kill`, { method: "POST" });
});

// Bascule de langue — L'UNIQUE point de redessin de la page. `applyDom` (dans le noyau) a déjà
// retraduit tout ce qui porte un `data-i18n` dans le gabarit ; ne restent que les fragments
// composés en JavaScript. Les onglets déjà chargés sont rejoués (le drapeau de garde tombe),
// ceux jamais ouverts n'ont rien à réécrire.
window.i18n.onChange(() => {
  if (lastStatus) setStatus(lastStatus);
  if (lastMeta) setMeta(lastMeta);
  if (diffsLoaded) { diffsLoaded = false; loadDiffs(); }
  if (turnsLoaded) { turnsLoaded = false; loadTurns(); }
  // costs.js est une IIFE : il publie son redessin sur `window` plutôt que dans la portée
  // globale partagée. Absent tant que l'onglet Coûts n'a jamais été ouvert.
  if (window.redrawCosts) window.redrawCosts();
});

poll();
