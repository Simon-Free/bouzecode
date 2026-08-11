// Le corps d'une conversation qui n'a encore RIEN à montrer doit dire où en est l'agent,
// et le dire VITE. La phase (« démarrage », « attente du modèle ») est servie par
// /api/sessions/<key>/blocks, donc au rythme de poll() — 1,5 s. Elle était servie et JETÉE :
// le corps ne lisait que `status.state`, si bien que ces libellés n'arrivaient que par
// /api/agents/tree, poll à 8 s derrière un cache de 10 s. Mesuré le 2026-08-03 sur le parc
// réel : phase connue du serveur à 8,6 s, affichée à 11,9 s.
// Fix : poll() lit `status.phase` et la fait primer sur `status.state`, comme le badge.
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
  return {
    conv,
    status: document.createElement("div"),
    nextIndex: 0,
    lastState: "cli",
    partialActive: true,
    polling: false,
    poller: null,
    partialPoller: null,
  };
}

// /blocks vide, avec l'état ET la phase que sert réellement le backend.
function mockBlocks(state, phase) {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/blocks")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({ blocks: [], total: 0, status: { state, phase } }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

async function texteAffiche(key, state, phase) {
  const { poll, openTabs } = window.__convTest;
  const entry = makeEntry();
  openTabs.set(key, entry);
  mockBlocks(state, phase);
  await poll(key);
  await flush();
  const texte = entry.conv.querySelector(".conv-empty-state").textContent;
  clearTimeout(entry.poller);
  clearTimeout(entry.partialPoller);
  openTabs.delete(key);
  return texte;
}

describe("poll() — la phase servie par /blocks dit où en est l'agent, à 1,5 s", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("phase 'demarrage' annonce le démarrage de l'agent", async () => {
    await loadModule();
    expect(await texteAffiche("agent/aaa00001", "starting", "demarrage"))
      .toBe("Starting the agent…");
  });

  it("phase 'attente_modele' explique que le modèle lit la demande", async () => {
    await loadModule();
    // Le cas qui manquait : l'état est « running » (donc muet), seule la phase informe.
    expect(await texteAffiche("agent/aaa00002", "running", "attente_modele"))
      .toBe("The model is reading your request…");
  });

  it("sans phase, l'état reprend la main — « running » reste une attente indéterminée", async () => {
    await loadModule();
    expect(await texteAffiche("agent/aaa00003", "running", ""))
      .toBe("Waiting for content…");
  });

  it("sans phase, un état terminal dit qu'il n'y a rien à montrer", async () => {
    await loadModule();
    expect(await texteAffiche("agent/aaa00004", "finished", ""))
      .toBe("No content (session empty or not found).");
  });

  it("une phase inconnue du front ne masque pas l'état", async () => {
    await loadModule();
    expect(await texteAffiche("agent/aaa00005", "starting", "phase_du_futur"))
      .toBe("Starting the agent…");
  });
});
