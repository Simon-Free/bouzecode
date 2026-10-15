import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Page Agents — relectures concurrentes : une lecture partie AVANT un rechargement (Restaurer,
// relance du fil, archivage) ne doit jamais écraser ce que le rechargement a posé.

function res(status, body) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) });
}
const flush = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };
const user = (t, idx) => ({ idx, html: `<div class="block user pui-bubble pui-bubble--user"><p>${t}</p></div>` });

beforeEach(() => {
  vi.resetModules();
  document.body.innerHTML = `<div id="conv-tabs"></div><div id="conv-panels"><div class="conv-empty"></div></div><div id="conv-list"></div>`;
  try { localStorage.clear(); } catch (e) { console.warn(e); }
});
afterEach(() => { vi.useRealTimers(); });

describe("fil relancé pendant une lecture", () => {
  it("l'historique reste entier : la lecture en vol (after=N) est ignorée, le fil est relu depuis le début", async () => {
    const messages = [user("Premier message", 0), user("Deuxième message", 1), user("Troisième message", 2)];
    let retenue = null;
    global.fetch = vi.fn((url) => {
      if (!url.startsWith("/api/sessions/agent/a1/blocks")) return res(200, {});
      const after = Number(new URL(url, "http://x").searchParams.get("after") || 0);
      const lu = () => ({ blocks: messages.slice(after), total: messages.length, status: { state: "finished" }, queue: [] });
      //  La réponse est calculée quand elle part : la session a pu grandir entre-temps.
      if (after > 0 && !retenue) return new Promise((ok) => { retenue = () => ok(res(200, lu())); });
      return res(200, lu());
    });
    const { createThread } = await import("../../static/js/conversations/panel/thread.js");
    const pane = document.createElement("div");
    document.body.appendChild(pane);
    const entry = { key: "agent/a1", title: "A", active: true };
    const hooks = { onStatus() {}, onUnread() {}, retarget() {}, close() {}, repaintTab() {} };
    const thread = createThread(entry, pane, hooks);
    thread.start();
    await flush();
    expect(pane.querySelectorAll(".block.user")).toHaveLength(3);
    thread.poller.now();            // lecture incrémentale (after=2) retenue en vol
    await flush();
    expect(retenue).not.toBeNull();
    thread.restart();               // « Restaurer » : le fil repart de zéro
    messages.push(user("Quatrième message", 3));
    retenue();                      // la vieille lecture répond APRÈS le redémarrage
    await flush(20);
    const textes = [...pane.querySelectorAll(".block.user")].map((el) => el.textContent);
    expect(textes).toEqual(["Premier message", "Deuxième message", "Troisième message", "Quatrième message"]);
    thread.stop();
  });
});

describe("agent archivé", () => {
  it("une lecture de l'arbre partie avant l'archivage ne le fait pas réapparaître", async () => {
    const vivant = { key: "agent/a1", title: "À archiver", etat: "finished", status: { state: "finished" } };
    let archive = false;
    let retenue = null;
    global.fetch = vi.fn((url) => {
      if (url.startsWith("/api/agents/tree")) {
        const body = { nodes: archive ? [] : [vivant], total_roots: archive ? 0 : 1 };
        if (!archive && !retenue && global.retenirArbre) return new Promise((ok) => { retenue = () => ok(res(200, body)); });
        return res(200, body);
      }
      return res(200, {});
    });
    const { refreshTree } = await import("../../static/js/conversations/list.js");
    const { state } = await import("../../static/js/conversations/store.js");
    global.retenirArbre = true;
    const ancienne = refreshTree();          // lecture périodique partie AVANT l'archivage
    await flush();
    global.retenirArbre = false;
    archive = true;                          // POST /archive fait, puis rechargement frais
    await refreshTree();
    expect(state.nodes).toHaveLength(0);
    retenue();                               // la vieille lecture répond après
    await ancienne;
    expect(state.nodes.map((n) => n.key)).toEqual([]);
  });
});

describe("liste pendant un geste", () => {
  it("bouton relâché HORS de la fenêtre : la liste reprend ses mises à jour (fenêtre quittée)", async () => {
    let nodes = [];
    global.fetch = vi.fn((url) => res(200, url.startsWith("/api/agents/tree") ? { nodes, total_roots: nodes.length } : {}));
    const { startList, refreshTree } = await import("../../static/js/conversations/list.js");
    const poll = startList();
    await flush();
    poll.stop();
    const liste = document.getElementById("conv-list");
    liste.dispatchEvent(new Event("pointerdown", { bubbles: true }));   // geste commencé dans la liste…
    nodes = [{ key: "agent/n1", agent_id: "n1", title: "Arrivé pendant le geste", etat: "finished", state: "finished",
      started_at: "2026-09-26T00:00:00" }];
    await refreshTree();
    expect(liste.textContent).not.toContain("Arrivé pendant le geste");  // rendu différé pendant le geste
    window.dispatchEvent(new Event("blur"));                              // … relâché hors de la fenêtre
    await flush();
    expect(liste.textContent).toContain("Arrivé pendant le geste");
  });
});
