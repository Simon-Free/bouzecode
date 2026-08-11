import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";

// L'INCOHÉRENCE À TUER (un agent mort à 0 bloc, rc -1) :
// au même instant, la vignette de la sidebar portait « mort ? », sa description
// « terminé · branche agent/deadbeef », le panneau de détail « terminé », et le board
// « planté ». Ces tests prouvent que les trois surfaces FRONT disent le même mot, celui
// de la vivacité servie par le backend (`liveness`), et qu'AUCUNE ne dit « terminé ».
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(__dirname, "../../static/js/conversations.js");

const AGENT = "a1b2c3d4e5f6";
const KEY = `agent/${AGENT}`;

// Le node tel que /api/agents/tree le sert pour cet agent : session close (state
// "finished"), aucun tour, code de sortie non nul → suspect_dead, et la vivacité
// croisée par le backend (pid + close_reason + final_answer) dit `crashed`.
const NODE_MORT = {
  key: KEY, agent_id: AGENT, parent: null, state: "finished",
  turn_count: 0, returncode: -1, suspect_dead: true, liveness: "crashed",
  interrupted: true, branch: "agent/deadbeef", title: "corrige le badge",
  title_full: "corrige le badge de statut", started_at: "2026-07-28T09:00:00Z",
};

// Ce que /api/sessions/<key>/blocks sert pour le MÊME agent : le panneau lit `liveness`
// à côté de `state`, sinon il rebadge « terminé » ce que la sidebar dit mort.
const BLOCKS_MORT = {
  blocks: [], total: 0, meta: { model: "opus" },
  status: { state: "finished", liveness: "crashed", interrupted: true },
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

function installFetch(tree, blocks) {
  global.fetch = vi.fn((url) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(tree) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(blocks) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

async function loadModule(nodes, blocks) {
  mountDom();
  installFetch({ nodes, total_roots: nodes.length }, blocks);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_e) { /* pas de localStorage */ }
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("un agent mort à 0 bloc ne s'affiche « terminé » sur aucune surface", () => {
  it("la vignette porte « planté » et sa description dit la MÊME chose", async () => {
    await loadModule([NODE_MORT], BLOCKS_MORT);

    const row = document.querySelector(`#conv-list .conv-item[data-key="${KEY}"]`);
    expect(row).toBeTruthy();
    const badge = row.querySelector(".badge");
    expect(badge.classList.contains("st-ko")).toBe(true);
    expect(badge.textContent).toContain("crashed");
    expect(badge.textContent).not.toContain("done");
    // La DESCRIPTION accessible de la carte (attribut title, lu par les lecteurs d'écran
    // et les snapshots d'accessibilité) : c'est elle qui annonçait « terminé · branche … ».
    expect(row.title).toContain("crashed");
    expect(row.title).not.toContain("done");
    // Le badge vert de succès n'existe nulle part sur cette carte.
    expect(row.querySelector(".st-ok")).toBeNull();
  });

  it("le panneau de détail ouvert dit « planté », pas « terminé »", async () => {
    await loadModule([NODE_MORT], BLOCKS_MORT);
    document.querySelector(`#conv-list .conv-item[data-key="${KEY}"]`).click();
    await flush();

    const panel = document.querySelector("#conv-panels .conv-panel:not([hidden])");
    expect(panel).toBeTruthy();
    const badge = panel.querySelector(".conv-panel-status .badge");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toContain("crashed");
    expect(badge.textContent).not.toContain("done");
  });

  it("un mort SUSPECTÉ mais non prouvé garde son point d'interrogation", async () => {
    // Vivacité `delivered` (clôture prouvée) mais 0 tour et rc non nul : on ne SAIT pas.
    // « mort ? » est la réponse honnête — et « terminé » reste interdit.
    const doute = { ...NODE_MORT, liveness: "delivered", interrupted: false };
    await loadModule([doute], { ...BLOCKS_MORT, status: { state: "finished", liveness: "delivered" } });

    const row = document.querySelector(`#conv-list .conv-item[data-key="${KEY}"]`);
    const badge = row.querySelector(".badge");
    expect(badge.textContent).toContain("dead?");
    expect(badge.textContent).not.toContain("done");
    expect(row.title).toContain("dead?");
    expect(row.title).not.toContain("done");
  });

  it("NON-RÉGRESSION : un agent qui a vraiment livré reste « terminé »", async () => {
    const livre = {
      ...NODE_MORT, state: "finished", turn_count: 7, returncode: 0,
      suspect_dead: false, liveness: "delivered", interrupted: false,
    };
    await loadModule([livre], {
      ...BLOCKS_MORT, status: { state: "finished", liveness: "delivered" },
    });

    const row = document.querySelector(`#conv-list .conv-item[data-key="${KEY}"]`);
    const badge = row.querySelector(".badge");
    expect(badge.classList.contains("st-ok")).toBe(true);
    expect(row.title).toContain("done");
    expect(row.title).not.toContain("crashed");
  });
});
