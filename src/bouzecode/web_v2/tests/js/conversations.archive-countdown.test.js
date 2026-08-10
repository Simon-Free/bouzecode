import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Ces tests prouvent le comportement du décompte "Annuler 3/2/1" du bouton
// Archiver de la sidebar (conversations.js). Niveau : DOM/timer (happy-dom +
// vitest, fake timers) — on vérifie qu'AUCUN appel backend n'est émis avant la
// fin des 3s, que "Annuler" bloque l'appel, et que deux countdowns sur deux
// items différents coexistent indépendamment (Map par item, pas de timer global).
// Fixtures DÉRIVÉES DU RÉEL : même shape /api/agents/tree que
// conversations.subagents.test.js ({ nodes:[{key, parent, state, title}] }).

const SCRIPT = "../../static/js/conversations.js";
const EMPTY_BLOCKS = { blocks: [], total: 0, status: { state: "cli" }, meta: {} };
const ARCHIVE_URL = "/api/conversations/archive";

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
    // L'endpoint d'archive : on répond ok pour laisser le flux se dérouler.
    if (url.includes(ARCHIVE_URL)) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ archived: [], skipped: [] }) });
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

// Nombre d'appels réels vers l'endpoint d'archive (ignore tree/blocks).
function archiveCalls(fetchMock) {
  return fetchMock.mock.calls.filter((c) => String(c[0]).includes(ARCHIVE_URL));
}

