// Un dispatch part en `defer` : le serveur répond AVANT que l'agent existe, et le vrai node
// n'apparaît dans /api/agents/tree que quelques secondes plus tard (worktree, venv, spawn).
// Le seul refresh capable de le découvrir était le tick de 8 s — mesuré le 2026-08-03 sur le
// parc réel : node présent côté serveur à 8,6 s, affiché à 11,9 s. L'utilisateur voyait donc
// « Préparation… » plusieurs secondes de plus que nécessaire.
// Fix : après un dispatch déféré, on talonne /api/agents/tree à 1 s jusqu'à ce que le vrai
// node arrive, puis on rend la main au tick de 8 s.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../static/js/conversations.js",
);

const PROMPT = "réponds PONG";
const TICKET = "T1";
// Le tick spontané de la liste. Le talonnage doit être franchement plus rapide que lui,
// sinon il n'apporte rien.
const TICK_LISTE_MS = 8000;
const FENETRE_MS = 2600;

function mountDom() {
  document.body.innerHTML = `
    <div id="conv-list"></div>
    <div id="conv-tabs"></div>
    <div id="conv-panels"></div>
    <form id="conv-new-bar">
      <textarea id="conv-new-input"></textarea>
      <button id="conv-new-send" type="button"></button>
    </form>
    <div id="conv-new-error"></div>
  `;
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

// Le parc vu par le front : vide au début, puis l'agent réel apparaît quand `spawned` passe
// à vrai — exactement la chronologie d'un dispatch déféré.
function installFetch(etat) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/api/dispatch")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ticket_id: TICKET, deferred: true, routed: true }),
      });
    }
    if (u.includes("/api/agents/tree")) {
      etat.treeCalls += 1;
      const nodes = etat.spawned
        ? [{ key: "agent/abcdef123456", agent_id: "abcdef123456", ticket_id: TICKET,
             state: etat.state ?? "starting", phase: etat.phase ?? "demarrage",
             title: PROMPT, title_full: PROMPT }]
        : [];
      return Promise.resolve({
        ok: true, json: () => Promise.resolve({ nodes, total_roots: nodes.length }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

async function submitNewPrompt() {
  const input = document.getElementById("conv-new-input");
  input.value = PROMPT;
  input.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", shiftKey: false, bubbles: true }),
  );
  await flush();
}

async function loadModule(etat) {
  mountDom();
  installFetch(etat);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

describe("après un dispatch déféré, l'arrivée de l'agent est talonnée, pas attendue", () => {
  beforeEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("le parc est réinterrogé plusieurs fois dans les 2,6 s qui suivent l'envoi", async () => {
    const etat = { treeCalls: 0, spawned: false };
    await loadModule(etat);

    await submitNewPrompt();
    const apresEnvoi = etat.treeCalls;

    await new Promise((r) => setTimeout(r, FENETRE_MS));

    const pendantLaFenetre = etat.treeCalls - apresEnvoi;
    // Avec le seul tick de 8 s, cette fenêtre n'aurait produit AUCUNE interrogation.
    expect(FENETRE_MS).toBeLessThan(TICK_LISTE_MS);
    expect(pendantLaFenetre).toBeGreaterThanOrEqual(2);
  }, 15000);

  it("l'agent réel remplace le node optimiste dès qu'il apparaît, sans attendre le tick", async () => {
    const etat = { treeCalls: 0, spawned: false };
    await loadModule(etat);

    await submitNewPrompt();
    // Le serveur finit de provisionner : l'agent existe désormais.
    etat.spawned = true;

    await new Promise((r) => setTimeout(r, FENETRE_MS));
    await flush();

    const cles = [...document.querySelectorAll("[data-key]")]
      .map((el) => el.getAttribute("data-key"));
    expect(cles).toContain("agent/abcdef123456");
    expect(cles.filter((k) => k && k.startsWith("optimistic:"))).toEqual([]);
  }, 15000);

  // Le SECOND palier des ~10 s rapportés : l'agent existe déjà (« démarrage »), puis passe
  // à « attente du modèle ». Sans talonnage prolongé, cette 2e transition retombait sur le
  // tick de 8 s — mesuré le 2026-08-03 : connue du serveur à 35,5 s, affichée à 39,0 s.
  it("le talonnage continue tant que l'agent annonce une phase de démarrage", async () => {
    const etat = { treeCalls: 0, spawned: true, state: "running", phase: "attente_modele" };
    await loadModule(etat);

    await submitNewPrompt();
    await new Promise((r) => setTimeout(r, FENETRE_MS));
    const pendantLAttenteModele = etat.treeCalls;

    await new Promise((r) => setTimeout(r, 2000));

    expect(etat.treeCalls - pendantLAttenteModele).toBeGreaterThanOrEqual(2);
  }, 15000);

  it("le talonnage s'arrête quand l'agent n'a plus de phase à annoncer", async () => {
    // Ni phase, ni état de démarrage : l'agent travaille, l'écran n'a plus rien à rattraper.
    const etat = { treeCalls: 0, spawned: true, state: "running", phase: "" };
    await loadModule(etat);

    await submitNewPrompt();
    await new Promise((r) => setTimeout(r, FENETRE_MS));
    const apresReconciliation = etat.treeCalls;

    await new Promise((r) => setTimeout(r, 2000));

    // Plus de talonnage : au plus le tick spontané a pu passer une fois.
    expect(etat.treeCalls - apresReconciliation).toBeLessThanOrEqual(1);
  }, 15000);
});
