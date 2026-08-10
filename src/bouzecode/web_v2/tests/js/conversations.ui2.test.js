import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// UI-2 : compactage de l'en-tête de /conversations.
// Critères d'acceptation :
//  1. UNE seule ligne meta (.conv-panel-status) : badge état + modèle + id court + branche
//     + icône document (.conv-meta-doc) ouvrant un menu (.conv-meta-menu) contenant
//     le chemin session.json sélectionnable + Copier + Télécharger.
//     Plus AUCUN bloc .conv-path affiché en permanence (enfant direct de .conv-panel).
//  2. AUCUN rail sous-agents (.conv-subagents) dans le panel conversation : la
//     navigation vers les sous-agents passe par la sidebar + les marqueurs inline.

const SCRIPT = "../../static/js/conversations.js";

const EMPTY_BLOCKS = { blocks: [], total: 0, status: { state: "cli" }, meta: {} };

// Arbre : 1 manager avec 1 enfant CLI (inactif) -> rail replié par défaut.
const TREE_IDLE = {
  nodes: [
    { key: "agent/mgr-1", parent: null, state: "cli", title: "Manager 1", branch: "develop",
      agent_id: "d72e2180", session_path: "C:/sessions/d72e2180/session.json" },
    { key: "agent/sub-a", parent: "mgr-1", state: "cli", title: "Subagent A" },
  ],
};

// Arbre : enfant awaiting_input -> rail auto-ouvert.
const TREE_AWAIT = {
  nodes: [
    { key: "agent/mgr-aw", parent: null, state: "running", title: "Manager aw", branch: "develop",
      agent_id: "aa11bb22", session_path: "C:/sessions/aa11bb22/session.json" },
    { key: "agent/sub-aw", parent: "mgr-aw", state: "awaiting_input", title: "Sub aw" },
  ],
};

// Arbre : 1 enfant running + 1 enfant suspect_dead -> synthèse "1 ok / 1 alerte".
const TREE_MIX = {
  nodes: [
    { key: "agent/mgr-mix", parent: null, state: "running", title: "Manager mix", branch: "main",
      agent_id: "cc33dd44", session_path: "C:/sessions/cc33dd44/session.json" },
    { key: "agent/sub-ok", parent: "mgr-mix", state: "finished", title: "Sub ok" },
    { key: "agent/sub-ko", parent: "mgr-mix", state: "running", title: "Sub ko", suspect_dead: true },
  ],
};

function mountDom() {
  document.body.innerHTML = `
    <aside><div id="conv-list"></div></aside>
    <form id="conv-new-bar"><textarea id="conv-new-input"></textarea>
      <button id="conv-new-send" type="submit"></button></form>
    <div id="conv-new-error"></div>
    <div id="conv-tabs"></div>
    <div id="conv-panels"><div class="conv-empty">Vide</div></div>
  `;
}

function installFetch(tree) {
  const fetchMock = vi.fn((url) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(tree) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock;
  return fetchMock;
}

async function flush() {
  for (let i = 0; i < 25; i++) await Promise.resolve();
}

async function loadModule(tree) {
  mountDom();
  installFetch(tree);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

// Ouvre l'onglet de la racine `key` en cliquant sa ligne dans la sidebar, puis renvoie le panel.
async function openPanel(key) {
  const item = document.querySelector(`#conv-list [data-key="${key}"]`);
  expect(item, `ligne sidebar ${key}`).not.toBeNull();
  item.click();
  await flush();
  // Le panel actif est le dernier .conv-panel non masqué.
  const panels = [...document.querySelectorAll("#conv-panels .conv-panel")];
  const active = panels.find((p) => !p.hidden) || panels[panels.length - 1];
  expect(active, "panel actif").toBeTruthy();
  return active;
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_) {}
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("UI-2 — ligne meta unique + menu document", () => {
  it("le panel n'a qu'UNE ligne meta et AUCUN bloc .conv-path permanent", async () => {
    await loadModule(TREE_IDLE);
    const panel = await openPanel("agent/mgr-1");
    // Exactement une ligne meta.
    expect(panel.querySelectorAll(".conv-panel-status").length).toBe(1);
    // Plus de bloc chemin affiché en permanence.
    expect(panel.querySelector(":scope > .conv-path")).toBeNull();
    expect(panel.querySelector(".conv-panel-status .conv-meta-doc")).not.toBeNull();
  });

  it("la ligne meta contient badge + id court + branche ; le menu document contient chemin + Copier + Télécharger", async () => {
    await loadModule(TREE_IDLE);
    const panel = await openPanel("agent/mgr-1");
    const status = panel.querySelector(".conv-panel-status");
    // id court (#d72e2180) et branche (develop) présents dans la ligne meta.
    expect(status.textContent).toContain("d72e2180");
    expect(status.textContent).toContain("develop");
    // Menu document : chemin sélectionnable + boutons Copier/Télécharger.
    const menu = panel.querySelector(".conv-meta-menu");
    expect(menu).not.toBeNull();
    expect(menu.querySelector(".conv-path-code").textContent).toContain("session.json");
    const btns = [...menu.querySelectorAll(".conv-path-btn")].map((b) => b.textContent);
    expect(btns.join(" ")).toContain("Copier");
    expect(btns.join(" ")).toContain("Télécharger");
  });
});

describe("UI-2 — aucun rail sous-agents dans le panel", () => {
  it("le panel conversation ne contient AUCUN bloc .conv-subagents (rail supprimé)", async () => {
    await loadModule(TREE_IDLE);
    const panel = await openPanel("agent/mgr-1");
    expect(panel.querySelector(".conv-subagents")).toBeNull();
    expect(panel.querySelector(".conv-sub-head")).toBeNull();
    expect(panel.querySelector(".conv-sub-body")).toBeNull();
    expect(panel.querySelector(".conv-sub-chip")).toBeNull();
  });

  it("même avec plusieurs sous-agents (dont un en alerte), aucun rail n'est rendu", async () => {
    await loadModule(TREE_MIX);
    const panel = await openPanel("agent/mgr-mix");
    expect(panel.querySelector(".conv-subagents")).toBeNull();
  });

  it("même avec un enfant awaiting_*, aucun rail auto-ouvert n'apparaît", async () => {
    await loadModule(TREE_AWAIT);
    const panel = await openPanel("agent/mgr-aw");
    expect(panel.querySelector(".conv-subagents")).toBeNull();
  });
});