// Le bouton "Archiver" de la carte racine `key` (une racine depth 0 le porte).
function archiveBtn(key) {
  const item = document.querySelector(`[data-key="${key}"]`);
  if (!item) return null;
  // Le bouton peut être dans l'item lui-même ou dans le groupe conteneur.
  return item.querySelector(".conv-archive-btn")
    || item.closest(".conv-group")?.querySelector(".conv-archive-btn")
    || document.querySelector(`.conv-archive-btn`);
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_e) { /* env sans localStorage */ }
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("conversations.js — countdown 'Annuler 3/2/1' du bouton Archiver", () => {
  // Racine seule (parent null) → carte depth 0 → bouton Archiver présent.
  function treeSingle() {
    return { nodes: [{ key: "agent/root-a", parent: null, state: "finished", title: "Racine A" }] };
  }
  // Racine + un enfant (parent = id de la racine) → archive-tree.
  function treeWithChild() {
    return {
      nodes: [
        { key: "agent/root-a", parent: null, state: "finished", title: "Racine A" },
        { key: "agent/child-a", parent: "root-a", state: "finished", title: "Enfant A" },
      ],
    };
  }
  // Deux racines indépendantes A et B, chacune avec un enfant.
  function treeTwoRoots() {
    return {
      nodes: [
        { key: "agent/root-a", parent: null, state: "finished", title: "Racine A" },
        { key: "agent/child-a", parent: "root-a", state: "finished", title: "Enfant A" },
        { key: "agent/root-b", parent: null, state: "finished", title: "Racine B" },
        { key: "agent/child-b", parent: "root-b", state: "finished", title: "Enfant B" },
      ],
    };
  }

  it("(a) aucun appel d'archive n'est émis avant la fin des 3s ; l'appel part à 3s", async () => {
    const fetchMock = await loadModule(treeWithChild());
    const btn = archiveBtn("agent/root-a");
    expect(btn).not.toBeNull();
    expect(btn.textContent).toContain("Archiver");

    btn.click();
    // Immédiatement : décompte affiché, AUCUN fetch archive.
    expect(btn.textContent).toBe("Annuler 3");
    expect(archiveCalls(fetchMock)).toHaveLength(0);

    // 1s → "Annuler 2", toujours aucun appel.
    await vi.advanceTimersByTimeAsync(1000);
    expect(btn.textContent).toBe("Annuler 2");
    expect(archiveCalls(fetchMock)).toHaveLength(0);

    // 2s → "Annuler 1", toujours aucun appel.
    await vi.advanceTimersByTimeAsync(1000);
    expect(btn.textContent).toBe("Annuler 1");
    expect(archiveCalls(fetchMock)).toHaveLength(0);

    // 3s → fin du décompte : UN SEUL appel batch avec l'agent + son descendant.
    await vi.advanceTimersByTimeAsync(1000);
    const calls = archiveCalls(fetchMock);
    expect(calls).toHaveLength(1);
    const body = JSON.parse(calls[0][1].body);
    expect(body.keys).toContain("agent/root-a");
    expect(body.keys).toContain("agent/child-a"); // archive-tree : descendant inclus
  });

  it("(b) 'Annuler' pendant le décompte empêche tout appel backend", async () => {
    const fetchMock = await loadModule(treeSingle());
    const btn = archiveBtn("agent/root-a");
    expect(btn).not.toBeNull();

    btn.click();
    expect(btn.textContent).toBe("Annuler 3");

    // On avance 1s, puis on re-clique = ANNULER.
    await vi.advanceTimersByTimeAsync(1000);
    expect(btn.textContent).toBe("Annuler 2");
    btn.click(); // annulation
    expect(btn.textContent).toBe("Archiver"); // état normal restauré

    // Même en laissant filer bien au-delà des 3s, AUCUN appel n'est émis.
    await vi.advanceTimersByTimeAsync(5000);
    expect(archiveCalls(fetchMock)).toHaveLength(0);
  });

  it("(c) deux countdowns sur deux items coexistent indépendamment (annuler l'un n'affecte pas l'autre)", async () => {
    const fetchMock = await loadModule(treeTwoRoots());
    const btnA = archiveBtn("agent/root-a");
    const btnB = archiveBtn("agent/root-b");
    expect(btnA).not.toBeNull();
    expect(btnB).not.toBeNull();
    expect(btnA).not.toBe(btnB);

    // Lance les deux countdowns.
    btnA.click();
    btnB.click();
    expect(btnA.textContent).toBe("Annuler 3");
    expect(btnB.textContent).toBe("Annuler 3");

    // 1s : les deux décomptent indépendamment.
    await vi.advanceTimersByTimeAsync(1000);
    expect(btnA.textContent).toBe("Annuler 2");
    expect(btnB.textContent).toBe("Annuler 2");
    expect(archiveCalls(fetchMock)).toHaveLength(0);

    // On ANNULE A ; B doit continuer son décompte intact.
    btnA.click();
    expect(btnA.textContent).toBe("Archiver");
    expect(btnB.textContent).toBe("Annuler 2"); // B non affecté

    // On laisse filer jusqu'à la fin du décompte de B (2s restantes).
    await vi.advanceTimersByTimeAsync(2000);

    const calls = archiveCalls(fetchMock);
    // UN SEUL appel : celui de B (A a été annulé).
    expect(calls).toHaveLength(1);
    const body = JSON.parse(calls[0][1].body);
    expect(body.keys).toContain("agent/root-b");
    expect(body.keys).toContain("agent/child-b");
    // Aucune clé de A ne doit apparaître.
    expect(body.keys).not.toContain("agent/root-a");
    expect(body.keys).not.toContain("agent/child-a");
  });

  // Régression : un SOUS-AGENT en attente d'action (awaiting_input) remonte en
  // section « Nécessite une action » sous forme d'entrée FLAT (clé `...::flat`,
  // _realKey = clé réelle). Avant le fix, wantArch excluait les entrées FLAT
  // (`!n._realKey`) → aucun bouton Archiver sur les méta-agents/sous-agents.
  // Désormais le bouton est présent et archive la clé RÉELLE (pas `::flat`).
  it("(d) un sous-agent en 'Nécessite une action' a un bouton Archiver qui archive la clé réelle", async () => {
    const tree = {
      nodes: [
        { key: "agent/root-a", parent: null, state: "finished", title: "Racine A" },
        { key: "agent/child-a", parent: "root-a", state: "awaiting_input", title: "Enfant A" },
      ],
    };
    const fetchMock = await loadModule(tree);

    // Le sous-agent awaiting_input est cloné FLAT (data-key = clé flat) en needinput.
    const flatItem = document.querySelector(`[data-key="agent/child-a::flat"]`);
    expect(flatItem).not.toBeNull();
    const btn = flatItem.querySelector(".conv-archive-btn");
    expect(btn).not.toBeNull();
    expect(btn.textContent).toContain("Archiver");

    btn.click();
    expect(btn.textContent).toBe("Annuler 3");
    expect(archiveCalls(fetchMock)).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(3000);
    const calls = archiveCalls(fetchMock);
    expect(calls).toHaveLength(1);
    const body = JSON.parse(calls[0][1].body);
    // Archive la clé RÉELLE, pas la clé flat.
    expect(body.keys).toContain("agent/child-a");
    expect(body.keys).not.toContain("agent/child-a::flat");
  });
});
