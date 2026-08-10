// Régression : le message user "implémente vazy" apparaissait 2× à l'écran alors
// que le backend (/api/sessions/<key>/blocks) ne l'émet qu'1× (bulle class="block user").
// Cause racine : poll() est une boucle setTimeout auto-réarmée SANS garde de réentrance.
// Deux poll(key) concurrents (ex: setTimeout en vol + appel manuel via retargetTab/
// reconcileOptimistic/reprise-question) fetchent le MÊME `after=nextIndex` (nextIndex
// n'est mis à jour qu'APRÈS l'await fetch) → les mêmes blocks sont insérés 2×.
// Fix : garde `if (entry.polling) return; entry.polling = true; … finally { =false }`.
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

// A deferred promise we can resolve manually to hold /blocks in flight while a
// SECOND poll() runs concurrently on the same nextIndex.
function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

const USER_BLOCK = {
  idx: 0,
  html: '<div class="block user pui-bubble pui-bubble--user"><p>implémente vazy</p></div>',
};

async function loadModule() {
  mountDom();
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

describe("poll() reentrancy — user message must not be inserted twice", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("two concurrent poll() on the same nextIndex insert the user bubble only ONCE", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    expect(typeof poll).toBe("function");
    expect(openTabs).toBeTruthy();

    const key = "agent/deadbeef";
    // Minimal open-tab entry mimicking newConversation()'s entry shape — only the
    // fields poll() touches. conv = the bubble container.
    const conv = document.createElement("div");
    document.getElementById("conv-panels").appendChild(conv);
    const status = document.createElement("div");
    const entry = {
      key,
      conv,
      status,
      nextIndex: 0,
      lastState: "running",
      partialActive: true,
      polling: false,
      poller: null,
      partialPoller: null,
    };
    openTabs.set(key, entry);

    // /blocks: first call is held in flight (deferred); it resolves with ONE user
    // block + total:1. Any later call returns empty (nextIndex already advanced).
    const d = deferred();
    let blocksCalls = 0;
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/blocks")) {
        blocksCalls += 1;
        if (blocksCalls === 1) {
          return d.promise.then(() => ({
            ok: true,
            json: () => Promise.resolve({ blocks: [USER_BLOCK], total: 1, status: { state: "running" } }),
          }));
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ blocks: [], total: 1, status: { state: "running" } }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    // Fire TWO poll() concurrently: both read entry.nextIndex === 0 and both would
    // fetch /blocks?after=0 → without the guard, both insert the same block.
    const p1 = poll(key);
    const p2 = poll(key);
    // Let the guard (and the fetch scheduling) settle before releasing the deferred.
    await flush();
    d.resolve();
    await Promise.all([p1, p2]);
    await flush();

    const userBubbles = [...conv.querySelectorAll(".block.user")].filter((el) =>
      el.textContent.includes("implémente vazy"),
    );
    expect(userBubbles.length).toBe(1);

    // Cleanup the self-rearmed setTimeout so it doesn't leak into other tests.
    clearTimeout(entry.poller);
    openTabs.delete(key);
  });
});
