import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Autonomous test file (own harness) covering the UX rules on /conversations:
//  §2 — an alert state (suspect_dead) must NEVER render as a bare dot: the label
//       ("mort") is forced even in the compact badge, plus an explanatory tooltip.
//  §3 — a running subagent must NOT appear as a flat first-level row (it stays
//       reachable via the collapsible sidebar and the inline thread markers).
// Kept separate from conversations.test.js on purpose (that file has a corrupted
// non-ASCII encoding that makes anchored edits unreliable). Vitest picks up every
// *.test.js under tests/js, so this file runs as part of the suite.

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

describe("conversations.js — regle anti-dot-seul (§2)", () => {
  it("un node suspect_dead affiche le libelle 'mort' (pas un dot rouge seul) + tooltip explicatif", async () => {
    const TREE = {
      nodes: [
        {
          key: "agent/dead-1",
          parent: null,
          state: "finished",
          suspect_dead: true,
          title: "Validateur 18:43",
        },
      ],
    };
    await loadModule(TREE);

    // Le node finished va dans la section "Termines".
    const item = document.querySelector('.conv-section-finished [data-key="agent/dead-1"]');
    expect(item).not.toBeNull();

    const badge = item.querySelector(".badge");
    expect(badge).not.toBeNull();
    // Alerte rouge : classe st-ko.
    expect(badge.classList.contains("st-ko")).toBe(true);
    // ANTI-DOT-SEUL : le libelle "mort" est present dans le texte (pas seulement un dot).
    expect(badge.textContent).toContain("mort");
    // Le dot existe toujours (on n'a rien supprime), mais il n'est PAS seul.
    expect(badge.querySelector(".pui-dot")).not.toBeNull();
    // Tooltip explicite le critere declencheur.
    expect(badge.title.length).toBeGreaterThan(0);
    expect(badge.title.toLowerCase()).toContain("mort");
  });
});

describe("conversations.js — sous-agent en cours PAS a la racine (§3)", () => {
  // Un manager en cours qui a lance un sous-agent lui aussi en cours.
  // Regle UX : le sous-agent running NE doit PAS apparaitre a la racine de la
  // section "En cours" (pas de row flat de premier niveau) ; il reste accessible
  // via la sidebar (enfant depliable) et les marqueurs inline du fil.
  function treeRunningSub() {
    return {
      nodes: [
        { key: "agent/mgr-r", parent: null, state: "running", title: "Manager R" },
        {
          key: "agent/sub-r",
          parent: "mgr-r",
          state: "running",
          run_kind: "task",
          title: "Sous-agent 19:02",
        },
      ],
    };
  }

  it("le sous-agent running n'a AUCUNE row de premier niveau dans '● En cours'", async () => {
    await loadModule(treeRunningSub());

    const running = document.querySelector(".conv-section-running");
    expect(running).not.toBeNull();

    // Le manager (racine) est bien dans "En cours".
    expect(
      running.querySelector('[data-key="agent/mgr-r"].conv-item')
    ).not.toBeNull();

    // Le sous-agent NE produit AUCUNE row flat de premier niveau.
    expect(running.querySelector('[data-key="agent/sub-r::flat"]')).toBeNull();
    // Et plus generalement aucune row porteuse d'un label "flat parent" (↳ ...).
    expect(running.querySelector(".conv-flat-parent")).toBeNull();
  });
});
