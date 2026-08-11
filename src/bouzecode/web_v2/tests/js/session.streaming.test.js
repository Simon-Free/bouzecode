// Streaming token-par-token dans la vue /sessions/<key> (session.js).
// Régression : cette vue n'appelait JAMAIS /partial → aucun `.streaming-block`
// ne s'affichait pendant la génération ("rien ne s'affiche"). Le fix ajoute
// pollPartial() (calqué sur conversations.js). Ces tests prouvent que le bloc
// provisoire apparaît, se met à jour, puis est retiré à l'arrivée du vrai bloc.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";
// session.js compose ses libellés avec `window.i18n` : hors gabarit, c'est à l'import ci-dessous
// d'installer le noyau et les dictionnaires. Sans lui, le script planterait dès le chargement.
import "../../static/js/i18n/index.js";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../static/js/session.js",
);

function mountDom() {
  document.body.innerHTML = `
    <div id="s-badge"></div>
    <div id="conv"></div>
    <button id="composer-send"></button>
    <textarea id="composer-text"></textarea>
    <button id="kill-btn"></button>
    <div id="composer"></div>
    <div id="question-panel"></div>
    <div id="question-text"></div>
    <div id="question-options"></div>
  `;
}

async function flush() {
  for (let i = 0; i < 50; i++) await Promise.resolve();
}

// fetch mock: route /partial → payload courant, tout le reste → 404-ish vide.
function mockFetch(partialPayload) {
  global.fetch = vi.fn(async (url) => {
    if (String(url).includes("/partial")) {
      return { ok: true, json: async () => partialPayload.current };
    }
    return { ok: true, json: async () => ({ blocks: [], total: 0, status: { state: "running" } }) };
  });
}

async function loadModule() {
  mountDom();
  vi.resetModules();
  globalThis.SESSION_KEY = "agent/deadbeef";
  globalThis.agentId = "deadbeef";
  // happy-dom: window global existe. Assure visibilityState "visible".
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

describe("session.js — streaming token-par-token (/partial → .streaming-block)", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    delete globalThis.SESSION_KEY;
    delete globalThis.agentId;
  });

  it("crée un .streaming-block avec le texte partiel quand l'agent génère (running)", async () => {
    const partialPayload = { current: { turn: 1, seq: 1, text: "Voici le début" } };
    mockFetch(partialPayload);
    await loadModule();

    const t = window.__sessionTest;
    t.setLastState("running");
    // Un seul cycle pollPartial (il se re-programme via setTimeout, on ne l'attend pas).
    await t.pollPartial();
    await flush();

    const sb = document.querySelector("#conv .streaming-block");
    expect(sb).not.toBeNull();
    expect(sb.textContent).toBe("Voici le début");
  });

  it("met à jour le MÊME bloc quand le texte grandit (pas de doublon)", async () => {
    const partialPayload = { current: { turn: 1, seq: 1, text: "Voici" } };
    mockFetch(partialPayload);
    await loadModule();

    const t = window.__sessionTest;
    t.setLastState("running");
    await t.pollPartial();
    await flush();
    partialPayload.current = { turn: 1, seq: 2, text: "Voici le texte complet" };
    await t.pollPartial();
    await flush();

    const blocks = document.querySelectorAll("#conv .streaming-block");
    expect(blocks.length).toBe(1);
    expect(blocks[0].textContent).toBe("Voici le texte complet");
  });

  it("retire le .streaming-block quand /partial renvoie {text:null}", async () => {
    const partialPayload = { current: { turn: 1, seq: 1, text: "Un texte" } };
    mockFetch(partialPayload);
    await loadModule();

    const t = window.__sessionTest;
    t.setLastState("running");
    await t.pollPartial();
    await flush();
    expect(document.querySelector("#conv .streaming-block")).not.toBeNull();

    partialPayload.current = { text: null };
    await t.pollPartial();
    await flush();
    expect(document.querySelector("#conv .streaming-block")).toBeNull();
  });

  it("poll() retire le .streaming-block avant d'insérer le vrai bloc (pas de doublon final)", async () => {
    const partialPayload = { current: { turn: 1, seq: 1, text: "Réponse en cours" } };
    mockFetch(partialPayload);
    await loadModule();

    const t = window.__sessionTest;
    t.setLastState("running");
    await t.pollPartial();
    await flush();
    expect(document.querySelector("#conv .streaming-block")).not.toBeNull();

    // Le vrai bloc message complet arrive via /blocks.
    global.fetch = vi.fn(async (url) => {
      if (String(url).includes("/partial")) {
        return { ok: true, json: async () => ({ text: null }) };
      }
      if (String(url).includes("/interrupted")) {
        return { ok: true, json: async () => ({ dismissed: true, items: [] }) };
      }
      return {
        ok: true,
        json: async () => ({
          blocks: [{ idx: 0, html: '<div class="block assistant">Réponse en cours et finale</div>' }],
          total: 1,
          status: { state: "finished" },
        }),
      };
    });
    await t.poll();
    await flush();

    // Le bloc provisoire a disparu, remplacé par le vrai bloc rendu.
    expect(document.querySelector("#conv .streaming-block")).toBeNull();
    expect(document.querySelector("#conv .block.assistant")).not.toBeNull();
  });

  it("phase=thinking → bloc repliable .streaming-thinking + label 'Thinking…'", async () => {
    const partialPayload = { current: { turn: 1, seq: 2, phase: "thinking", thinking: "Je réfléchis à la solution", text: "" } };
    mockFetch(partialPayload);
    await loadModule();

    const t = window.__sessionTest;
    t.setLastState("running");
    await t.pollPartial();
    await flush();

    const stk = document.querySelector("#conv .streaming-thinking");
    expect(stk).not.toBeNull();
    expect(stk.classList.contains("collapsed")).toBe(false);
    expect(stk.querySelector(".st-label").textContent).toBe("Thinking…");
    expect(stk.querySelector(".st-body").textContent).toBe("Je réfléchis à la solution");
    expect(document.querySelector("#conv .streaming-block")).toBeNull();
  });

  it("bascule phase thinking→text → .streaming-thinking se referme (collapsed) + label 'Thinking'", async () => {
    const partialPayload = { current: { phase: "thinking", thinking: "mon raisonnement", text: "" } };
    mockFetch(partialPayload);
    await loadModule();

    const t = window.__sessionTest;
    t.setLastState("running");
    await t.pollPartial();
    await flush();
    expect(document.querySelector("#conv .streaming-thinking").classList.contains("collapsed")).toBe(false);

    partialPayload.current = { phase: "text", thinking: "mon raisonnement", text: "La réponse est 42" };
    await t.pollPartial();
    await flush();

    const stk = document.querySelector("#conv .streaming-thinking");
    expect(stk).not.toBeNull();
    expect(stk.classList.contains("collapsed")).toBe(true);
    expect(stk.querySelector(".st-label").textContent).toBe("Thinking");
    expect(document.querySelector("#conv .streaming-block").textContent).toBe("La réponse est 42");
  });

  it("texte contenant <tool_use name=X> → header .streaming-tool 'Tool running: X'", async () => {
    const partialPayload = { current: { phase: "text", thinking: "", text: 'Je corrige.\n<tool_use name="Edit" id="e1"><param' } };
    mockFetch(partialPayload);
    await loadModule();

    const t = window.__sessionTest;
    t.setLastState("running");
    await t.pollPartial();
    await flush();

    const stool = document.querySelector("#conv .streaming-tool");
    expect(stool).not.toBeNull();
    expect(stool.querySelector(".st-tool-label").textContent).toBe("Tool running: Edit");
  });
});
