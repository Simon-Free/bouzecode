// Régression : après un follow-up (POST /api/agents/<id>/continue) qui répond 200,
// la RÉPONSE de l'agent n'apparaissait pas immédiatement — sendMsg ne relançait NI
// poll(key) NI pollPartial(key), donc le nouveau tour n'était streamé qu'au prochain
// tick SPONTANÉ du poller de la conversation (jusqu'à ~8s de latence visuelle pure).
// À l'inverse, le chemin LAUNCH relance explicitement poll/pollPartial via
// remapLaunchingTabs/retargetTab. Fix : sendMsg appelle poll(key)+pollPartial(key)
// dans la branche resp.ok, juste après avoir vidé l'input.
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

describe("sendMsg() — le follow-up relance immédiatement le streaming de la conversation", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("après POST /continue 200, poll (/blocks) ET pollPartial (/partial) repartent", async () => {
    await loadModule();
    const { sendMsg, openTabs } = window.__convTest;
    expect(typeof sendMsg).toBe("function");

    const key = "agent/cafebabe";
    const conv = document.createElement("div");
    document.getElementById("conv-panels").appendChild(conv);
    const status = document.createElement("div");
    const input = document.createElement("textarea");
    input.value = "continue vazy";
    const entry = {
      key,
      conv,
      status,
      input,
      inputError: document.createElement("div"),
      nextIndex: 0,
      lastState: "idle",
      partialActive: false,
      polling: false,
      poller: null,
      partialPoller: null,
    };
    openTabs.set(key, entry);

    const calls = { continue: 0, blocks: 0, partial: 0 };
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/continue")) {
        calls.continue += 1;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }
      if (u.includes("/blocks")) {
        calls.blocks += 1;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ blocks: [], total: 0, status: { state: "running" } }),
        });
      }
      if (u.includes("/partial")) {
        calls.partial += 1;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await sendMsg(key);
    await flush();

    expect(calls.continue).toBe(1);
    // Preuve que le streaming a redémarré immédiatement (sans attendre un tick).
    expect(calls.blocks).toBeGreaterThanOrEqual(1);
    expect(calls.partial).toBeGreaterThanOrEqual(1);
    // L'input a bien été vidé (branche resp.ok).
    expect(input.value).toBe("");

    clearTimeout(entry.poller);
    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });
});
