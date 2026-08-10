// Le corps d'un onglet de LANCEMENT (clé `launching/<ticket>`) affichait une phrase FIGÉE,
// écrite en dur — « Préparation de la conversation… » — identique de la première à la
// cinquante-cinquième seconde. Or `git worktree add` coûte 1,1 s à chaud mais 20,6 s à froid
// (mesuré sur ce poste, 1431 fichiers scannés par l'antivirus) et jusqu'à ~55 s sous charge :
// l'utilisateur attendait sans savoir pourquoi, ni si ça avançait.
// Fix : poll() interroge /blocks pour cette clé aussi (le backend y sert désormais la phase
// du lancement) et rend le libellé du SERVEUR — mêmes mots que la sidebar et que l'API.
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

// Ce que sert réellement routes/sessions._launching_blocks pour une clé `launching/<id>`.
function mockLaunchingBlocks(status, ok = true) {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/blocks")) {
      return Promise.resolve({
        ok,
        json: () => Promise.resolve({ blocks: [], total: 0, status }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

async function texteAffiche(status, ok = true) {
  const { poll, openTabs } = window.__convTest;
  const key = "launching/tkt00001";
  const entry = makeEntry();
  openTabs.set(key, entry);
  mockLaunchingBlocks(status, ok);
  await poll(key);
  await flush();
  const texte = entry.conv.querySelector(".conv-empty-state").textContent;
  clearTimeout(entry.poller);
  clearTimeout(entry.partialPoller);
  openTabs.delete(key);
  return texte;
}

describe("poll() — un onglet de lancement nomme la phase au lieu d'une phrase figée", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("annonce la création du worktree et sa branche de base", async () => {
    await loadModule();
    expect(
      await texteAffiche({
        state: "provisioning",
        phase: "provisioning_worktree",
        phase_label: "création du worktree",
        phase_detail: "depuis develop",
      }),
    ).toBe("Création du worktree… — depuis develop");
  });

  it("annonce l'installation de l'environnement uv", async () => {
    await loadModule();
    expect(
      await texteAffiche({
        state: "provisioning",
        phase: "syncing_venv",
        phase_label: "installation de l'environnement uv",
      }),
    ).toBe("Installation de l'environnement uv…");
  });

  it("dit qu'on en est au 2e essai quand le premier `git worktree add` a expiré", async () => {
    await loadModule();
    // Sans ce détail, un provisionnement qui rejoue était indistinguable d'un serveur bloqué.
    expect(
      await texteAffiche({
        state: "provisioning",
        phase: "provisioning_worktree",
        phase_label: "création du worktree",
        phase_detail: "essai 1/3 échoué (délai dépassé) — nouvelle tentative",
      }),
    ).toContain("essai 1/3 échoué");
  });

  it("retombe sur la phrase générique quand le serveur n'a plus de phase à servir", async () => {
    await loadModule();
    // 404 : l'agent vient de naître, l'onglet va basculer sur `agent/<id>`.
    expect(await texteAffiche({}, false)).toBe("Préparation de la conversation…");
  });

  it("un onglet OPTIMISTE, lui, n'a aucun ticket à interroger et reste générique", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "optimistic:1730000000000-abc123";
    const entry = makeEntry();
    openTabs.set(key, entry);
    global.fetch = vi.fn(() => Promise.reject(new Error("aucun appel attendu")));

    await poll(key);
    await flush();

    expect(entry.conv.querySelector(".conv-empty-state").textContent)
      .toBe("Préparation de la conversation…");
    expect(global.fetch).not.toHaveBeenCalled();
    clearTimeout(entry.poller);
    openTabs.delete(key);
  });
});
