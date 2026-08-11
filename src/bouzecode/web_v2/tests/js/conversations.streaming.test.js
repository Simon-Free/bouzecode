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

// Build a minimal open-tab entry mimicking newConversation()'s shape — only the
// fields pollPartial()/poll() touch. conv = the bubble container inside a panel.
function makeEntry(key, state) {
  const conv = document.createElement("div");
  document.getElementById("conv-panels").appendChild(conv);
  return {
    key,
    conv,
    status: document.createElement("div"),
    nextIndex: 0,
    lastState: state,
    partialActive: true,
    polling: false,
    poller: null,
    partialPoller: null,
  };
}

describe("conversations.js streaming — .streaming-block in /conversations view", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("pollPartial creates a .streaming-block with the partial text while running", async () => {
    await loadModule();
    const { pollPartial, openTabs } = window.__convTest;
    expect(typeof pollPartial).toBe("function");

    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    global.fetch = vi.fn((url) => {
      if (String(url).includes("/partial")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ turn: 1, seq: 3, text: "hello wor" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await pollPartial(key);
    await flush();

    const sb = entry.conv.querySelector(".streaming-block");
    expect(sb).toBeTruthy();
    expect(sb.textContent).toBe("hello wor");

    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("updates the SAME .streaming-block when text grows (no duplicate)", async () => {
    await loadModule();
    const { pollPartial, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    let text = "hel";
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/partial")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ text }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await pollPartial(key);
    await flush();
    text = "hello world";
    await pollPartial(key);
    await flush();

    const blocks = entry.conv.querySelectorAll(".streaming-block");
    expect(blocks.length).toBe(1);
    expect(blocks[0].textContent).toBe("hello world");

    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("removes the .streaming-block when /partial returns text:null", async () => {
    await loadModule();
    const { pollPartial, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    let text = "streaming...";
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/partial")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ text }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await pollPartial(key);
    await flush();
    expect(entry.conv.querySelector(".streaming-block")).toBeTruthy();

    text = null;
    await pollPartial(key);
    await flush();
    expect(entry.conv.querySelector(".streaming-block")).toBeFalsy();

    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("poll() removes the .streaming-block before inserting the real block", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    // Seed a streaming-block as if pollPartial had created one.
    const sb = document.createElement("div");
    sb.className = "streaming-block";
    sb.textContent = "partial text";
    entry.conv.appendChild(sb);

    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/blocks")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            blocks: [{ idx: 0, html: '<div class="block assistant"><p>final</p></div>' }],
            total: 1,
            status: { state: "running" },
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ text: null }) });
    });

    await poll(key);
    await flush();

    expect(entry.conv.querySelector(".streaming-block")).toBeFalsy();
    expect(entry.conv.textContent).toContain("final");

    clearTimeout(entry.poller);
    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("phase=thinking → bloc repliable .streaming-thinking + label 'Thinking…'", async () => {
    await loadModule();
    const { pollPartial, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    global.fetch = vi.fn((url) => {
      if (String(url).includes("/partial")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ turn: 1, seq: 2, phase: "thinking", thinking: "Je réfléchis à la solution", text: "" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await pollPartial(key);
    await flush();

    const stk = entry.conv.querySelector(".streaming-thinking");
    expect(stk).toBeTruthy();
    expect(stk.classList.contains("collapsed")).toBe(false);
    expect(stk.querySelector(".st-label").textContent).toBe("Thinking…");
    expect(stk.querySelector(".st-body").textContent).toBe("Je réfléchis à la solution");
    // pas de bloc texte pendant le thinking pur
    expect(entry.conv.querySelector(".streaming-block")).toBeFalsy();

    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("bascule phase thinking→text → .streaming-thinking se referme (collapsed) + label 'Thinking'", async () => {
    await loadModule();
    const { pollPartial, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    let payload = { phase: "thinking", thinking: "mon raisonnement", text: "" };
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/partial")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await pollPartial(key);
    await flush();
    expect(entry.conv.querySelector(".streaming-thinking").classList.contains("collapsed")).toBe(false);

    payload = { phase: "text", thinking: "mon raisonnement", text: "La réponse est 42" };
    await pollPartial(key);
    await flush();

    const stk = entry.conv.querySelector(".streaming-thinking");
    expect(stk).toBeTruthy();
    expect(stk.classList.contains("collapsed")).toBe(true);
    expect(stk.querySelector(".st-label").textContent).toBe("Thinking");
    // le texte assistant s'affiche maintenant
    expect(entry.conv.querySelector(".streaming-block").textContent).toBe("La réponse est 42");

    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("texte contenant <tool_use name=X> → header .streaming-tool 'Tool running: X'", async () => {
    await loadModule();
    const { pollPartial, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    global.fetch = vi.fn((url) => {
      if (String(url).includes("/partial")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ phase: "text", thinking: "", text: 'Je corrige.\n<tool_use name="Edit" id="e1"><param' }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    await pollPartial(key);
    await flush();

    const stool = entry.conv.querySelector(".streaming-tool");
    expect(stool).toBeTruthy();
    expect(stool.querySelector(".st-tool-label").textContent).toBe("Tool running: Edit");

    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("sortie de running → purge le .streaming-tool orphelin (sablier figé)", async () => {
    await loadModule();
    const { pollPartial, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key, "running");
    openTabs.set(key, entry);

    let payload = { phase: "text", thinking: "", text: 'Je corrige.\n<tool_use name="Edit" id="e1"><param' };
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/partial")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    // 1er cycle running : le sablier apparaît.
    await pollPartial(key);
    await flush();
    expect(entry.conv.querySelector(".streaming-tool")).toBeTruthy();

    // L'agent quitte "running" (ex. tool terminé → état terminal/erreur). Le /partial
    // suivant peut encore renvoyer l'ancien texte, mais lastState n'est plus running :
    // pollPartial prend la branche d'arrêt et DOIT purger le sablier résiduel.
    entry.lastState = "error";
    await pollPartial(key);
    await flush();

    expect(entry.conv.querySelector(".streaming-tool")).toBeFalsy();
    expect(entry.conv.querySelector(".streaming-block")).toBeFalsy();
    expect(entry.partialActive).toBe(false);
    expect(entry.partialPoller).toBe(null);

    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });
});
