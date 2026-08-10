import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(__dirname, "../../static/js/conversations.js");
const PAGES_CSS = path.resolve(__dirname, "../../static/pages.css");

const EMPTY_BLOCKS = { blocks: [], running: false };

// Clés d'agent = "agent/<40 hex>". L'id complet est la clé sans le préfixe (40 car.),
// l'id court affiché est sa troncature à 8. Deux sous-agents du MÊME profil (mêmes
// titre/rôle) mais d'id distincts : c'est exactement le cas réel qui motivait la dédup.
const KEY_S1 = "agent/aaaa11112222333344445555666677778888";
const KEY_S2 = "agent/bbbb22223333444455556666777788889999";
const ID_S1_FULL = KEY_S1.replace(/^agent\//, "");
const ID_S2_FULL = KEY_S2.replace(/^agent\//, "");

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

const TREE = {
  nodes: [
    { key: "agent/mgr", parent: null, state: "running", run_kind: "manager", title: "Manager" },
    { key: KEY_S1, parent: "mgr", state: "running", run_kind: "subagent", title: "Validateur · python-coder" },
    { key: KEY_S2, parent: "mgr", state: "running", run_kind: "subagent", title: "Validateur · python-coder" },
  ],
};

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

// Le rendu de la liste (sidebar) et le 1er renderMeta sont pilotés par les PROMESSES
// des fetch (/api/agents/tree, /blocks), pas par setTimeout : draîner les microtasks
// suffit. (Avancer les fake timers ici relance en boucle le re-poll et casse le boot.)
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

// Ouvre le manager puis le sous-agent S1 en onglet et renvoie son .conv-panel.active
// (le panneau dont la ligne meta .conv-panel-status a été rendue par le 1er poll).
async function openS1Panel() {
  // Monte le DOM, importe le script réel, laisse la sidebar se peupler (fetch tree).
  await loadModule(TREE);
  // La sidebar rend le manager ET ses sous-agents comme des .conv-item (les enfants
  // portent .conv-child dans .conv-children, hidden). On ouvre DIRECTEMENT le sous-agent
  // S1 en onglet via son data-key — pas de .conv-sub-chip dans ce flux de liste.
  const itemS1 = document.querySelector(`#conv-list .conv-item[data-key="${KEY_S1}"]`);
  expect(itemS1).toBeTruthy();
  itemS1.click();
  await flush();
  // activateTab ne pose .active QUE sur l'onglet ; le panneau visible est le seul
  // sans attribut hidden (les autres sont panel.hidden=true).
  const panel = document.querySelector("#conv-panels .conv-panel:not([hidden])");
  expect(panel).toBeTruthy();
  return panel;
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_e) { /* jsdom-less env */ }
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("switch Conv/Récap intégré à la ligne meta + id dédupliqué", () => {
  // (a) Le switch vit DANS la ligne meta, plus sur une ligne dédiée du panneau.
  it("(a) .conv-view-switch est enfant de .conv-panel-status (pas une ligne dédiée)", async () => {
    const panel = await openS1Panel();
    const status = panel.querySelector(".conv-panel-status");
    expect(status).toBeTruthy();
    // Enfant DIRECT de la ligne meta (parentElement === status, sans :scope que
    // happy-dom gère mal). Le switch existe et son parent est bien la ligne meta.
    const sw = status.querySelector(".conv-view-switch");
    expect(sw).toBeTruthy();
    expect(sw.parentElement).toBe(status);
    // Et PLUS aucune .conv-view-switch en enfant direct du panneau (l'ancienne
    // ligne dédiée n'existe plus) : tout switch trouvé a pour parent la ligne meta.
    const switches = [...panel.querySelectorAll(".conv-view-switch")];
    expect(switches.length).toBeGreaterThan(0);
    expect(switches.every((s) => s.parentElement !== panel)).toBe(true);
  });

  // (b) Le bouton actif porte un style DISTINCT et mesurable (classe .active + règle CSS
  // au fond accent contrasté). happy-dom ne calcule pas le CSS → on assert la classe DOM
  // ET la présence de la règle dans pages.css (le contraste pixel est prouvé par screenshot).
  it("(b) le bouton actif porte .active et une règle CSS distincte (fond accent)", async () => {
    const panel = await openS1Panel();
    const sw = panel.querySelector(".conv-panel-status .conv-view-switch");
    const btns = [...sw.querySelectorAll(".conv-view-btn")];
    expect(btns.length).toBe(2);
    const active = btns.filter((b) => b.classList.contains("active"));
    expect(active.length).toBe(1);
    expect(active[0].dataset.view).toBe("conv"); // Conversation actif par défaut
    // Récap grisé tant que la session tourne (running:false ⇒ pas terminé côté état "cli").
    const recapBtn = btns.find((b) => b.dataset.view === "recap");
    expect(recapBtn.disabled).toBe(true);
    // La règle contrastante existe bien dans la feuille de style servie.
    const css = fs.readFileSync(PAGES_CSS, "utf8");
    expect(css).toMatch(/\.conv-view-btn\.active\s*\{[^}]*background:\s*var\(--accent\)/);
  });

  // (c) L'id court n'apparaît qu'UNE fois dans le panneau, et plus du tout dans l'onglet.
  it("(c) l'id court apparaît 1 seule fois (ligne meta) et jamais dans l'onglet", async () => {
    const panel = await openS1Panel();
    const metaIds = panel.querySelectorAll(".conv-meta-id");
    expect(metaIds.length).toBe(1);
    expect(metaIds[0].textContent).toBe("#" + ID_S1_FULL.slice(0, 8));
    // Plus aucun chip d'id dans la barre d'onglets.
    expect(document.querySelectorAll("#conv-tabs .conv-tab-id").length).toBe(0);
  });

  // (d) Clic sur l'id court → le presse-papier reçoit l'id COMPLET (40 hex), pas la troncature.
  it("(d) clic sur l'id court copie l'id COMPLET dans le presse-papier", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    const panel = await openS1Panel();
    const chip = panel.querySelector(".conv-meta-id");
    expect(chip).toBeTruthy();
    expect(chip.textContent).toBe("#" + ID_S1_FULL.slice(0, 8));

    chip.click();
    await flush();

    expect(writeText).toHaveBeenCalledWith(ID_S1_FULL);
    // Feedback furtif appliqué.
    expect(chip.classList.contains("is-copied")).toBe(true);
  });
});
