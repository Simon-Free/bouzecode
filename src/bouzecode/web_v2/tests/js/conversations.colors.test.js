import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Couvre la sémantique d'état par VERDICT sur /conversations :
//  - un sous-agent au verdict KO ne doit JAMAIS porter la classe "ok" (st-ok vert) ;
//    son badge d'état doit être st-ko (rouge). Fini le vert+KO côte à côte.
//  - un node archivé ne doit PAS porter de pastille verte (st-ok) : il passe en gris
//    neutre (st-cli).
// Même harness que conversations.subagents.test.js (fixtures = vrais arbres /api/agents/tree).
//
// OÙ ON REGARDE, ET POURQUOI. Ces deux règles s'observaient à l'origine sur les chips du
// rail sous-agents du panneau. Ce rail a été SUPPRIMÉ depuis (UI-2 : la navigation vers les
// sous-agents passe par la sidebar et les marqueurs inline — trois fichiers de tests gardent
// son absence, dont conversations.ui2.test.js). Le test continuait donc de chercher des chips
// qu'aucun code ne produit plus, et échouait sur une surface morte, pas sur la règle.
// La surface VIVANTE est la sidebar : un sous-agent — archivé compris — est rendu imbriqué
// sous sa racine, derrière le toggle « N sous-agents », et son badge sort du même
// `effectiveState` que les chips d'alors. On déplie donc comme le ferait l'utilisateur.

const SCRIPT = "../../static/js/conversations.js";
const EMPTY_BLOCKS = { blocks: [], total: 0, status: { state: "cli" }, meta: {} };

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
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

async function loadModule(tree) {
  mountDom();
  const fetchMock = installFetch(tree);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
  return fetchMock;
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_e) { /* jsdom-less env */ }
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("conversations.js — le VERDICT prime pour un node terminé", () => {
  function treeMgrValidatorKO() {
    return {
      nodes: [
        { key: "agent/mgr-ko", parent: null, state: "finished", title: "Manager KO" },
        {
          key: "agent/val-ko",
          parent: "mgr-ko",
          state: "finished",
          run_kind: "validate",
          title: "Validateur 18:28",
          verdict: "KO",
        },
      ],
    };
  }

  // Déplie la racine et rend la ligne du sous-agent, par le chemin de l'utilisateur.
  async function subagentRow(tree, rootKey, childKey) {
    await loadModule(tree);
    const root = document.querySelector(`[data-key="${rootKey}"].conv-item`);
    expect(root).not.toBeNull();
    const toggle = root.parentElement.querySelector(".conv-toggle");
    expect(toggle, "la racine doit offrir un toggle « N sous-agents »").not.toBeNull();
    toggle.click();
    await flush();

    const row = document.querySelector(`.conv-children [data-key="${childKey}"].conv-item`);
    expect(row, `le sous-agent ${childKey} doit être rendu sous sa racine`).not.toBeNull();
    return row;
  }

  it("sous-agent finished au verdict KO : badge N'A PAS st-ok, A st-ko", async () => {
    const row = await subagentRow(treeMgrValidatorKO(), "agent/mgr-ko", "agent/val-ko");
    expect(row.textContent).toContain("Validateur 18:28");

    // Le badge d'ÉTAT suit le verdict : rouge, jamais vert.
    const badge = row.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge.classList.contains("st-ok")).toBe(false); // pas de vert "terminé"
    expect(badge.classList.contains("st-ko")).toBe(true);  // rouge KO
  });

  it("sous-agent archivé : badge N'A PAS st-ok (pas de pastille verte), A st-cli (gris neutre)", async () => {
    // Un archivé n'est jamais une RACINE de la sidebar, mais il reste rendu imbriqué sous
    // la sienne (childrenOf ne filtre pas les archivés) : même chemin effectiveState.
    const TREE = {
      nodes: [
        { key: "agent/mgr-arch", parent: null, state: "finished", title: "Manager arch" },
        {
          key: "agent/arch-1",
          parent: "mgr-arch",
          state: "finished",
          archived: true,
          title: "Ancien enfant 12:00",
        },
      ],
    };
    const row = await subagentRow(TREE, "agent/mgr-arch", "agent/arch-1");
    expect(row.textContent).toContain("Ancien enfant 12:00");

    const badge = row.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge.classList.contains("st-ok")).toBe(false); // JAMAIS de vert sur un archivé
    expect(badge.classList.contains("st-cli")).toBe(true); // gris neutre "archivé"
  });
});
