// Régression : les RÉPONSES PROPOSÉES à une question de l'agent étaient incliquables.
// `renderQuestion` faisait `questionOptions.replaceChildren()` à CHAQUE poll (1,5 s tant que
// l'agent attend) : un bouton détruit puis recréé entre le mousedown et le mouseup n'émet
// jamais de `click` (l'événement va au plus proche ancêtre COMMUN, le conteneur, sans
// listener). L'utilisateur cliquait sa réponse et il ne se passait RIEN — aucune requête,
// aucune erreur. Fix : le bloc question n'est reconstruit que lorsqu'il CHANGE.
import { describe, it, expect, beforeEach, vi } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../static/js/conversations.js",
);

const QUESTION = "Test A ou B ?";
const OPTIONS = [{ label: "A" }, { label: "B" }];

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

function makeEntry(key) {
  const div = () => document.createElement("div");
  const conv = div();
  document.getElementById("conv-panels").appendChild(conv);
  const question = div();
  return {
    key,
    conv,
    status: div(),
    input: document.createElement("textarea"),
    inputError: div(),
    question,
    questionText: div(),
    questionPlan: div(),
    questionOptions: div(),
    nextIndex: 0,
    lastState: "cli",
    questionSignature: "",
    partialActive: false,
    polling: false,
    poller: null,
    partialPoller: null,
  };
}

function stubFetch(counters, question) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/continue")) {
      counters.continue += 1;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    if (u.includes("/blocks")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          blocks: [],
          total: 0,
          status: { state: "awaiting_input", question, options: OPTIONS },
        }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

describe("boutons de réponse : stables tant que la question ne change pas", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("un bouton capturé au 1er poll survit aux polls suivants ET son clic part encore", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "agent/cafebabe";
    const entry = makeEntry(key);
    openTabs.set(key, entry);

    const counters = { continue: 0 };
    stubFetch(counters, QUESTION);

    await poll(key);
    await flush();
    const premierBouton = entry.questionOptions.firstElementChild;
    expect(premierBouton.textContent).toBe("A");

    // Trois polls de plus, exactement comme pendant l'attente réelle.
    for (let i = 0; i < 3; i++) { await poll(key); await flush(); }

    // Le bouton que l'utilisateur vise n'a pas été remplacé sous sa souris.
    expect(entry.questionOptions.firstElementChild).toBe(premierBouton);
    expect(entry.questionOptions.children.length).toBe(OPTIONS.length);

    // Et il répond toujours : le clic déclenche bien l'envoi de la réponse.
    premierBouton.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await flush();
    expect(counters.continue).toBe(1);
    expect(entry.input.value).toBe("");

    clearTimeout(entry.poller);
    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });

  it("une NOUVELLE question reconstruit bien le bloc (la signature change)", async () => {
    await loadModule();
    const { poll, openTabs } = window.__convTest;
    const key = "agent/deadbeef";
    const entry = makeEntry(key);
    openTabs.set(key, entry);

    const counters = { continue: 0 };
    stubFetch(counters, QUESTION);
    await poll(key);
    await flush();
    const ancienBouton = entry.questionOptions.firstElementChild;

    stubFetch(counters, "Une AUTRE question ?");
    await poll(key);
    await flush();

    expect(entry.questionText.textContent).toBe("Une AUTRE question ?");
    expect(entry.questionOptions.firstElementChild).not.toBe(ancienBouton);

    clearTimeout(entry.poller);
    clearTimeout(entry.partialPoller);
    openTabs.delete(key);
  });
});
