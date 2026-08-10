// §2/§3/§4 — orphelins validateurs (parent archivé/purgé/disparu).
//
// Un node kind:validate dont le parent est ABSENT de l'arbre ne doit PAS
// apparaître comme conversation racine standard dans « Terminés ». Il est
// rattaché sous une entrée FANTÔME grisée repliée (« ⌀ conversation archivée »),
// où il reste visible et ouvrable (aucune perte d'information).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../static/js/conversations.js",
);
const EMPTY_BLOCKS = { blocks: [], events: [] };

function mountDom() {
  document.body.innerHTML = `
    <div id="conv-list"></div>
    <div id="tabs"></div>
    <div id="panels"></div>
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
  installFetch(tree);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

describe("conversations.js — orphelins validateurs (§2/§3/§4)", () => {
  // Parent codeur 402a41074631 ABSENT de l'arbre : seul le validateur est listé.
  const ORPHAN_TREE = {
    nodes: [
      {
        key: "agent/val-orphan",
        agent_id: "val-orphan",
        parent: "402a41074631",
        state: "finished",
        kind: "validate",
        run_kind: "validate",
        verdict: "OK",
        title: "Validateur 09:12",
      },
    ],
  };

  it("§2 : un validateur orphelin n'est PAS une conversation racine standard", async () => {
    await loadModule(ORPHAN_TREE);
    // Il ne doit pas figurer comme racine directe de la section Terminés.
    const asRoot = document.querySelector(
      '.conv-section-finished [data-key="agent/val-orphan"]:not(.conv-child)',
    );
    expect(asRoot).toBeNull();
  });

  it("§3 : une entrée fantôme grisée est créée pour le parent absent", async () => {
    await loadModule(ORPHAN_TREE);
    const ghost = document.querySelector(
      '.conv-section-finished [data-key="ghost/402a41074631"]',
    );
    expect(ghost).not.toBeNull();
    // Grisée via la classe dédiée (aucune info supprimée, juste atténuée).
    expect(ghost.classList.contains("conv-item--ghost")).toBe(true);
    // Libellé fantôme lisible.
    expect(ghost.textContent).toContain("conversation archivée");
  });

  it("§4 : le validateur orphelin reste rattaché sous le fantôme (visible/ouvrable)", async () => {
    await loadModule(ORPHAN_TREE);
    const ghostGroup = document
      .querySelector('[data-key="ghost/402a41074631"]')
      .closest(".conv-group");
    expect(ghostGroup).not.toBeNull();
    // Le validateur est un enfant du groupe fantôme (childrenOf → match agent_id).
    const child = ghostGroup.querySelector('[data-key="agent/val-orphan"]');
    expect(child).not.toBeNull();
  });
});
