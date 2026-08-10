// Test DOM (happy-dom + vitest) : bouton « ? » par bulle assistant.
// Vérifie que le clic sur .turn-context-btn fetch /turns/<n>/context (HTML riche)
// et injecte le HTML dans la modale. Fixture bulle assistant = markup EXACT de
// _assistant_block (message_view.py).
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

const SCRIPT = new URL("../../static/js/session.js", import.meta.url).pathname;
const KEY = "agent/abc123";

// Markup réel d'une bulle assistant produite par _assistant_block(message, turn_index=3).
const ASSISTANT_BUBBLE = `
<div class="block assistant pui-bubble pui-bubble--ai">
  <button type="button" class="turn-context-btn" data-turn="3" title="Voir le contexte de ce tour" aria-label="Voir le contexte de ce tour">?</button>
  <p>Réponse assistant</p>
</div>`;

// Réponse réelle attendue du endpoint /turns/<n>/context (render_context_diag_html) :
// du HTML complet avec CSS inline. Le front l'injecte tel quel via body.innerHTML.
const TURN_CONTEXT_HTML = `<style>.cd-wrap{}</style>
<div class="cd-wrap">
  <h1>Contexte envoyé au modèle — tour 3</h1>
  <div class="cd-meta">session abcd1234 · sonnet · input 1234 tok</div>
  <div class="cd-sec"><h2>Nouveau ce tour (delta ajouté au contexte)</h2>
    <div class="cd-item">Mon raisonnement du tour 3</div>
  </div>
</div>`;

function mountDom() {
  document.body.innerHTML = `
    <span id="s-badge"></span>
    <h1 id="s-title"></h1>
    <div id="s-meta"></div>
    <span id="diff-count"></span>
    <button id="kill-btn"></button>
    <div id="composer">
      <textarea id="composer-text"></textarea>
      <button id="composer-send"></button>
    </div>
    <div id="question-panel">
      <div id="question-text"></div>
      <div id="question-options"></div>
    </div>
    <div id="conv"></div>`;
}

let fetchCalls;

function installFetch() {
  fetchCalls = [];
  global.fetch = vi.fn(async (url, opts) => {
    fetchCalls.push({ url, opts });
    if (url.includes("/turns/") && url.includes("/context")) {
      return { ok: true, text: async () => TURN_CONTEXT_HTML };
    }
    // boot poll() /blocks : aucun nouveau bloc.
    if (url.includes("/blocks")) {
      return {
        ok: true,
        json: async () => ({ total: 0, blocks: [], status: { state: "cli" }, meta: {} }),
      };
    }
    return { ok: true, json: async () => ({}) };
  });
}

async function flush() {
  for (let i = 0; i < 40; i++) await Promise.resolve();
}

async function loadModule() {
  mountDom();
  installFetch();
  global.SESSION_KEY = KEY;
  globalThis.SESSION_KEY = KEY;
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("bouton ? contexte du tour", () => {
  it("clique le bouton → fetch /turns/<n>/context et injecte le HTML dans la modale", async () => {
    await loadModule();
    const conv = document.getElementById("conv");
    conv.insertAdjacentHTML("beforeend", ASSISTANT_BUBBLE);

    const btn = conv.querySelector(".turn-context-btn");
    expect(btn).not.toBeNull();
    expect(btn.dataset.turn).toBe("3");

    btn.click();
    await flush();

    const ctxCall = fetchCalls.find(
      (c) => c.url.includes(`/api/sessions/${KEY}/turns/3/context`)
    );
    expect(ctxCall).toBeTruthy();
    // Nouveau contrat : l'endpoint renvoie du HTML riche par défaut (delta/cached/tokens),
    // pas de ?json=1 — le front consomme response.text() et l'injecte via innerHTML.
    expect(ctxCall.url).not.toContain("json=1");

    const modal = document.getElementById("turn-context-modal");
    expect(modal).not.toBeNull();
    // Le HTML riche renvoyé par render_context_diag_html est injecté tel quel.
    expect(modal.textContent).toContain("Contexte envoyé au modèle — tour 3");
    expect(modal.textContent).toContain("Mon raisonnement du tour 3");
  });

  it("clic sur la croix ferme la modale", async () => {
    await loadModule();
    const conv = document.getElementById("conv");
    conv.insertAdjacentHTML("beforeend", ASSISTANT_BUBBLE);
    conv.querySelector(".turn-context-btn").click();
    await flush();

    expect(document.getElementById("turn-context-modal")).not.toBeNull();
    document.querySelector(".turn-context-close").click();
    expect(document.getElementById("turn-context-modal")).toBeNull();
  });

  it("Escape ferme la modale", async () => {
    await loadModule();
    const conv = document.getElementById("conv");
    conv.insertAdjacentHTML("beforeend", ASSISTANT_BUBBLE);
    conv.querySelector(".turn-context-btn").click();
    await flush();

    expect(document.getElementById("turn-context-modal")).not.toBeNull();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(document.getElementById("turn-context-modal")).toBeNull();
  });
});
