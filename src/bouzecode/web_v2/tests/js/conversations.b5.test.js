import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// [B5] Test DOM (happy-dom) du repli du composer quand un onglet est ouvert.
// happy-dom NE VOIT PAS le CSS : ici on teste UNIQUEMENT la LOGIQUE de toggle de
// la classe .tabs-open sur .conv-main (état / handlers), pas le rendu visuel.
// Le rendu visuel (display:none réel) est couvert par le test Playwright.

const SCRIPT = "../../static/js/conversations.js";

// Arbre /api/agents/tree : 2 managers racine (permet d'ouvrir un onglet via clic).
const TREE = {
  nodes: [
    { key: "agent/mgr-1", parent: null, state: "cli", title: "Manager 1" },
    { key: "agent/mgr-2", parent: null, state: "cli", title: "Manager 2" },
  ],
};
const EMPTY_BLOCKS = { blocks: [], total: 0, status: { state: "cli" }, meta: {} };

// mountDom DÉRIVÉ DU VRAI TEMPLATE conversations.html (L44-74) : la structure
// clé pour B5 est le wrapper <section class="conv-main"> qui englobe le composer,
// la bannière agent, la zone d'erreur, #conv-tabs et #conv-panels. updateComposer
// fait `document.querySelector(".conv-main")` → sans ce wrapper il no-op.
function mountDom() {
  document.body.innerHTML = `
    <div class="conv-layout">
      <aside class="conv-sidebar"><div id="conv-list"></div></aside>
      <section class="conv-main">
        <form id="conv-new-bar" class="conv-new-bar">
          <textarea id="conv-new-input"></textarea>
          <button id="conv-new-send" type="submit"></button>
        </form>
        <div class="conv-agent-bar">
          <button id="conv-agent-toggle" type="button" aria-expanded="false" aria-controls="conv-agent-panel"></button>
          <div id="conv-agent-panel" role="radiogroup" hidden></div>
        </div>
        <div id="conv-new-error"></div>
        <div id="conv-tabs"></div>
        <div id="conv-panels"><div class="conv-empty">Vide</div></div>
      </section>
    </div>
  `;
}

function installFetch(tree = TREE) {
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
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

async function loadModule(tree = TREE) {
  mountDom();
  installFetch(tree);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

const main = () => document.querySelector(".conv-main");
const firstConvItem = () => document.querySelector("#conv-list .conv-item");

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("conversations.js — [B5] barre nouvelle conversation toujours visible", () => {
  it("écran d'accueil (aucun onglet) : la barre #conv-new-bar est présente et aucun bouton + n'existe", async () => {
    await loadModule();
    expect(document.getElementById("conv-new-bar")).not.toBeNull();
    expect(main().classList.contains("tabs-open")).toBe(false);
    // Le bouton "+" (.conv-new-tab-btn) a été supprimé : le prompt direct le remplace.
    expect(document.getElementById("conv-new-tab-btn")).toBeNull();
    expect(document.querySelector(".conv-new-tab-btn")).toBeNull();
  });

  it("ouverture d'un onglet : la barre reste dans le DOM, aucun .conv-new-tab-btn n'est injecté, .tabs-open passe en mode compact", async () => {
    await loadModule();
    const item = firstConvItem();
    expect(item).not.toBeNull();
    item.click();
    await flush();
    // La barre nouvelle conversation reste TOUJOURS présente (plus de masquage).
    expect(document.getElementById("conv-new-bar")).not.toBeNull();
    // .tabs-open est togglée pour le mode compact.
    expect(main().classList.contains("tabs-open")).toBe(true);
    // Plus aucun bouton "+" n'est créé.
    expect(document.getElementById("conv-new-tab-btn")).toBeNull();
    expect(document.querySelector("#conv-tabs .conv-new-tab-btn")).toBeNull();
  });

  it("fermeture du dernier onglet : retour à l'accueil, .tabs-open retiré, la barre reste visible", async () => {
    await loadModule();
    firstConvItem().click();
    await flush();
    expect(main().classList.contains("tabs-open")).toBe(true);

    const closeBtn = document.querySelector("#conv-tabs .conv-tab .conv-tab-close");
    expect(closeBtn).not.toBeNull();
    closeBtn.click();
    await flush();
    expect(main().classList.contains("tabs-open")).toBe(false);
    expect(document.getElementById("conv-new-bar")).not.toBeNull();

    // Réouverture d'un onglet : le mode compact se réapplique.
    firstConvItem().click();
    await flush();
    expect(main().classList.contains("tabs-open")).toBe(true);
  });
});
