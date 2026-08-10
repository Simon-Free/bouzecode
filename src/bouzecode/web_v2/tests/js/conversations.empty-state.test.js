// Régression bug « onglet vide » (ticket « Suite du ticket… » resté vide 3 jours) :
// openTab crée le panneau puis poll()/pollPartial() ; quand /api/sessions/<key>/blocks
// renvoie blocks:[] (session jamais écrite : agent bloqué/mort) OU quand la key est
// optimistic: (fetch skippé), AUCUN contenu ni message n'était affiché →
// onglet visuellement VIDE, permanent si l'agent ne spawnait/n'écrivait jamais.
// Fix : poll() pose un placeholder .conv-empty-state reflétant l'état RÉEL, retiré dès
// le premier vrai bloc.
import { describe, it, expect, beforeEach, vi } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../static/js/conversations.js",
);

function mountDom() {
  document.body.innerHTML = `
    <div id="conv-list"></div>
    <div id="conv-tabs"></div>
    <div id="conv-panels"></div>
    <div id="tabs"></div>
    <div id="panels"></div>
    <form id="conv-new-bar">
      <textarea id="conv-new-input"></textarea>
      <button id="conv-new-send" type="button"></button>
    </form>
    <div id="conv-new-error"></div>
  `;
}

async function flush() {
  for (let i = 0; i < 50; i++) await Promise.resolve();
}

async function loadModule() {
  mountDom();
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

function makeEntry() {
  const conv = document.createElement("div");
  document.getElementById("conv-panels").appendChild(conv);
  const status = document.createElement("div");
  return {
    conv,
    status,
    nextIndex: 0,
    lastState: "cli",
    partialActive: true,
    polling: false,
    poller: null,
    partialPoller: null,
  };
}

function mockBlocks(state, blocks = [], total = 0) {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/blocks")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ blocks, total, status: { state } }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

describe("poll() empty-state placeholder — an opened tab is never a silent void", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("blocks:[] + state 'starting' shows « Démarrage de l'agent… »", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry();
    openTabs.set(key, entry);
    mockBlocks("starting");

    await poll(key);
    await flush();

    const ph = entry.conv.querySelector(".conv-empty-state");
    expect(ph).toBeTruthy();
    expect(ph.textContent).toBe("Démarrage de l'agent…");

    clearTimeout(entry.poller);
    openTabs.delete(key);
  });

  it("blocks:[] + terminal state shows « Aucun contenu (session vide ou introuvable). »", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "agent/deadbee2";
    const entry = makeEntry();
    openTabs.set(key, entry);
    mockBlocks("finished");

    await poll(key);
    await flush();

    const ph = entry.conv.querySelector(".conv-empty-state");
    expect(ph).toBeTruthy();
    expect(ph.textContent).toBe("Aucun contenu (session vide ou introuvable).");

    clearTimeout(entry.poller);
    openTabs.delete(key);
  });

  it("a real block clears the placeholder", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "agent/deadbee3";
    const entry = makeEntry();
    openTabs.set(key, entry);

    // 1er poll : vide → placeholder posé.
    mockBlocks("starting");
    await poll(key);
    await flush();
    expect(entry.conv.querySelector(".conv-empty-state")).toBeTruthy();

    // 2e poll : un vrai bloc arrive → placeholder retiré.
    mockBlocks("running", [
      { idx: 0, html: '<div class="block user">salut</div>' },
    ], 1);
    await poll(key);
    await flush();
    expect(entry.conv.querySelector(".conv-empty-state")).toBeFalsy();
    expect(entry.conv.querySelector(".block.user")).toBeTruthy();

    clearTimeout(entry.poller);
    openTabs.delete(key);
  });

  // Un onglet OPTIMISTE n'a encore AUCUN identifiant à interroger (le POST /api/dispatch
  // n'a pas rendu son ticket_id) : lui seul saute le fetch. Une clé `launching/<ticket>`,
  // elle, interroge désormais /blocks pour NOMMER la phase en cours — cf.
  // conversations.launching-phase.test.js : la phrase générique ci-dessous restait figée
  // pendant les ~20 s à ~55 s de `git worktree add`.
  it("an optimistic: tab (fetch skipped) shows « Préparation de la conversation… »", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "optimistic:1730000000000-some1";
    const entry = makeEntry();
    openTabs.set(key, entry);
    global.fetch = vi.fn(() =>
      Promise.reject(new Error("fetch must NOT be called for optimistic: keys")),
    );

    await poll(key);
    await flush();

    const ph = entry.conv.querySelector(".conv-empty-state");
    expect(ph).toBeTruthy();
    expect(ph.textContent).toBe("Préparation de la conversation…");
    expect(global.fetch).not.toHaveBeenCalled();

    clearTimeout(entry.poller);
    openTabs.delete(key);
  });
});
