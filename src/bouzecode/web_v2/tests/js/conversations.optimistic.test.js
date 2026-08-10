// Regression: opening a ticket tab whose key is still `optimistic:...` (real
// session not yet reconciled) must NOT hammer /api/sessions/optimistic:.../blocks
// nor /partial (404 storm). poll()/pollPartial() carry a guard mirroring the
// `launching/` one: for optimistic keys they re-schedule softly WITHOUT fetching
// /api/sessions. reconcileOptimistic/retargetTab rebinds the tab to the real key.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../static/js/conversations.js",
);
const EMPTY_BLOCKS = { blocks: [], events: [] };

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

// installFetch(tree, calls, opts) — opts.dispatch overrides the /api/dispatch body.
// tree can be a static object OR a function () => object (to change the tree between
// the initial load and a later refreshList, e.g. once the real node has spawned).
function installFetch(tree, calls, opts = {}) {
  const dispatchBody = opts.dispatch ?? { ticket_id: "T1", deferred: true };
  const treeOf = () => (typeof tree === "function" ? tree() : tree);
  const fetchMock = vi.fn((url, init) => {
    calls.push(String(url));
    if (String(url).includes("/api/dispatch")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(dispatchBody) });
    }
    if (String(url).includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(treeOf()) });
    }
    if (String(url).includes("/blocks")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
    }
    if (String(url).includes("/partial")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock;
  return fetchMock;
}

// Drive newConversation via the composer: set the prompt then submit.
// The composer binds Enter (no shift) on #conv-new-input to newConversation().
async function submitNewPrompt(prompt) {
  const input = document.getElementById("conv-new-input");
  input.value = prompt;
  // Trigger BOTH bindings — the composer may fire newConversation() from an
  // Enter keydown on the textarea OR a click on the send button. Firing both
  // is robust to whichever the module actually wires (idempotent: a second
  // call with an already-consumed input is a cheap no-op).
  input.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", shiftKey: false, bubbles: true }),
  );
  const send = document.getElementById("conv-new-send");
  if (send) send.click();
  await flush();
}

function optKeys() {
  return [...document.querySelectorAll("[data-key]")]
    .map((el) => el.getAttribute("data-key"))
    .filter((k) => k && k.startsWith("optimistic:"));
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

async function loadModule(tree, calls, opts = {}) {
  mountDom();
  installFetch(tree, calls, opts);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

describe("optimistic tab polling guard", () => {
  beforeEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("does not fetch /api/sessions/optimistic:.../{blocks,partial}", async () => {
    const OPT_KEY = "optimistic:1784536859233-qd00gb";
    // Node carrying an optimistic key, WITHOUT _optimistic:true so renderList
    // does not filter it out (L737) — it renders with data-key = OPT_KEY.
    const tree = {
      nodes: [
        {
          key: OPT_KEY,
          agent_id: "qd00gb",
          state: "starting",
          title: "Nouveau ticket",
          title_full: "Nouveau ticket",
        },
      ],
    };
    const calls = [];
    await loadModule(tree, calls);

    const row = document.querySelector(`[data-key="${OPT_KEY}"]`);
    expect(row, "row for optimistic node must be rendered").toBeTruthy();

    row.click();
    await flush();

    const sessionCalls = calls.filter((u) => u.includes(`/api/sessions/${OPT_KEY}`));
    expect(sessionCalls).toEqual([]);
  });
});

describe("optimistic ticket lifecycle (RED against current code)", () => {
  beforeEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  // BUG-1: the ticket must ALWAYS survive — no 20s timeout may kill the optimistic
  // node. Current code arms optGuard = setTimeout(removeOptimistic, 20000): after
  // 20001ms the optimistic entry vanishes ("ticket lost in the limbo").
  it("does NOT drop the optimistic ticket after 20s", async () => {
    const calls = [];
    // Tree stays empty (defer: real node not spawned yet, > 20s).
    await loadModule({ nodes: [] }, calls);

    vi.useFakeTimers();
    await submitNewPrompt("mon prompt qui tarde a spawner");
    // Let the dispatch promise settle under fake timers.
    await vi.advanceTimersByTimeAsync(0);

    expect(optKeys().length, "optimistic node present right after submit").toBe(1);

    // Spawn takes longer than the old 20s guard.
    await vi.advanceTimersByTimeAsync(20001);

    expect(
      optKeys().length,
      "optimistic ticket must still be there after 20s (ticket always created)",
    ).toBe(1);
    vi.useRealTimers();
  });

  // BUG-2: on a dispatch error the typed prompt must be preserved in the composer,
  // not silently wiped. Current code clears / does not restore #conv-new-input.
  it("preserves the typed prompt when dispatch fails", async () => {
    const calls = [];
    await loadModule({ nodes: [] }, calls, { dispatch: { error: "boom" } });

    const PROMPT = "un prompt precieux a ne pas perdre";
    await submitNewPrompt(PROMPT);

    const input = document.getElementById("conv-new-input");
    expect(input.value, "prompt must remain in composer on dispatch error").toBe(PROMPT);
  });

  // BUG-3: once the real node spawns, the OPTIMISTIC tab must be retargeted to the
  // real key even if title_full differs (late generic "agent" title). Reconciliation
  // must key on ticket_id, not on strict title_full equality.
  it("retargets the optimistic tab to the real node by ticket_id", async () => {
    vi.useFakeTimers();
    const calls = [];
    let spawned = false;
    // Tree is empty until we flip `spawned`, then returns the real agent node
    // whose title_full is the generic "agent" (≠ prompt) but ticket_id matches.
    const tree = () =>
      spawned
        ? {
            nodes: [
              {
                key: "agent/abc",
                agent_id: "abc",
                ticket_id: "T1",
                state: "running",
                title: "agent",
                title_full: "agent",
              },
            ],
          }
        : { nodes: [] };
    await loadModule(tree, calls);

    await submitNewPrompt("prompt dont le titre serveur differe");
    await vi.advanceTimersByTimeAsync(0);
    // An optimistic tab is open on optimistic:...
    const optKey = optKeys()[0];
    expect(optKey, "optimistic node rendered after submit").toBeTruthy();
    const row = document.querySelector(`[data-key="${optKey}"]`);
    row.click();
    await vi.advanceTimersByTimeAsync(0);

    // Real node spawns; the periodic list refresh (~8s) refetches the tree,
    // reconcileOptimistic matches by ticket_id (T1) and retargets the tab.
    spawned = true;
    await vi.advanceTimersByTimeAsync(8001);
    await vi.advanceTimersByTimeAsync(0);

    // After reconciliation the tab must live under the REAL key, not the optimistic one.
    expect(
      document.querySelector('[data-key="agent/abc"]'),
      "real node must be present after spawn",
    ).toBeTruthy();
    expect(
      optKeys().length,
      "optimistic tab must have been retargeted (no optimistic key left)",
    ).toBe(0);
    vi.useRealTimers();
  });
});
