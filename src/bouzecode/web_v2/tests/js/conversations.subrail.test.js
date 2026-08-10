import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Régression : `Uncaught ReferenceError: sub is not defined` dans openTab.
//
// L'objet `entry` construit par openTab référence `sub` (le conteneur DOM du rail
// sous-agents, consommé ensuite par renderSubagents via entry.sub). La variable
// locale `const sub = node(paneConv, "div", "conv-sub-rail")` avait été oubliée :
// à l'exécution de openTab, `sub` n'était pas défini → ReferenceError, et le panneau
// ne se montait jamais.
//
// Aucun test existant ne MONTAIT openTab (subagents.test.js teste la sidebar/rendu de
// liste ; tabs.test.js n'exerçait pas cette régression), et il n'y a pas de lint
// no-undef → le bug passait totalement silencieux. Ce fichier ferme ce trou : il
// déclenche openTab via le VRAI flux UI (clic sur un .conv-item de la sidebar) et
// vérifie que le rail sous-agents (entry.sub) existe bien dans le DOM.
//
// openTab/openTabs ne sont ni exportés ni sur window : on ne peut les atteindre QUE
// par ce clic — d'où l'usage du même harnais autonome que les autres *.test.js.

const SCRIPT = "../../static/js/conversations.js";

const EMPTY_BLOCKS = { blocks: [], total: 0, status: { state: "cli" }, meta: {} };

// Manager racine + un sous-agent rattaché. On ouvre le sous-agent en onglet : c'est
// openTab qui construit l'objet `entry` (la ligne où la régression `sub` se produisait).
const KEY_MGR = "agent/mgr";
const KEY_SUB = "agent/aaaa11112222333344445555666677778888";

const TREE = {
  nodes: [
    { key: KEY_MGR, parent: null, state: "running", run_kind: "manager", title: "Manager" },
    { key: KEY_SUB, parent: "mgr", state: "running", run_kind: "subagent", title: "Sous-agent · coder" },
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
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

async function loadModule(tree) {
  mountDom();
  installFetch(tree);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

// Clique le .conv-item d'une clé donnée dans la sidebar → déclenche openTab en interne.
// Renvoie le panneau visible (le seul .conv-panel sans attribut hidden).
async function openTabFor(key) {
  const item = document.querySelector(`#conv-list .conv-item[data-key="${key}"]`);
  expect(item, `conv-item introuvable pour ${key}`).toBeTruthy();
  item.click();
  await flush();
  const panel = document.querySelector("#conv-panels .conv-panel:not([hidden])");
  expect(panel, "aucun panneau visible après le clic (openTab a-t-il throw ?)").toBeTruthy();
  return panel;
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_e) { /* env sans localStorage */ }
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("openTab — régression `sub is not defined` (rail sous-agents)", () => {
  it("ouvrir un onglet ne throw pas et monte le rail sous-agents (entry.sub) dans le DOM", async () => {
    await loadModule(TREE);
    // Le clic exécute openTab, qui construit `entry` en référençant `sub`.
    // Avant le fix, cette ligne levait ReferenceError et le panneau ne se montait pas.
    const panel = await openTabFor(KEY_SUB);
    // entry.sub est inséré dans le DOM sous forme de conteneur .conv-sub-rail.
    const rail = panel.querySelector(".conv-sub-rail");
    expect(rail, "le conteneur entry.sub (.conv-sub-rail) doit exister dans le panneau").toBeTruthy();
  });

  it("le rail sous-agents est placé dans .conv-pane-conv (sous les messages)", async () => {
    await loadModule(TREE);
    const panel = await openTabFor(KEY_SUB);
    const paneConv = panel.querySelector(".conv-pane-conv");
    expect(paneConv).toBeTruthy();
    const rail = paneConv.querySelector(".conv-sub-rail");
    expect(rail, ".conv-sub-rail doit être enfant de .conv-pane-conv").toBeTruthy();
  });

});
