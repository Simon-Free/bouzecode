import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Test DOM (happy-dom) du rendu Récap side-by-side MAISON (remplace le <pre> +/-
// unifié + Monaco). Fixture DÉRIVÉE DU RÉEL : payload /recap capturé sur une vraie
// session (agent/c0ffee01), avec original/modified non vides (\r\n) — voir
// __fixtures__/recap_payload_real.json. On joue le VRAI flux client : montage du
// module → clic pastille Récap sidebar → le <details> du diff se déplie et rend
// deux colonnes ancien|nouveau surlignées + coloration syntaxique.
//
// NB : ce test vérifie la LOGIQUE DOM (bons nœuds/classes présents). Le rendu
// VISUEL (couleurs, layout 2 colonnes réel) est prouvé par screenshot navigateur,
// et le BOOT sans erreur par le smoke Playwright §0 — happy-dom ne voit pas le CSS.

const SCRIPT = "../../static/js/conversations.js";
const HERE = dirname(fileURLToPath(import.meta.url));
const RECAP_REAL = JSON.parse(
  readFileSync(join(HERE, "__fixtures__", "recap_payload_real.json"), "utf-8")
);

const TREE = {
  nodes: [
    { key: "agent/mgr-1", parent: null, state: "finished", title: "Manager 1", branch: "develop", has_recap: true },
  ],
};

function mountDom() {
  document.body.innerHTML = `
    <div class="conv-main">
      <aside><div id="conv-list"></div></aside>
      <form id="conv-new-bar"><textarea id="conv-new-input"></textarea>
        <button id="conv-new-send" type="submit"></button></form>
      <div id="conv-new-error"></div>
      <div id="conv-tabs"></div>
      <div id="conv-panels"><div class="conv-empty">Vide</div></div>
    </div>
  `;
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

function installFetch(recapPayload, recapCalls) {
  const fetchMock = vi.fn((url) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
    }
    if (url.includes("/recap")) {
      recapCalls.push(url);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(recapPayload) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ blocks: [], total: 0, status: { state: "finished" }, meta: {} }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock;
  return fetchMock;
}

async function mountTree(recapPayload, recapCalls) {
  mountDom();
  installFetch(recapPayload, recapCalls);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

async function clickRecapPill() {
  document.querySelector("#conv-list .conv-recap-pill").click();
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_) {}
  // Le code récap maison n'utilise plus loadMonaco, mais on stube quand même au
  // cas où un autre chemin du module y touche — défaut : Monaco indisponible.
  globalThis.loadMonaco = vi.fn(() => Promise.resolve(null));
  globalThis.monacoLanguage = () => "python";
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("Récap — diff side-by-side maison", () => {
  it("rend deux colonnes ancien|nouveau au lieu du <pre> +/- unifié", async () => {
    const recapCalls = [];
    await mountTree(RECAP_REAL, recapCalls);
    await clickRecapPill();

    const panels = document.querySelector("#conv-panels");

    // La grille side-by-side est présente (au moins une par diff déplié).
    const grids = panels.querySelectorAll(".recap-sxs");
    expect(grids.length).toBeGreaterThan(0);

    // Chaque grille est une suite de .sxs-row.
    const rows = panels.querySelectorAll(".recap-sxs .sxs-row");
    expect(rows.length).toBeGreaterThan(0);

    // Le fichier modifié (diff#1) produit des lignes supprimées ET ajoutées.
    expect(panels.querySelectorAll(".sxs-row.sxs-del").length).toBeGreaterThan(0);
    expect(panels.querySelectorAll(".sxs-row.sxs-add").length).toBeGreaterThan(0);

    // Cellule vide (filler) en face d'une ligne ajoutée/supprimée.
    expect(panels.querySelectorAll(".sxs-code.sxs-empty").length).toBeGreaterThan(0);
  });

  it("colore la syntaxe : mots-clés / chaînes détectés", async () => {
    const recapCalls = [];
    await mountTree(RECAP_REAL, recapCalls);
    await clickRecapPill();

    const panels = document.querySelector("#conv-panels");
    // diff#2 (test neuf) contient `from`, `import`, `def`, `True` → mots-clés python.
    expect(panels.querySelectorAll(".recap-sxs .tok-kw").length).toBeGreaterThan(0);
    // Des chaînes ("work", "coder-99", …) → tokens string.
    expect(panels.querySelectorAll(".recap-sxs .tok-str").length).toBeGreaterThan(0);
  });

  it("N'utilise PLUS le rendu <pre> +/- unifié quand original/modified existent", async () => {
    const recapCalls = [];
    await mountTree(RECAP_REAL, recapCalls);
    await clickRecapPill();

    const panels = document.querySelector("#conv-panels");
    // Plus aucun <pre class="recap-diff-body"> ni ligne .diff-add/.diff-del unifiée.
    expect(panels.querySelectorAll("pre.recap-diff-body").length).toBe(0);
    expect(panels.querySelectorAll(".recap-diff-body .diff-add").length).toBe(0);
    expect(panels.querySelectorAll(".recap-diff-body .diff-del").length).toBe(0);
  });

  it("aligne correctement le fichier neuf (original vide) : que des lignes ajoutées", async () => {
    const recapCalls = [];
    await mountTree(RECAP_REAL, recapCalls);
    await clickRecapPill();

    const panels = document.querySelector("#conv-panels");
    const grids = panels.querySelectorAll(".recap-sxs");
    // La dernière grille correspond au diff#2 (test neuf, section "tests").
    const lastGrid = grids[grids.length - 1];
    const adds = lastGrid.querySelectorAll(".sxs-row.sxs-add").length;
    const dels = lastGrid.querySelectorAll(".sxs-row.sxs-del").length;
    expect(adds).toBeGreaterThan(0);
    expect(dels).toBe(0);
  });
});
