import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";

// LE DÉFAUT À TUER : la phase est cuite DANS le badge (elle prime sur l'état, cf. badge()),
// mais le moteur de rendu keyé ne recréait le badge que si l'ÉTAT ou `suspect_dead` avait
// changé. Or une phase s'ouvre ET SE FERME à état constant : « le modèle lit votre demande… »
// apparaît puis disparaît pendant que l'agent reste `running`. Le libellé restait donc figé
// sur la dernière phase vue — jusqu'à ce que l'état bouge, c'est-à-dire jusqu'à la fin de
// l'agent. Rendre la phase fraîche côté serveur ne servait à rien tant que le badge ne se
// repeignait pas.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(__dirname, "../../static/js/conversations.js");

const KEY = "agent/ab12cd34ef56";

const AGENT_EN_ATTENTE_DU_MODELE = {
  key: KEY, agent_id: "ab12cd34ef56", parent: null, state: "running", liveness: "running",
  turn_count: 1, title: "Déployer sur Azure", title_full: "Déployer la branche develop",
  started_at: "2026-08-04T08:43:09Z", phase: "attente_modele",
};

const BLOCKS = { blocks: [], total: 0, meta: { model: "opus" }, status: { state: "running" } };

let arbre;

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

function installFetch() {
  global.fetch = vi.fn((url) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(arbre) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(BLOCKS) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

async function loadModule(nodes) {
  mountDom();
  arbre = { nodes, total_roots: nodes.length };
  installFetch();
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

/** Sert un nouvel arbre puis laisse le tick de rafraîchissement (8 s) le consommer. */
async function servirPuisRafraichir(nodes) {
  arbre = { nodes, total_roots: nodes.length };
  await vi.advanceTimersByTimeAsync(8000);
  await flush();
}

function badge(key) {
  return document.querySelector(`#conv-list .conv-item[data-key="${key}"] .badge`);
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_e) { /* pas de localStorage */ }
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("le badge suit la phase, même quand l'état ne bouge pas", () => {
  it("la fin d'une phase efface son libellé alors que l'agent reste « en cours »", async () => {
    await loadModule([AGENT_EN_ATTENTE_DU_MODELE]);
    // Une phase force TOUJOURS son libellé, même en vignette compacte : un point de couleur
    // muet n'explique aucune attente.
    expect(badge(KEY).textContent).toContain("the model is reading your request");

    // Le modèle a répondu : le serveur n'annonce plus de phase, l'état reste `running`.
    await servirPuisRafraichir([{ ...AGENT_EN_ATTENTE_DU_MODELE, phase: "" }]);

    expect(badge(KEY).textContent).not.toContain("the model is reading your request");
    // Sans phase, la vignette redevient un point ; l'état se lit dans son infobulle.
    expect(badge(KEY).title).toBe("running");
  });

  it("une phase qui s'ouvre à état constant s'affiche tout de suite", async () => {
    await loadModule([{ ...AGENT_EN_ATTENTE_DU_MODELE, phase: "" }]);
    expect(badge(KEY).title).toBe("running");

    // Tour suivant : l'agent redemande au modèle, toujours `running`.
    await servirPuisRafraichir([AGENT_EN_ATTENTE_DU_MODELE]);

    expect(badge(KEY).textContent).toContain("the model is reading your request");
  });

  it("un état inchangé ET une phase inchangée ne recréent aucun badge", async () => {
    await loadModule([AGENT_EN_ATTENTE_DU_MODELE]);
    const avant = badge(KEY);

    await servirPuisRafraichir([AGENT_EN_ATTENTE_DU_MODELE]);

    // Identité DOM conservée : un badge recréé à chaque poll ferait rater les clics
    // qui tombent entre mousedown et mouseup (cf. le moteur de rendu keyé).
    expect(badge(KEY)).toBe(avant);
  });
});
