import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Couvre la sémantique d'état par VERDICT sur /conversations :
//  - un sous-agent au verdict KO ne doit JAMAIS porter la classe "ok" (st-ok vert) ;
//    son badge d'état doit être st-ko (rouge). Fini le vert+KO côte à côte.
//  - un node archivé ne doit PAS porter de pastille verte (st-ok) : il passe en gris
//    neutre (st-cli).
// Même harness que conversations.subagents.test.js (fixtures = vrais arbres /api/agents/tree).

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

  async function openManagerTab(tree) {
    await loadModule(tree);
    const item = document.querySelector('[data-key="agent/mgr-ko"].conv-item');
    expect(item).not.toBeNull();
    item.click();
    await flush();
  }

  it("chip d'un sous-agent finished au verdict KO : badge N'A PAS st-ok, A st-ko", async () => {
    await openManagerTab(treeMgrValidatorKO());

    const chips = Array.from(document.querySelectorAll(".conv-sub-chip"));
    const chip = chips.find((c) => c.textContent.includes("Validateur 18:28"));
    expect(chip).not.toBeUndefined();

    // Le badge d'ÉTAT du chip (pas le pill verdict) suit le verdict : rouge, jamais vert.
    const badge = chip.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge.classList.contains("st-ok")).toBe(false); // pas de vert "terminé"
    expect(badge.classList.contains("st-ko")).toBe(true);  // rouge KO
  });

  it("sous-agent archivé : chip badge N'A PAS st-ok (pas de pastille verte), A st-cli (gris neutre)", async () => {
    // Les archivés sont filtrés de la liste sidebar principale ; on les observe donc
    // via le rail sous-agents d'un manager (même chemin effectiveState que le verdict KO).
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
    await loadModule(TREE);
    const mgr = document.querySelector('[data-key="agent/mgr-arch"].conv-item');
    expect(mgr).not.toBeNull();
    mgr.click();
    await flush();

    const chips = Array.from(document.querySelectorAll(".conv-sub-chip"));
    const chip = chips.find((c) => c.textContent.includes("Ancien enfant 12:00"));
    expect(chip).not.toBeUndefined();

    const badge = chip.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge.classList.contains("st-ok")).toBe(false); // JAMAIS de vert sur un archivé
    expect(badge.classList.contains("st-cli")).toBe(true); // gris neutre "archivé"
  });
});
