// Vitest: keyword search panel in the Conversations tab (render + click navigation).
import { beforeEach, describe, expect, it, vi } from "vitest";

const SCRIPT = "../../static/js/conversations.js";

const TREE = { nodes: [], version: 1 };

function mountDom() {
  document.body.innerHTML = `
    <aside><div id="conv-list"></div></aside>
    <form id="conv-new-bar"><textarea id="conv-new-input"></textarea>
      <button id="conv-new-send" type="submit"></button></form>
    <div class="conv-agent-bar">
      <button id="conv-agent-toggle" type="button" aria-expanded="false" aria-controls="conv-agent-panel">
        <span id="conv-agent-value"></span></button>
      <div id="conv-agent-panel" role="radiogroup" hidden></div>
      <button id="conv-project-toggle" type="button" aria-expanded="false" aria-controls="conv-project-panel">
        <span id="conv-project-value"></span></button>
      <div id="conv-project-panel" role="radiogroup" hidden></div>
      <div id="conv-project-suggestions" hidden></div>
    </div>
    <div id="conv-new-error"></div>
    <div id="conv-tabs"></div>
    <div id="conv-panels"><div class="conv-empty">Vide</div></div>
  `;
}

let searchResults = { results: [] };

function installFetch() {
  const fetchMock = vi.fn(async (url) => {
    const u = String(url);
    if (u.includes("/api/search")) {
      return { ok: true, json: async () => searchResults };
    }
    if (u.includes("/api/agents/tree")) {
      return { ok: true, json: async () => TREE };
    }
    return { ok: true, json: async () => ({}) };
  });
  globalThis.fetch = fetchMock;
  return fetchMock;
}

function flush() {
  return new Promise((r) => setTimeout(r, 0));
}

async function loadModule() {
  mountDom();
  installFetch();
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

function enterQuery(text) {
  const input = document.getElementById("conv-search-input");
  input.value = text;
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
}

describe("conversations keyword search", () => {
  beforeEach(() => {
    searchResults = { results: [] };
  });

  it("inserts the search box before the conversation list", async () => {
    await loadModule();
    const box = document.querySelector(".conv-search");
    expect(box).toBeTruthy();
    expect(document.getElementById("conv-search-input")).toBeTruthy();
  });

  it("renders results with title, role and highlighted snippet", async () => {
    searchResults = {
      results: [{
        agent_id: "agent-1",
        key: "agent/agent-1",
        ticket_title: "Ticket about bananas",
        matches: [
          { role: "user", snippet: "parle de bananas ici" },
          { role: "final_answer", snippet: "les bananas sont livrées" },
        ],
      }],
    };
    await loadModule();
    enterQuery("bananas");
    await flush();

    const items = document.querySelectorAll(".conv-search-item");
    expect(items.length).toBe(1);
    expect(items[0].querySelector(".conv-search-title").textContent)
      .toBe("Ticket about bananas");
    const roles = [...items[0].querySelectorAll(".conv-search-role")]
      .map((n) => n.textContent);
    expect(roles).toEqual(["vous", "réponse"]);
    const marks = items[0].querySelectorAll("mark");
    expect(marks.length).toBe(2);
    expect(marks[0].textContent).toBe("bananas");
  });

  it("shows an empty state when there is no result", async () => {
    searchResults = { results: [] };
    await loadModule();
    enterQuery("nothing");
    await flush();
    expect(document.querySelector(".conv-search-results").textContent)
      .toContain("Aucun résultat");
  });

  it("opens the agent conversation on result click", async () => {
    searchResults = {
      results: [{
        agent_id: "agent-1",
        key: "agent/agent-1",
        ticket_title: "Ticket about bananas",
        matches: [{ role: "user", snippet: "parle de bananas" }],
      }],
    };
    await loadModule();
    enterQuery("bananas");
    await flush();
    document.querySelector(".conv-search-item").click();
    await flush();
    const tabs = document.querySelectorAll("#conv-tabs .conv-tab");
    expect(tabs.length).toBe(1);
  });
});
