import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Chemin du VRAI script servi par Flask.
const SCRIPT = "../../static/js/conversations.js";

// Arbre /api/agents/tree : 1 manager racine + 1 subagent enfant + 1 autre racine.
const TREE = {
  nodes: [
    { key: "agent/mgr-1", parent: null, state: "running", title: "Manager 1", branch: "develop" },
    { key: "agent/mgr-2", parent: null, state: "cli", title: "Manager 2" },
    { key: "agent/sub-a", parent: "mgr-1", state: "running", title: "Subagent A" },
  ],
};

// Reponse /blocks : vide mais bien formee (poll s'en sert).
const EMPTY_BLOCKS = { blocks: [], total: 0, status: { state: "cli" }, meta: {} };

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

// Fixtures projet/dispatch, reconfigurables par test (voir describe "sélecteur projet").
const PROJECTS_FIXTURE = { projects: [
  { name: "Demo App", slug: "demo-app", path: "/x/demo-app" },
  { name: "OSS", slug: "bouzecode_oss", path: "/x/oss" },
] };
const TYPOLOGIES_FIXTURE = { typologies: [{ name: "default" }] };
let PROJECTS_RESPONSE = PROJECTS_FIXTURE;
let DISPATCH_RESPONSE = { key: "conv-1" };

// fetch mocke : route selon l'URL. tree() renvoie l'arbre passe.
function installFetch(tree = TREE) {
  const fetchMock = vi.fn((url, opts) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(tree) });
    }
    if (url.includes("/api/typologies")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(TYPOLOGIES_FIXTURE) });
    }
    if (url.includes("/api/projects")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(PROJECTS_RESPONSE) });
    }
    if (url.includes("/api/dispatch")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(DISPATCH_RESPONSE) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock;
  return fetchMock;
}

// Lit le body JSON du dernier POST /api/dispatch capturé par le fetchMock.
function dispatchBody(fetchMock) {
  const call = [...fetchMock.mock.calls].reverse().find((c) => String(c[0]).includes("/api/dispatch"));
  if (!call || !call[1] || !call[1].body) return null;
  return JSON.parse(call[1].body);
}

// Remplit l'input et soumet la barre nouvelle conversation.
async function submitNew(prompt = "fais un truc") {
  const input = document.getElementById("conv-new-input");
  const form = document.getElementById("conv-new-bar");
  input.value = prompt;
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await flush();
}

// Le module lance refreshList() (async, 2 awaits) au top-level ; on vide la
// file de microtasks pour laisser les fetch mockes se resoudre.
async function flush() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

// Racines réelles toutes sections (needinput/running/finished), hors flats ::flat.
// Les 3 wrappers .conv-section-* sont enfants directs de #conv-list ; leurs .conv-group
// directs contiennent les racines. On exclut les entrées flat (::flat) et les enfants.
function rootItems() {
  return [...document.querySelectorAll("#conv-list > div > .conv-group > .conv-item")]
    .filter((el) => !(el.dataset.key || "").endsWith("::flat"));
}
function rootTitlesStr() {
  return rootItems().map((el) => el.textContent).join(" ");
}

// Import frais du module a chaque test (les effets top-level doivent rejouer).
async function loadModule(tree = TREE) {
  mountDom();
  const fetchMock = installFetch(tree);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
  return fetchMock;
}

beforeEach(() => {
  vi.useFakeTimers(); // neutralise setInterval(refreshList,8000) + setTimeout poll
  try { localStorage.clear(); } catch (_) {} // isole la persistance bz.conv.expanded/collapsed entre tests
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("conversations.js — sidebar (filtre des racines + sections par état)", () => {
  it("affiche les racines dans leur section d'état ; le subagent running N'est PAS à la racine, seulement imbriqué", async () => {
    await loadModule();
    // TREE : mgr-1 running (racine), mgr-2 cli (racine), sub-a running (enfant mgr-1).
    const roots = rootItems();
    // 2 vraies racines (hors flats).
    expect(roots.length).toBe(2);
    const titles = roots.map((el) => el.textContent).join(" ");
    expect(titles).toContain("Manager 1");
    expect(titles).toContain("Manager 2");
    // mgr-1 (running) -> section "● En cours".
    expect(document.querySelector('.conv-section-running [data-key="agent/mgr-1"]')).not.toBeNull();
    // mgr-2 (cli) -> section "Terminés".
    expect(document.querySelector('.conv-section-finished [data-key="agent/mgr-2"]')).not.toBeNull();
    // NOUVELLE règle : sub-a running ne remonte PLUS à la racine "● En cours" (aucune entrée flat).
    expect(document.querySelector('[data-key="agent/sub-a::flat"]')).toBeNull();
    expect(document.querySelector(".conv-flat-parent")).toBeNull();
    // sub-a reste UNIQUEMENT imbriqué sous mgr-1 (bloc enfants), REPLIÉ par défaut (running seul n'auto-expand pas).
    const group = document.querySelector('.conv-section-running [data-key="agent/mgr-1"]').closest(".conv-group");
    const childrenBox = group.querySelector(".conv-children");
    expect(childrenBox).not.toBeNull();
    expect(childrenBox.hidden).toBe(true);
    expect(childrenBox.textContent).toContain("Subagent A");
  });

  it("toggle bidirectionnel : la ligne header .conv-toggle (frère du bloc enfants) replie/déplie ; enfant cliquable", async () => {
    await loadModule();
    // mgr-1 a un enfant (sub-a). Le toggle est une ligne header DANS le .conv-group (frère de .conv-children).
    const rootItem = document.querySelector('.conv-section-running [data-key="agent/mgr-1"]');
    const group = rootItem.closest(".conv-group");
    const toggle = group.querySelector(".conv-toggle");
    expect(toggle).not.toBeNull();

    const childrenBox = group.querySelector(".conv-children");
    // Enfant running seul -> replié par défaut.
    expect(childrenBox.hidden).toBe(true);

    // Clic sur le header -> déplie (sans ouvrir d'onglet).
    toggle.click();
    await flush();
    expect(childrenBox.hidden).toBe(false);
    expect(document.querySelectorAll("#conv-tabs .conv-tab").length).toBe(0);

    // Re-clic -> replie.
    toggle.click();
    await flush();
    expect(childrenBox.hidden).toBe(true);

    // Re-déplie pour cliquer l'enfant.
    toggle.click();
    await flush();
    const childItem = childrenBox.querySelector(".conv-item.conv-child");
    expect(childItem).not.toBeNull();
    expect(childItem.textContent).toContain("Subagent A");
    childItem.click();
    await flush();
    expect(document.querySelectorAll("#conv-tabs .conv-tab").length).toBe(1);
  });

  it("une racine sans sous-session n'a pas de toggle", async () => {
    await loadModule();
    // mgr-2 (finished) n'a pas d'enfant -> son .conv-group n'a pas de .conv-toggle.
    const mgr2 = document.querySelector('.conv-section-finished [data-key="agent/mgr-2"]');
    expect(mgr2).not.toBeNull();
    expect(mgr2.closest(".conv-group").querySelector(".conv-toggle")).toBeNull();
  });

  it("affiche un message quand aucune conversation manager", async () => {
    await loadModule({ nodes: [] });
    const list = document.getElementById("conv-list");
    expect(list.textContent).toContain("Aucune conversation manager");
    expect(list.querySelectorAll(".conv-item").length).toBe(0);
  });
});

// A5/T1 : persistance de l'etat deplie (localStorage) + badge agrégé + auto-expand awaiting-only.
describe("conversations.js — A5/T1 persistance deplie + badge + auto-expand", () => {
  // Arbre avec un enfant NON running (cli) -> replie par defaut, sert a tester
  // la persistance d'un depliage explicite.
  const TREE_IDLE = {
    nodes: [
      { key: "agent/mgr-idle", parent: null, state: "cli", title: "Manager idle" },
      { key: "agent/sub-idle", parent: "mgr-idle", state: "cli", title: "Subagent idle" },
    ],
  };
  // Arbre avec un enfant awaiting_* -> auto-expand (exception T1).
  const TREE_AWAIT = {
    nodes: [
      { key: "agent/mgr-aw", parent: null, state: "running", title: "Manager aw" },
      { key: "agent/sub-aw", parent: "mgr-aw", state: "awaiting_input", title: "Sub aw" },
    ],
  };
  // Helper : le toggle header du .conv-group du parent (frère de .conv-children).
  const groupOf = (key) => document.querySelector(`[data-key="${key}"]`).closest(".conv-group");

  it("badge agrégé : le toggle affiche la flèche + N sous-agents + agrégat d'états", async () => {
    await loadModule();
    const toggle = groupOf("agent/mgr-1").querySelector(".conv-toggle");
    // mgr-1 a exactement 1 enfant (sub-a running). Flèche ▸ (replié) + "1 sous-agent · 1 en cours".
    expect(toggle.textContent).toMatch(/^▸\s+1 sous-agent/);
    expect(toggle.textContent).toContain("1 en cours");
  });

  it("auto-expand awaiting-only : un enfant awaiting_* déplie automatiquement", async () => {
    await loadModule(TREE_AWAIT);
    const childrenBox = groupOf("agent/mgr-aw").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(false);
    const toggle = groupOf("agent/mgr-aw").querySelector(".conv-toggle");
    expect(toggle.textContent.startsWith("▾")).toBe(true);
  });

  it("un enfant running seul NE déplie PAS (replié par défaut)", async () => {
    await loadModule(); // TREE : sub-a running
    const childrenBox = groupOf("agent/mgr-1").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(true);
    const toggle = groupOf("agent/mgr-1").querySelector(".conv-toggle");
    expect(toggle.textContent.startsWith("▸")).toBe(true);
  });

  it("replié par défaut : un enfant ni running ni awaiting reste replié", async () => {
    await loadModule(TREE_IDLE);
    const childrenBox = groupOf("agent/mgr-idle").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(true);
    const toggle = groupOf("agent/mgr-idle").querySelector(".conv-toggle");
    expect(toggle.textContent.startsWith("▸")).toBe(true);
  });

  it("persistance : un dépliage explicite survit au re-render (refreshList 8s)", async () => {
    await loadModule(TREE_IDLE);
    let toggle = groupOf("agent/mgr-idle").querySelector(".conv-toggle");
    let childrenBox = groupOf("agent/mgr-idle").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(true);

    toggle.click();
    await flush();
    childrenBox = groupOf("agent/mgr-idle").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(false);

    await vi.advanceTimersByTimeAsync(8000);
    await flush();
    childrenBox = groupOf("agent/mgr-idle").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(false);
  });

  it("persistance localStorage : un dépliage explicite survit à un RELOAD (re-import module)", async () => {
    await loadModule(TREE_IDLE);
    let childrenBox = groupOf("agent/mgr-idle").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(true);

    // Dépliage explicite -> écrit dans localStorage bz.conv.expanded.
    groupOf("agent/mgr-idle").querySelector(".conv-toggle").click();
    await flush();
    expect(groupOf("agent/mgr-idle").querySelector(".conv-children").hidden).toBe(false);

    // Simule un RELOAD de page : re-import du module SANS clear du localStorage.
    mountDom();
    installFetch(TREE_IDLE);
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    // L'état déplié est restauré depuis localStorage.
    childrenBox = groupOf("agent/mgr-idle").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(false);
  });

  it("persistance : un repliage explicite prime sur l'auto-expand après re-render", async () => {
    await loadModule(TREE_AWAIT); // enfant awaiting -> auto-expand
    let childrenBox = groupOf("agent/mgr-aw").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(false); // auto-expand awaiting

    // L'utilisateur replie explicitement.
    groupOf("agent/mgr-aw").querySelector(".conv-toggle").click();
    await flush();
    childrenBox = groupOf("agent/mgr-aw").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(true);

    // Re-render : le repliage explicite (collapsed) prime sur l'auto-expand.
    await vi.advanceTimersByTimeAsync(8000);
    await flush();
    childrenBox = groupOf("agent/mgr-aw").querySelector(".conv-children");
    expect(childrenBox.hidden).toBe(true);
  });
});

describe("conversations.js — ouverture d'onglets internes", () => {
  it("clic sur un manager -> nouvel onglet + panel actif", async () => {
    await loadModule();
    const first = document.querySelector("#conv-list .conv-item");
    first.click();
    await flush();

    const tabs = document.querySelectorAll("#conv-tabs .conv-tab");
    const panels = document.querySelectorAll("#conv-panels .conv-panel");
    expect(tabs.length).toBe(1);
    expect(panels.length).toBe(1);
    // Le panel ouvert est visible et l'etat "vide" est masque.
    expect(panels[0].hidden).toBe(false);
    expect(document.querySelector(".conv-empty").hidden).toBe(true);
  });

  it("panel manager NE contient PLUS le rail .conv-subagents (bloc supprime)", async () => {
    await loadModule();
    const managers = document.querySelectorAll("#conv-list .conv-item");
    managers[0].click(); // Manager 1
    await flush();

    const panel = document.querySelector("#conv-panels .conv-panel");
    expect(panel).not.toBeNull();
    // Non-regression : plus aucun rail sous-agents ni chip dans le panneau.
    expect(panel.querySelector(".conv-subagents")).toBeNull();
    expect(panel.querySelector(".conv-sub-chip")).toBeNull();
    expect(panel.querySelector(".conv-sub-head")).toBeNull();
  });

  it("clic sur un marqueur inline [data-open-key] -> ouvre l'onglet du sous-agent", async () => {
    await loadModule();
    const managers = document.querySelectorAll("#conv-list .conv-item");
    managers[0].click(); // Manager 1
    await flush();

    // Le fil de conversation contient des marqueurs inline .subagent-event injectes
    // par le backend (data-open-key) ; le clic est delegue pour ouvrir l'onglet cible.
    const panel = document.querySelector("#conv-panels .conv-panel");
    const conv = panel.querySelector(".conv-messages");
    expect(conv).not.toBeNull();
    conv.insertAdjacentHTML(
      "beforeend",
      '<div class="subagent-event" data-open-key="agent/sub-a">Subagent A</div>'
    );

    conv.querySelector("[data-open-key]").click();
    await flush();

    // Un second onglet doit s'etre ouvert (mgr-1 + sub-a).
    expect(document.querySelectorAll("#conv-tabs .conv-tab").length).toBe(2);
    expect(document.querySelectorAll("#conv-panels .conv-panel").length).toBe(2);
  });
});

// --- Rendu conversation : appariement call/result + question ----------------

// fetch mocke a reponse /blocks custom (html + status) et capture /continue.
function installFetchBlocks(blocks, status, continueCalls) {
  const fetchMock = vi.fn((url, opts) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
    }
    if (url.includes("/continue")) {
      continueCalls.push(JSON.parse((opts && opts.body) || "{}"));
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ blocks, total: blocks.length, status, meta: {} }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock;
  return fetchMock;
}

async function loadWithBlocks(blocks, status, continueCalls) {
  mountDom();
  installFetchBlocks(blocks, status, continueCalls);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
  document.querySelector("#conv-list .conv-item").click();
  await flush();
}

describe("conversations.js — rendu d'une conversation (paires + question)", () => {
  it("imbrique chaque tool_result dans son tool_call correspondant", async () => {
    const blocks = [
      { idx: 0, html: '<details class="tc" data-tool-id="c1"><summary>call</summary></details>' },
      { idx: 1, html: '<details class="tr" data-tool-call-id="c1"><summary>res</summary></details>' },
    ];
    await loadWithBlocks(blocks, { state: "cli" }, []);

    const tc = document.querySelector("#conv-panels details.tc[data-tool-id='c1']");
    expect(tc).not.toBeNull();
    // Le result est desormais un ENFANT du call (imbrique) et marque paired.
    const nestedTr = tc.querySelector("details.tr[data-tool-call-id='c1']");
    expect(nestedTr).not.toBeNull();
    expect(nestedTr.dataset.paired).toBe("1");
  });

  it("affiche la question + options et permet d'y repondre depuis l'UI", async () => {
    const continueCalls = [];
    const status = {
      state: "awaiting_input",
      question: "Quelle option ?",
      options: [{ label: "Oui" }, { label: "Non" }],
    };
    await loadWithBlocks([], status, continueCalls);

    const question = document.querySelector("#conv-panels .conv-question");
    expect(question).not.toBeNull();
    expect(question.hidden).toBe(false);
    expect(document.querySelector(".conv-question-text").textContent).toBe("Quelle option ?");
    const opts = document.querySelectorAll(".conv-question-option");
    expect(opts.length).toBe(2);
    expect(opts[0].textContent).toBe("Oui");

    opts[0].click();
    await flush();
    // Reponse envoyee via /continue avec le label choisi.
    expect(continueCalls.length).toBe(1);
    expect(continueCalls[0].text).toBe("Oui");
  });

  // Agent INTERROMPU (crash / redémarrage) : « décider de son sort » = un input à await.
  // On réutilise le formatage awaiting (bloc question) pour offrir la reprise : pseudo-question
  // + bouton "Reprendre" → POST /continue {text:""} (reprise CHAUDE in-process si idle vivant,
  // sinon respawn COLD). Pas de zone séparée « agents interrompus ».
  it("agent interrompu (status.interrupted) : affiche pseudo-question + bouton Reprendre → /continue {text:\"\"}", async () => {
    const continueCalls = [];
    const status = { state: "finished", interrupted: true };
    await loadWithBlocks([], status, continueCalls);

    const question = document.querySelector("#conv-panels .conv-question");
    expect(question).not.toBeNull();
    expect(question.hidden).toBe(false);
    expect(document.querySelector(".conv-question-text").textContent.toLowerCase()).toContain("interrompu");

    const opts = document.querySelectorAll(".conv-question-option");
    expect(opts.length).toBe(1);
    expect(opts[0].textContent).toBe("Reprendre");

    opts[0].click();
    await flush();
    // Reprise via /continue avec un texte VIDE (pas de nouveau message : on relance le tour).
    expect(continueCalls.length).toBe(1);
    expect(continueCalls[0].text).toBe("");
  });
});

// --- B1 : validation de plan (awaiting_plan_validation) ---------------------
// Regression : une conv en attente de validation de plan doit AUSSI afficher le
// panneau question (renderQuestion ne s'activait qu'en "awaiting_input"), avec le
// PLAN (dernier tool_call WritePlan) affiche AU-DESSUS des boutons.
// Fixture DERIVEE DU REEL : le bloc /blocks reproduit exactement le HTML rendu par
// message_view._tool_call_html pour WritePlan (details.tc.toolcall + summary
// .tc-name="WritePlan" + body markdown), et le status renvoye par /blocks.
describe("conversations.js — B1 validation de plan (awaiting_plan_validation)", () => {
  // HTML d'un tool_call WritePlan tel que rendu par message_view (summary + body markdown).
  const PLAN_BLOCK = {
    idx: 0,
    html:
      '<details class="tc toolcall pui-tool-panel" data-tool-id="wp1">' +
      '<summary><span class="tc-kind">outil</span> <span class="pui-dot"></span> ' +
      '<span class="tc-name">WritePlan</span> <span class="tc-hint">Plan</span></summary>' +
      '<div class="md"><h2>Mon plan</h2><p>Etape 1 : faire le truc.</p></div>' +
      "</details>",
  };

  it("awaiting_plan_validation : le panneau s'affiche AVEC le plan au-dessus des boutons", async () => {
    const continueCalls = [];
    const status = {
      state: "awaiting_plan_validation",
      question: "Valides-tu ce plan ?",
      options: [{ label: "Oui, exécute" }, { label: "Non" }],
    };
    await loadWithBlocks([PLAN_BLOCK], status, continueCalls);

    // Le panneau question est visible (avant le fix : reste hidden car != awaiting_input).
    const question = document.querySelector("#conv-panels .conv-question");
    expect(question).not.toBeNull();
    expect(question.hidden).toBe(false);
    expect(document.querySelector(".conv-question-text").textContent).toBe("Valides-tu ce plan ?");

    // La zone plan est visible et contient le CORPS du plan (pas le summary/outil).
    const plan = document.querySelector(".conv-question-plan");
    expect(plan).not.toBeNull();
    expect(plan.hidden).toBe(false);
    expect(plan.textContent).toContain("Mon plan");
    expect(plan.textContent).toContain("Etape 1 : faire le truc.");
    // Le summary (label "outil" / "WritePlan") NE doit PAS etre recopie dans le panneau.
    expect(plan.querySelector("summary")).toBeNull();
    expect(plan.textContent).not.toContain("WritePlan");

    // Le plan est AU-DESSUS des boutons dans le DOM (ordre : text, plan, options).
    const optionsBox = document.querySelector(".conv-question-options");
    expect(plan.compareDocumentPosition(optionsBox) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Les boutons de validation restent fonctionnels (repond via /continue).
    const opts = document.querySelectorAll(".conv-question-option");
    expect(opts.length).toBe(2);
    opts[0].click();
    await flush();
    expect(continueCalls.length).toBe(1);
    expect(continueCalls[0].text).toBe("Oui, exécute");
  });

  it("awaiting_input classique : le panneau s'affiche mais SANS zone plan (meme si un WritePlan est present)", async () => {
    const status = {
      state: "awaiting_input",
      question: "Quelle option ?",
      options: [{ label: "A" }],
    };
    await loadWithBlocks([PLAN_BLOCK], status, []);

    const question = document.querySelector("#conv-panels .conv-question");
    expect(question.hidden).toBe(false);
    // Pas une validation de plan -> la zone plan reste masquee et vide.
    const plan = document.querySelector(".conv-question-plan");
    expect(plan.hidden).toBe(true);
    expect(plan.textContent).toBe("");
  });
});

describe("conversations.js — sendMsg auto-interrupt puis retry /continue (Q1)", () => {
  // Monte le mock APRÈS ouverture de l'onglet. /continue renvoie 409 au 1er appel
  // (agent running) puis ok ; /interrupt renvoie ok. On vérifie que sendMsg
  // enchaîne interrupt puis re-continue automatiquement.
  function installInterruptFetch(continueCalls, interruptCalls) {
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/interrupt")) {
        interruptCalls.push(1);
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/continue")) {
        continueCalls.push(JSON.parse((opts && opts.body) || "{}"));
        if (continueCalls.length === 1) {
          return Promise.resolve({
            ok: false,
            status: 409,
            json: () => Promise.resolve({ error: "l'agent tourne encore" }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ blocks: [], total: 0, status: { state: "running" }, meta: {} }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock;
    return fetchMock;
  }

  it("sur 409, interrompt puis ré-envoie /continue et vide l'input au succès", async () => {
    const continueCalls = [];
    const interruptCalls = [];
    // Ouvre le 1er onglet (mock initial /tree + /blocks via loadModule).
    await loadModule();
    document.querySelector("#conv-list .conv-item").click();
    await flush();
    // Remplace le fetch par le mock d'interruption (l'onglet est déjà ouvert).
    installInterruptFetch(continueCalls, interruptCalls);

    const input = document.querySelector("#conv-panels .conv-input-box");
    const send = document.querySelector("#conv-panels .conv-input-send");
    expect(input).not.toBeNull();
    expect(send).not.toBeNull();
    input.value = "precise ceci";
    send.click();
    // Déroule le delay + retry (fake timers).
    await vi.advanceTimersByTimeAsync(2000);
    await flush();

    expect(interruptCalls.length).toBeGreaterThanOrEqual(1);
    expect(continueCalls.length).toBeGreaterThanOrEqual(2);
    expect(input.value).toBe("");
  });

  it("chemin ok direct (agent non-running) : pas d'interrupt, input vidé", async () => {
    const continueCalls = [];
    const interruptCalls = [];
    await loadModule();
    document.querySelector("#conv-list .conv-item").click();
    await flush();
    // /continue ok immédiat.
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/interrupt")) {
        interruptCalls.push(1);
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/continue")) {
        continueCalls.push(JSON.parse((opts && opts.body) || "{}"));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ blocks: [], total: 0, status: { state: "idle" }, meta: {} }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock;

    const input = document.querySelector("#conv-panels .conv-input-box");
    const send = document.querySelector("#conv-panels .conv-input-send");
    input.value = "juste un suivi";
    send.click();
    await vi.advanceTimersByTimeAsync(2000);
    await flush();

    expect(interruptCalls.length).toBe(0);
    expect(continueCalls.length).toBe(1);
    expect(input.value).toBe("");
  });
});

describe("conversations.js — sectionnement par ÉTAT + bouton Archiver", () => {
  // T1 : sectionnement par ÉTAT (⚠ Nécessite une réponse / ● En cours / Terminés),
  // ordre fixe. Un sous-agent needsInput|running apparaît EN PROPRE au 1er niveau
  // (entrée flat ::flat + lien "↳ sous-agent de {parent}") EN PLUS de sous son parent.
  const CAT_TREE = {
    nodes: [
      { key: "agent/need-1", parent: null, state: "awaiting_input", title: "A traiter", branch: "main" },
      { key: "agent/user-1", parent: null, state: "running", title: "Ma conv", branch: "develop" },
      { key: "agent/meta-1", parent: null, state: "running", title: "Meta run", isolated: true },
      { key: "agent/test-1", parent: null, state: "finished", title: "smoke test login" },
      { key: "agent/sub-1", parent: "user-1", state: "running", title: "Subagent" },
    ],
  };

  it("3 sections par état dans l'ordre fixe : Nécessite une action, En cours, Terminés", async () => {
    await loadModule(CAT_TREE);
    const list = document.getElementById("conv-list");

    // La section needinput est le PREMIER enfant de #conv-list.
    const needSec = list.querySelector(".conv-section-needinput");
    const runSec = list.querySelector(".conv-section-running");
    const finSec = list.querySelector(".conv-section-finished");
    expect(needSec).not.toBeNull();
    expect(runSec).not.toBeNull();
    expect(finSec).not.toBeNull();
    expect(list.firstElementChild).toBe(needSec);

    // Ordre DOM fixe : needinput avant running avant finished.
    expect(needSec.compareDocumentPosition(runSec) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(runSec.compareDocumentPosition(finSec) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Titres par section, chacun PREMIER enfant de son wrapper.
    expect(needSec.firstElementChild.classList.contains("conv-cat-title")).toBe(true);
    expect(needSec.textContent).toContain("Nécessite une action");
    expect(needSec.textContent).toContain("A traiter"); // need-1 awaiting → section a
    expect(runSec.firstElementChild.classList.contains("conv-cat-title")).toBe(true);
    expect(runSec.textContent).toContain("En cours");
    expect(runSec.textContent).toContain("Ma conv");   // user-1 running → section b
    expect(runSec.textContent).toContain("Meta run");  // meta-1 running → section b
    expect(finSec.firstElementChild.classList.contains("conv-cat-title")).toBe(true);
    expect(finSec.textContent).toContain("Terminés");
    expect(finSec.textContent).toContain("smoke test login"); // test-1 finished → section c

    // sub-1 (enfant running de user-1) → NOUVELLE règle : ne remonte PAS en section
    // running (aucune entrée flat). Il reste imbriqué sous user-1.
    expect(runSec.querySelector('[data-key="agent/sub-1::flat"]')).toBeNull();
    const userGroup = runSec.querySelector('[data-key="agent/user-1"]').closest(".conv-group");
    expect(userGroup.querySelector(".conv-children").textContent).toContain("Subagent");

    // need-1 n'apparaît PAS ailleurs qu'en section needinput (racine unique, pas enfant ici).
    expect(runSec.textContent).not.toContain("A traiter");
    expect(finSec.textContent).not.toContain("A traiter");
  });

  it("le node need_input porte un bouton Archiver -> POST archive + disparait apres re-render", async () => {
    // fetch custom : capture l'archive, sert un 2e tree SANS le node archive au refresh suivant.
    let archived = false;
    const archiveCalls = [];
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes("/api/conversations/archive")) {
        archived = true;
        archiveCalls.push({ url, body: JSON.parse(opts.body), method: opts.method });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/api/agents/tree")) {
        const nodes = archived
          ? CAT_TREE.nodes.filter((n) => n.key !== "agent/need-1")
          : CAT_TREE.nodes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes }) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    const section = document.querySelector(".conv-section-needinput");
    const btn = section.querySelector(".conv-archive-btn");
    expect(btn).not.toBeNull();
    expect(section.textContent).toContain("A traiter");
    void archiveCalls;

    btn.click();
    await vi.advanceTimersByTimeAsync(3000);
    await flush();

    // POST vers l'endpoint RÉEL du backend : /api/conversations/archive
    // avec body {keys:["agent/<id>"]} (clé complète). Calé sur routes/sessions.py.
    expect(archiveCalls.length).toBe(1);
    expect(archiveCalls[0].method).toBe("POST");
    expect(archiveCalls[0].url).toContain("/api/conversations/archive");
    expect(archiveCalls[0].body).toEqual({ keys: ["agent/need-1"] });

    // Effet DOM : apres re-render (tree sans need-1) la conv a disparu.
    expect(document.querySelector(".conv-section-needinput")).toBeNull();
    expect(document.getElementById("conv-list").textContent).not.toContain("A traiter");
  });
});

describe("conversations.js — archive sidebar : update optimiste + rollback", () => {
  // Le bouton "Archiver" d'une racine sidebar (rec.archBtn) appelle archiveNode(key),
  // qui POST /api/conversations/archive {keys:[key]}. AVANT le fix, la carte restait
  // visible/active jusqu'au retour serveur + refetch complet (latence perçue).
  // Fix : grisage OPTIMISTE immédiat (classe conv-group--archiving) au clic, réconcilié
  // sur succès (refreshList purge la carte) ou rollback sur échec (classe retirée).
  // Fixture DÉRIVÉE DU RÉEL : TREE (mgr-1 running racine → a un .conv-archive-btn).

  // Retourne le .conv-group racine de mgr-1 (la carte à griser).
  const cardGroup = () =>
    document.querySelector('.conv-section-running [data-key="agent/mgr-1"]').closest(".conv-group");
  // Le bouton "Archiver" de cette carte racine.
  const archBtn = () => cardGroup().querySelector(".conv-archive-btn");

  it("clic Archiver → la carte est grisée IMMÉDIATEMENT (classe conv-group--archiving) AVANT la réponse serveur", async () => {
    // fetch archive à résolution DIFFÉRÉE : on tient la promise ouverte pour prouver
    // que le grisage est appliqué SYNCHRONE au clic, sans attendre le serveur.
    let resolveArchive;
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/conversations/archive")) {
        return new Promise((res) => { resolveArchive = () => res({ ok: true, json: () => Promise.resolve({ ok: true }) }); });
      }
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    const btn = archBtn();
    expect(btn).not.toBeNull();
    const group = cardGroup();
    expect(group.classList.contains("conv-group--archiving")).toBe(false);

    // Clic : démarre le décompte annulable (3s). Le grisage optimiste (add synchrone
    // avant le 1er await de archiveNode) n'a lieu qu'à la FIN du décompte → on avance
    // les fake timers de 3s pour le consommer, PUIS on vérifie le grisage (la promise
    // archive reste ouverte via resolveArchive → pas encore de rollback).
    btn.click();
    await vi.advanceTimersByTimeAsync(3000);
    expect(group.classList.contains("conv-group--archiving")).toBe(true);

    // Nettoyage : on résout l'archive pour ne pas laisser de promise pendante.
    if (resolveArchive) resolveArchive();
    await flush();
  });

  it("succès serveur : refreshList réconcilie et la carte disparaît (node plus archivé côté serveur)", async () => {
    // Après archive ok, le tree suivant ne contient PLUS mgr-1 → la carte est purgée.
    let archived = false;
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes("/api/conversations/archive")) {
        archived = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
      }
      if (url.includes("/api/agents/tree")) {
        const nodes = archived ? TREE.nodes.filter((n) => n.key !== "agent/mgr-1") : TREE.nodes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes }) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    expect(document.querySelector('[data-key="agent/mgr-1"]')).not.toBeNull();
    archBtn().click();
    await vi.advanceTimersByTimeAsync(3000);
    await flush();

    // L'archive a été postée avec la clé complète, et la carte a disparu après re-render.
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/conversations/archive"))).toBe(true);
    expect(document.querySelector('[data-key="agent/mgr-1"]')).toBeNull();
  });

  it("échec serveur (HTTP non ok) : ROLLBACK visuel — la classe est retirée, la carte reste active", async () => {
    // L'endpoint archive répond ok:false : la carte NE doit PAS rester grisée.
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/conversations/archive")) {
        return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: "boom" }) });
      }
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    const group = cardGroup();
    archBtn().click();
    // Le bouton démarre un décompte annulable de 3s ; on le laisse expirer pour
    // déclencher l'archive réelle (grisage optimiste + POST).
    await vi.advanceTimersByTimeAsync(3000);
    await flush();
    // Rollback : la classe est retirée et la carte est toujours présente/active.
    expect(cardGroup().classList.contains("conv-group--archiving")).toBe(false);
    expect(document.querySelector('[data-key="agent/mgr-1"]')).not.toBeNull();
  });

  it("échec réseau (fetch rejette) : ROLLBACK visuel — la classe est retirée", async () => {
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/conversations/archive")) {
        return Promise.reject(new Error("network down"));
      }
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    const group = cardGroup();
    archBtn().click();
    await vi.advanceTimersByTimeAsync(3000);
    await flush();
    expect(cardGroup().classList.contains("conv-group--archiving")).toBe(false);
    expect(document.querySelector('[data-key="agent/mgr-1"]')).not.toBeNull();
  });
});

describe("conversations.js — conv manuelle (dispatch:manual) dans le tree", () => {
  // Régression : une conv créée via "nouvelle conversation" a parent="dispatcher:manual"
  // (marqueur de dispatch manuel, PAS un agent-parent réel). Elle DOIT apparaître dans la
  // sidebar comme racine, classée "Méta-agent". Un vrai subagent (parent=agent présent)
  // reste exclu du 1er niveau (imbriqué).
  const MANUAL_TREE = {
    nodes: [
      { key: "agent/mgr-1", parent: null, state: "running", title: "Manager 1" },
      { key: "agent/man-1", parent: "dispatcher:manual", state: "running", title: "Conv manuelle" },
      { key: "agent/sub-a", parent: "mgr-1", state: "running", title: "Subagent A" },
    ],
  };

  it("la conv manuelle (parent=dispatcher:manual) est une racine, classée par son état (En cours)", async () => {
    await loadModule(MANUAL_TREE);

    // Racines au 1er niveau (hors flat) : Manager 1 et Conv manuelle (pas le subagent).
    const rootTitles = rootTitlesStr();
    expect(rootTitles).toContain("Manager 1");
    expect(rootTitles).toContain("Conv manuelle");
    expect(rootTitles).not.toContain("Subagent A");

    // Conv manuelle (running) rangée dans la section "● En cours".
    const runSec = document.querySelector(".conv-section-running");
    expect(runSec).not.toBeNull();
    expect(runSec.textContent).toContain("Conv manuelle");

    // Le subagent reste UNIQUEMENT dans un bloc enfants (imbriqué sous mgr-1) —
    // NOUVELLE règle : plus AUCUNE entrée flat de premier niveau.
    const childrenBox = document.querySelector("#conv-list .conv-children");
    expect(childrenBox).not.toBeNull();
    expect(childrenBox.textContent).toContain("Subagent A");
    expect(runSec.querySelector('[data-key="agent/sub-a::flat"]')).toBeNull();
  });
});

describe("conversations.js — sous-agents validateur / auto-merge imbriqués sous le codeur", () => {
  // Régression : un validateur (ou résolveur de merge) doit s'afficher IMBRIQUÉ sous son codeur
  // et être cliquable — JAMAIS remonté en fausse racine. Deux formes coexistent sur disque :
  //  - NOUVELLE : parent = id réel du codeur (ex. "cod-1") → imbriqué via childrenOf.
  //  - HÉRITÉE  : parent = littéral "dispatcher:validate"/"dispatcher:auto-merge" → n'est pas
  //    une racine (garde-fou front) ; il disparaît du 1er niveau (son codeur d'origine est perdu).
  const VALIDATOR_TREE = {
    nodes: [
      { key: "agent/cod-1", parent: "dispatcher:manual", state: "running", title: "Codeur ticket" },
      { key: "agent/val-1", parent: "cod-1", state: "running", title: "Validateur" },
      { key: "agent/leg-1", parent: "dispatcher:validate", state: "finished", title: "Validateur hérité" },
      { key: "agent/leg-2", parent: "dispatcher:auto-merge", state: "finished", title: "Merge hérité" },
    ],
  };

  it("le validateur running N'est PAS remonté à la racine, seulement imbriqué sous le codeur", async () => {
    // NOUVELLE règle : un sous-agent running (validateur) ne remonte PLUS au 1er niveau
    // (aucune entrée flat en « En cours »). Il reste UNIQUEMENT imbriqué sous son codeur,
    // accessible via le toggle/chip du parent. Pas de VRAIE racine non plus.
    await loadModule(VALIDATOR_TREE);
    // Vraies racines (hors flat) : le codeur oui, le validateur NON.
    expect(rootTitlesStr()).toContain("Codeur ticket");
    expect(rootItems().map((el) => el.dataset.key)).not.toContain("agent/val-1");

    // Aucune entrée FLAT de premier niveau pour le validateur running.
    expect(document.querySelector('[data-key="agent/val-1::flat"]')).toBeNull();

    // Le validateur vit UNIQUEMENT dans le bloc enfants du codeur (imbriqué + cliquable).
    const codRow = rootItems().find((el) => el.dataset.key === "agent/cod-1");
    const childrenBox = codRow.closest(".conv-group").querySelector(".conv-children");
    expect(childrenBox).not.toBeNull();
    expect(childrenBox.querySelector('[data-key="agent/val-1"]')).not.toBeNull();

    // Les hérités finished (leg-1/leg-2) ne sont NI racine NI flat (finished => pas de flat).
    expect(rootTitlesStr()).not.toContain("Validateur hérité");
    expect(document.querySelector('[data-key="agent/leg-1::flat"]')).toBeNull();
    expect(document.querySelector('[data-key="agent/leg-2::flat"]')).toBeNull();
  });

  it("les sous-agents hérités (parent=dispatcher:validate|auto-merge) ne sont PAS des racines", async () => {
    await loadModule(VALIDATOR_TREE);
    const rootTitles = rootTitlesStr();
    expect(rootTitles).not.toContain("Validateur hérité");
    expect(rootTitles).not.toContain("Merge hérité");
  });

  // FALLBACK PAR BRANCH (resolveOrphanParents) : quand le back n'a pas pu reparenter un
  // orphelin hérité (ticket disparu / pas de codeur résolu), le front le rattache au codeur
  // qui partage la MÊME branche/worktree, pour qu'il s'imbrique sous lui au lieu de rester perdu.
  const BRANCH_FALLBACK_TREE = {
    nodes: [
      { key: "agent/cod-b", parent: "dispatcher:manual", state: "running", title: "Codeur branche X", branch: "feat/x" },
      { key: "agent/leg-b", parent: "dispatcher:validate", state: "finished", title: "Validateur hérité branche X", branch: "feat/x" },
      { key: "agent/leg-c", parent: "dispatcher:validate", state: "finished", title: "Validateur hérité sans branche", branch: "" },
    ],
  };

  it("un orphelin hérité est rattaché par branch au codeur du même worktree (imbriqué, pas racine)", async () => {
    await loadModule(BRANCH_FALLBACK_TREE);
    const rootTitles = rootTitlesStr();
    // Rattaché par branch → n'apparaît plus au 1er niveau, mais imbriqué sous son codeur.
    expect(rootTitles).toContain("Codeur branche X");
    expect(rootTitles).not.toContain("Validateur hérité branche X");
    const childrenBox = document.querySelector("#conv-list .conv-children");
    expect(childrenBox).not.toBeNull();
    expect(childrenBox.textContent).toContain("Validateur hérité branche X");
    // Contrôle : sans branche commune, aucun candidat → reste non-racine (pas de faux rattachement).
    expect(childrenBox.textContent).not.toContain("Validateur hérité sans branche");
    expect(rootTitles).not.toContain("Validateur hérité sans branche");
  });
});

describe("conversations.js — barre nouvelle conversation (composeur)", () => {
  it("Entrée dans le champ -> POST /api/dispatch {prompt} puis ouvre l'onglet créé", async () => {
    const dispatchCalls = [];
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes("/api/dispatch")) {
        dispatchCalls.push({ method: opts.method, body: JSON.parse(opts.body) });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ key: "agent/new-99" }) });
      }
      if (url.includes("/api/agents/tree")) {
        const nodes = dispatchCalls.length
          ? [...TREE.nodes, { key: "agent/new-99", parent: null, state: "running", title: "Fais un truc" }]
          : TREE.nodes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes }) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    const input = document.getElementById("conv-new-input");
    input.value = "Fais un truc";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flush();

    // Un seul POST /api/dispatch avec le prompt saisi.
    expect(dispatchCalls.length).toBe(1);
    expect(dispatchCalls[0].method).toBe("POST");
    expect(dispatchCalls[0].body).toEqual({
      prompt: "Fais un truc",
      typology: "default",
      isolation: "shared",
      defer: true,
    });

    // La conversation créée est ouverte en onglet et le champ est vidé.
    expect(input.value).toBe("");
    expect(document.getElementById("conv-tabs").textContent).toContain("Fais un truc");
  });

  // Anti-régression du délai 6-7s : la création part TOUJOURS en `defer:true` pour que
  // le serveur (dispatch()) réponde dès le ticket créé (thread _launch_bg en fond) au lieu
  // de bloquer sur _launch synchrone (worktree + spawn). Sans ce flag, l'input reste
  // disabled plusieurs secondes → impossible de "shooter des tickets à la volée".
  it("le POST /api/dispatch de création porte TOUJOURS defer:true (réponse immédiate, pas de blocage)", async () => {
    const dispatchCalls = [];
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes("/api/dispatch")) {
        dispatchCalls.push({ method: opts.method, body: JSON.parse(opts.body) });
        // Réponse type d'un dispatch différé : ticket créé, deferred:true, PAS de key.
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ deferred: true, ticket_id: "T-1" }) });
      }
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    const input = document.getElementById("conv-new-input");
    input.value = "Shoote un ticket";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flush();

    expect(dispatchCalls.length).toBe(1);
    expect(dispatchCalls[0].body.defer).toBe(true);
    // Réponse différée sans key : pas d'onglet auto ouvert, mais l'input est revidé/réactivé
    // tout de suite (le champ est prêt pour le prochain ticket).
    expect(input.value).toBe("");
    expect(input.disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Banniere "type d'agent" togglee (feature du ticket).
// mountDom AVEC la banniere (structure derivee du vrai template conversations.html),
// fetch mock routant /api/typologies (fixture derivee de list_typologies : default
// TOUJOURS 1er, profile="" ; puis un agent non-default). Asserts : toggle ouvre/ferme,
// peuplement des radios, selection non-default -> label MAJ + localStorage +
// typology non vide dans le POST /api/dispatch, retour default -> typology "".
// ---------------------------------------------------------------------------

// Fixture derivee de list_typologies() (services/typologies.py) : "default" 1er,
// profile vide ; chaque item {name, description, profile, default_model, default_cwd}.
const TYPOLOGIES = {
  typologies: [
    { name: "default", description: "Agent standard", profile: "", default_model: "", default_cwd: "" },
    { name: "reviewer", description: "Relit le code", profile: "reviewer", default_model: "", default_cwd: "" },
  ],
};

// mountDom + le bloc banniere, calque exact du template conversations.html (L60-68).
function mountDomWithBanner() {
  document.body.innerHTML = `
    <aside><div id="conv-list"></div></aside>
    <form id="conv-new-bar"><textarea id="conv-new-input"></textarea>
      <button id="conv-new-send" type="submit"></button></form>
    <div class="conv-agent-bar">
      <button id="conv-agent-toggle" class="conv-agent-toggle" type="button"
        aria-expanded="false" aria-controls="conv-agent-panel">
        <span class="conv-agent-caret" aria-hidden="true">&#9656;</span>
        <span class="conv-agent-toggle-label">Type d'agent :</span>
        <span id="conv-agent-value" class="conv-agent-toggle-value">&#8230;</span>
      </button>
      <div id="conv-agent-panel" class="conv-agent-panel" role="radiogroup"
        aria-label="Type d'agent" hidden></div>
    </div>
    <div id="conv-new-error"></div>
    <div id="conv-tabs"></div>
    <div id="conv-panels"><div class="conv-empty">Vide</div></div>
  `;
}

// fetch mock qui route AUSSI /api/typologies et capture les POST /api/dispatch.
function installFetchWithTypologies() {
  const dispatchCalls = [];
  const fetchMock = vi.fn((url, opts) => {
    if (url.includes("/api/typologies")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(TYPOLOGIES) });
    }
    if (url.includes("/api/dispatch")) {
      dispatchCalls.push({ method: opts.method, body: JSON.parse(opts.body) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ key: "agent/new-1" }) });
    }
    if (url.includes("/api/agents/tree")) {
      const nodes = dispatchCalls.length
        ? [...TREE.nodes, { key: "agent/new-1", parent: null, state: "running", title: "Fais un truc" }]
        : TREE.nodes;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes }) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock;
  return { fetchMock, dispatchCalls };
}

async function loadModuleWithBanner() {
  localStorage.clear();
  mountDomWithBanner();
  const ctx = installFetchWithTypologies();
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
  return ctx;
}

describe("conversations.js — banniere type d'agent", () => {
  it("au boot : panneau ferme, radios peuples depuis /api/typologies, default coche + label", async () => {
    await loadModuleWithBanner();

    const toggle = document.getElementById("conv-agent-toggle");
    const panel = document.getElementById("conv-agent-panel");
    const value = document.getElementById("conv-agent-value");

    // Ferme par defaut.
    expect(panel.hidden).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    // 2 radios peuples (default + reviewer), meme name.
    const radios = panel.querySelectorAll('input[type="radio"][name="conv-typology"]');
    expect(radios.length).toBe(2);
    expect([...radios].map((r) => r.value)).toEqual(["default", "reviewer"]);

    // default (1er) coche + label affiche "default".
    expect(radios[0].checked).toBe(true);
    expect(value.textContent).toBe("default");
  });

  it("clic sur le toggle ouvre puis referme le panneau (hidden + aria-expanded)", async () => {
    await loadModuleWithBanner();
    const toggle = document.getElementById("conv-agent-toggle");
    const panel = document.getElementById("conv-agent-panel");

    toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(panel.hidden).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("selection d'un type non-default : label MAJ + localStorage + typology dans le POST", async () => {
    const { dispatchCalls } = await loadModuleWithBanner();
    const panel = document.getElementById("conv-agent-panel");
    const value = document.getElementById("conv-agent-value");
    const radios = panel.querySelectorAll('input[type="radio"][name="conv-typology"]');

    // Selectionne "reviewer".
    radios[1].checked = true;
    radios[1].dispatchEvent(new Event("change", { bubbles: true }));

    expect(value.textContent).toBe("reviewer");
    expect(localStorage.getItem("bz.conv.typology")).toBe("reviewer");

    // Un nouveau prompt part avec typology "reviewer".
    const input = document.getElementById("conv-new-input");
    input.value = "Fais un truc";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flush();

    expect(dispatchCalls.length).toBe(1);
    expect(dispatchCalls[0].body).toEqual({ prompt: "Fais un truc", typology: "reviewer", isolation: "shared", defer: true });
  });

  it("retour au default (1er item) : localStorage vide + POST typology \"default\"", async () => {
    const { dispatchCalls } = await loadModuleWithBanner();
    const panel = document.getElementById("conv-agent-panel");
    const radios = panel.querySelectorAll('input[type="radio"][name="conv-typology"]');

    // Passe reviewer puis revient sur default.
    radios[1].checked = true;
    radios[1].dispatchEvent(new Event("change", { bubbles: true }));
    radios[0].checked = true;
    radios[0].dispatchEvent(new Event("change", { bubbles: true }));

    expect(localStorage.getItem("bz.conv.typology")).toBe("");

    const input = document.getElementById("conv-new-input");
    input.value = "Autre chose";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flush();

    expect(dispatchCalls.length).toBe(1);
    expect(dispatchCalls[0].body).toEqual({ prompt: "Autre chose", typology: "default", isolation: "shared", defer: true });
  });
});

describe("conversations.js — AUCUN rail sous-agents dans le panel", () => {
  it("le panel du manager ne contient aucun bloc .conv-subagents (rail supprimé)", async () => {
    await loadModule();
    document.querySelector("#conv-list .conv-item").click();
    await flush();

    const panel = document.querySelector("#conv-panels .conv-panel");
    expect(panel).not.toBeNull();
    expect(panel.querySelector(".conv-subagents")).toBeNull();
    expect(panel.querySelector(".conv-sub-head")).toBeNull();
    expect(panel.querySelector(".conv-sub-body")).toBeNull();
    expect(panel.querySelector(".conv-sub-chip")).toBeNull();
  });
});

describe("streaming partial (token-par-token)", () => {
  // Mock fetch local pilote PAR LE TEST : /partial renvoie `ctl.partial` (objet
  // mutable). Le texte ne change QUE quand le test modifie ctl.partial -> le test
  // est deterministe, immunise au nombre exact de ticks draines par les fake timers.
  function installFetchStreaming(ctl, blocks = []) {
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/partial")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(ctl.partial) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            blocks, total: blocks.length, status: { state: "running" }, meta: {},
          }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock;
    return fetchMock;
  }

  async function openStreamingTab(ctl, blocks = []) {
    mountDom();
    installFetchStreaming(ctl, blocks);
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();
    document.querySelector("#conv-list .conv-item").click();
    await flush();
  }

  it("cree un .streaming-block dont le texte grandit quand le partial croit", async () => {
    const ctl = { partial: { text: "Bon" } };
    await openStreamingTab(ctl);

    const conv = document.querySelector(".conv-messages");
    expect(conv).not.toBeNull();

    // Le partial vaut "Bon" -> avancer garantit au moins un tick pollPartial (250ms).
    await vi.advanceTimersByTimeAsync(300);
    let sb = conv.querySelector(".streaming-block");
    expect(sb).not.toBeNull();
    const t1 = sb.textContent;
    expect(t1).toBe("Bon");

    // Le backend a produit plus de tokens : le test fait grossir le partial.
    ctl.partial = { text: "Bonjour le monde entier" };
    await vi.advanceTimersByTimeAsync(300);
    sb = conv.querySelector(".streaming-block");
    const t2 = sb.textContent;
    expect(t2.length).toBeGreaterThan(t1.length);
    expect(t2).toBe("Bonjour le monde entier");
  });

  it("retire le .streaming-block quand /partial renvoie text:null", async () => {
    const ctl = { partial: { text: "Salut" } };
    await openStreamingTab(ctl);
    const conv = document.querySelector(".conv-messages");

    // Du texte -> le bloc apparait.
    await vi.advanceTimersByTimeAsync(300);
    expect(conv.querySelector(".streaming-block")).not.toBeNull();

    // Message persiste -> plus de partial (text:null) -> le bloc est retire.
    ctl.partial = { text: null };
    await vi.advanceTimersByTimeAsync(300);
    expect(conv.querySelector(".streaming-block")).toBeNull();
  });
});

describe("conversations.js — B3 rendu keyé (identité DOM + état déplié)", () => {
  // Ces tests reproduisent le bug du re-render destructeur (replaceChildren toutes
  // les 8s) : un refresh AUTO ne doit PAS reconstruire les rows (clic raté) ni
  // reinitialiser l'etat deplie (childrenBox.hidden). Fixture = TREE reelle.

  it("un refresh auto (8s) PRESERVE l'instance DOM du .conv-item (pas de reconstruction)", async () => {
    await loadModule(); // TREE : mgr-1 racine (running)
    const row1 = rootItems()[0];
    expect(row1).not.toBeNull();

    // Le setInterval(refreshList, 8000) rejoue un refresh sur les MEMES donnees.
    await vi.advanceTimersByTimeAsync(8000);
    await flush();

    const row2 = rootItems()[0];
    // Rendu keye : meme cle -> MEME instance DOM (identite preservee).
    expect(row2).toBe(row1);
  });

  it("un refresh auto (8s) PRESERVE l'etat deplie (childrenBox.hidden reste false)", async () => {
    // Enfant NON running (cli) -> replie par defaut : on teste la persistance d'un
    // depliage EXPLICITE (pas l'auto-expand). Meme schema que /api/agents/tree.
    const TREE_IDLE_B3 = {
      nodes: [
        { key: "agent/mgr-idle", parent: null, state: "cli", title: "Manager idle" },
        { key: "agent/sub-idle", parent: "mgr-idle", state: "cli", title: "Subagent idle" },
      ],
    };
    await loadModule(TREE_IDLE_B3); // mgr-idle a un enfant sub-idle (cli -> replie)
    const rootItem = rootItems()[0];
    const group = rootItem.closest(".conv-group");
    const toggle = group.querySelector(".conv-toggle"); // ligne header, frere de .conv-children
    expect(toggle).not.toBeNull();
    const childrenBox = group.querySelector(".conv-children");
    // Etat initial : replie (enfant cli, pas d'auto-expand).
    expect(childrenBox.hidden).toBe(true);

    // L'utilisateur DEPLIE explicitement (retire la cle de collapsedKeys / desiredOpen).
    toggle.click();
    await flush();
    expect(childrenBox.hidden).toBe(false);

    // Un refresh auto survient : l'etat DEPLIE choisi par l'utilisateur doit SURVIVRE.
    await vi.advanceTimersByTimeAsync(8000);
    await flush();

    const childrenBoxAfter = rootItems()[0]
      .closest(".conv-group")
      .querySelector(".conv-children");
    expect(childrenBoxAfter.hidden).toBe(false);
  });
});

// --- B6 : arret du polling sur conversations terminees --------------------
// Bug : pollPartial se re-programmait toutes les 1500ms INDEFINIMENT meme sur
// etat terminal (finished/cli) -> centaines de req/min. Fix : pollPartial ne
// se re-programme QUE si running && onglet visible. poll() reste tournant mais
// espace a 15s sur terminal. Tests = logique timers/fetch (happy-dom, ZERO
// visuel). Fixture derivee du reel (TREE + forme /blocks reelle).
describe("polling terminal (B6)", () => {
  // ctl mutable pilote par le test : ctl.state -> status.state renvoye par
  // /blocks ; ctl.partial -> reponse /partial. On compte les appels /partial.
  function installFetchState(ctl, blocks = []) {
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/agents/tree")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      }
      if (url.includes("/partial")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(ctl.partial) });
      }
      if (url.includes("/blocks")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            blocks, total: blocks.length, status: { state: ctl.state }, meta: {},
          }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock;
    return fetchMock;
  }

  async function openStateTab(ctl, blocks = []) {
    mountDom();
    const fetchMock = installFetchState(ctl, blocks);
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();
    document.querySelector("#conv-list .conv-item").click();
    await flush();
    return fetchMock;
  }

  const partialCount = (fetchMock) =>
    fetchMock.mock.calls.filter(([u]) => typeof u === "string" && u.includes("/partial")).length;

  it("STOPPE pollPartial sur un onglet deja terminal (finished)", async () => {
    const ctl = { state: "finished", partial: { text: null } };
    const fetchMock = await openStateTab(ctl);

    // Laisse poll() etablir lastState="finished" (premier /blocks).
    await vi.advanceTimersByTimeAsync(400);
    const c1 = partialCount(fetchMock);

    // Avance largement : sur terminal, pollPartial NE doit PAS se re-programmer.
    await vi.advanceTimersByTimeAsync(10000);
    const c2 = partialCount(fetchMock);

    // Le compteur /partial ne bouge plus (aucune re-boucle 1500ms indefinie).
    expect(c2).toBe(c1);
  });

  it("STOPPE pollPartial quand running -> finished", async () => {
    const ctl = { state: "running", partial: { text: null } };
    const fetchMock = await openStateTab(ctl);

    // Phase running : /partial tourne a 250ms -> le compteur grimpe.
    await vi.advanceTimersByTimeAsync(1000);
    const cRunning = partialCount(fetchMock);
    expect(cRunning).toBeGreaterThan(1);

    // La conv se termine : poll() lit finished, pollPartial doit s'arreter.
    ctl.state = "finished";
    // Laisse au moins un cycle poll (>=1500ms) + un tick pollPartial pour STOP.
    await vi.advanceTimersByTimeAsync(2000);
    const cAfterFinish = partialCount(fetchMock);

    // Encore du temps : plus aucun /partial.
    await vi.advanceTimersByTimeAsync(10000);
    expect(partialCount(fetchMock)).toBe(cAfterFinish);
  });

  it("RELANCE pollPartial sur reprise finished -> running", async () => {
    const ctl = { state: "finished", partial: { text: null } };
    const fetchMock = await openStateTab(ctl);
    await vi.advanceTimersByTimeAsync(400);
    const cTerminal = partialCount(fetchMock);

    // Reprise (ex: /continue) : poll() lit running -> doit relancer pollPartial.
    ctl.state = "running";
    // poll() sur terminal tourne a 15s : il faut depasser un cycle pour detecter.
    await vi.advanceTimersByTimeAsync(16000);
    const cAfterResume = partialCount(fetchMock);

    // pollPartial a repris : le compteur /partial a augmente.
    expect(cAfterResume).toBeGreaterThan(cTerminal);
  });

  it("onglet cache : pas de tick rapide /partial meme en running", async () => {
    Object.defineProperty(document, "visibilityState", {
      value: "hidden", configurable: true,
    });
    const ctl = { state: "running", partial: { text: null } };
    const fetchMock = await openStateTab(ctl);

    // Onglet cache : pollPartial ne se re-programme pas -> peu d'appels /partial.
    await vi.advanceTimersByTimeAsync(3000);
    const cHidden = partialCount(fetchMock);
    expect(cHidden).toBeLessThanOrEqual(2);

    // Restaure pour ne pas polluer les autres tests.
    Object.defineProperty(document, "visibilityState", {
      value: "visible", configurable: true,
    });
  });
});

// A4 : le titre affiché = libellé court (n.title, déjà dérivé backend) ; le prompt
// complet (n.title_full) est posé en attribut title (tooltip) sur l'élément titre
// de la sidebar ET sur l'onglet ouvert.
describe("A4 libellés courts sous-agents + tooltip prompt complet", () => {
  const TREE_A4 = {
    nodes: [
      {
        key: "agent/val-1",
        parent: null,
        state: "running",
        title: "Validateur · python-coder · 10:39",
        title_full: "Tu valides le travail de l'agent python-coder sur le ticket A4 : vérifie que le libellé court est correct.",
      },
    ],
  };

  it("sidebar : textContent=libellé court, attribut title=prompt complet", async () => {
    await loadModule(TREE_A4);
    const titleEl = document.querySelector("#conv-list .conv-item-title");
    expect(titleEl).not.toBeNull();
    expect(titleEl.textContent).toBe("Validateur · python-coder · 10:39");
    expect(titleEl.title).toBe(TREE_A4.nodes[0].title_full);
  });

  it("onglet : span=libellé court, attribut title(tooltip)=prompt complet", async () => {
    await loadModule(TREE_A4);
    document.querySelector("#conv-list .conv-item").click();
    await flush();
    const tab = document.querySelector("#conv-tabs .conv-tab");
    expect(tab).not.toBeNull();
    // L'onglet applique un TRONCAGE volontaire (roleShort = 1er segment avant "·",
    // conversations.js L852-854) : span = "Validateur", tooltip = prompt complet.
    expect(tab.querySelector(".conv-tab-title").textContent).toBe("Validateur");
    expect(tab.title).toContain(TREE_A4.nodes[0].title_full);
  });
});

// Manager "finished" mais avec des enfants encore vivants = EN ATTENTE (il a clos son tour pour
// être ré-invocable par le wake). L'UI ne doit PAS l'afficher "terminé" (il paraîtrait mort).
describe("conversations.js — manager en attente d'enfants affiché actif", () => {
  const TREE_WAIT = { nodes: [
    { key: "agent/mgr-w", parent: null, state: "finished", title: "Manager waiting", branch: "develop" },
    { key: "agent/child-run", parent: "mgr-w", state: "running", title: "Child running" },
  ] };
  const TREE_DONE = { nodes: [
    { key: "agent/mgr-d", parent: null, state: "finished", title: "Manager done", branch: "develop" },
    { key: "agent/child-fin", parent: "mgr-d", state: "finished", title: "Child finished" },
  ] };

  it("finished + enfant running → section « En cours » + badge 'orchestre' pulsant", async () => {
    await loadModule(TREE_WAIT);
    // le manager en attente va dans « ● En cours », PAS « Terminés ».
    const item = document.querySelector('.conv-section-running [data-key="agent/mgr-w"]');
    expect(item).not.toBeNull();
    expect(document.querySelector('.conv-section-finished [data-key="agent/mgr-w"]')).toBeNull();
    const badge = item.querySelector(".badge");
    expect(badge.classList.contains("st-run")).toBe(true);
    expect(badge.classList.contains("st-ok")).toBe(false);
    expect(badge.title).toContain("orchestre");
    expect(badge.querySelector(".pui-dot--pulse")).not.toBeNull();
  });

  it("finished + tous enfants terminés → section « Terminés » + badge 'terminé'", async () => {
    await loadModule(TREE_DONE);
    const item = document.querySelector('.conv-section-finished [data-key="agent/mgr-d"]');
    expect(item).not.toBeNull();
    const badge = item.querySelector(".badge");
    expect(badge.classList.contains("st-ok")).toBe(true);
    expect(badge.title).toContain("terminé");
  });
});

// ============================================================================
// REFONTE CARTE SIDEBAR (spec user 2026-07-07) — tests d'acceptation.
//   - carte racine = 2 lignes : L1 dot+profil+heure, L2 = SUJET (title_full).
//   - id/branche retirés de la carte visible -> tooltip (row.title : état+branche+id).
//   - .conv-recap-pill : exactement 1 par carte éligible après plusieurs refresh.
// Contraintes préservées : .conv-item-title.textContent = title court (A4).
// ============================================================================
describe("conversations.js — REFONTE CARTE (spec user)", () => {
  const TREE_CARD = {
    nodes: [
      {
        key: "agent/card-1",
        parent: null,
        state: "running",
        title: "Agent · python-coder · 23:40",
        title_full: "Corrige le bug de duplication des pills dans la sidebar des conversations et refonds la carte.",
        branch: "agent/728f-refonte-carte",
        agent_id: "d72e218094d2",
        has_recap: true,
        started_at: "2026-07-07T21:40:00Z",
      },
    ],
  };
  const cardRow = () => document.querySelector('#conv-list [data-key="agent/card-1"]');

  it("carte = 2 lignes : .conv-item-title (L1, titre court) + .conv-item-subject (L2, sujet)", async () => {
    await loadModule(TREE_CARD);
    const row = cardRow();
    expect(row).not.toBeNull();
    // L1 : le titre court reste inchangé (contrainte A4).
    const titleEl = row.querySelector(".conv-item-title");
    expect(titleEl).not.toBeNull();
    expect(titleEl.textContent).toBe("Agent · python-coder · 23:40");
    // L2 : le SUJET (title_full) est présent dans un élément dédié, tronquable.
    const subjectEl = row.querySelector(".conv-item-subject");
    expect(subjectEl).not.toBeNull();
    expect(subjectEl.textContent).toBe(TREE_CARD.nodes[0].title_full);
  });

  it("le sujet (title_full) est visible et distinct du titre court", async () => {
    await loadModule(TREE_CARD);
    const subjectEl = cardRow().querySelector(".conv-item-subject");
    expect(subjectEl.textContent.length).toBeGreaterThan(0);
    expect(subjectEl.textContent).not.toBe("Agent · python-coder · 23:40");
  });

  it("tooltip de la carte (row.title) porte l'id, la branche et l'état — aucune perte d'info", async () => {
    await loadModule(TREE_CARD);
    const t = cardRow().title;
    expect(t).toBeTruthy();
    expect(t).toContain("d72e218094d2");            // id agent
    expect(t).toContain("agent/728f-refonte-carte"); // branche
    expect(t.toLowerCase()).toMatch(/en cours|running|actif/); // état lisible
  });

  it("exactement 1 .conv-recap-pill par carte éligible après 3 refresh (pas de duplication DOM)", async () => {
    await loadModule(TREE_CARD);
    for (let i = 0; i < 3; i++) {
      await vi.advanceTimersByTimeAsync(8000);
      await flush();
    }
    const pills = cardRow().querySelectorAll(".conv-recap-pill");
    expect(pills.length).toBe(1);
    expect(pills[0].hidden).toBe(false); // has_recap:true -> visible
  });
});

// SPEC : sélecteur Projet dans la bannière d'options de /conversations.
describe("conversations.js — sélecteur projet", () => {
  afterEach(() => {
    // Réinitialise les fixtures mutables entre tests.
    PROJECTS_RESPONSE = PROJECTS_FIXTURE;
    DISPATCH_RESPONSE = { key: "conv-1" };
  });

  function pickProject(slug) {
    const radio = document.querySelector(`#conv-project-panel input[name="conv-project"][value="${slug}"]`);
    radio.checked = true;
    radio.dispatchEvent(new Event("change", { bubbles: true }));
  }

  it("sélection d'un projet → payload dispatch contient project_slug", async () => {
    const fetchMock = await loadModule();
    pickProject("demo-app");
    await submitNew();
    const body = dispatchBody(fetchMock);
    expect(body).toBeTruthy();
    expect(body.project_slug).toBe("demo-app");
  });

  it("aucune sélection explicite → project_slug = 1er projet (plus d'option auto)", async () => {
    const fetchMock = await loadModule();
    // Plus d'option "auto" : sans sélection, le 1er projet réel est retenu.
    await submitNew();
    const body = dispatchBody(fetchMock);
    expect(body).toBeTruthy();
    expect(body.project_slug).toBe("demo-app");
    expect(body.prompt).toBeTruthy(); // le reste du payload intact
  });

  it("persistance : la sélection projet survit à un reload", async () => {
    try { localStorage.setItem("bz.conv.project", "bouzecode_oss"); } catch (_) {}
    await loadModule();
    const radio = document.querySelector('#conv-project-panel input[name="conv-project"][value="bouzecode_oss"]');
    expect(radio).toBeTruthy();
    expect(radio.checked).toBe(true);
    // L'option "auto" (value vide) a été retirée : elle n'existe plus.
    const auto = document.querySelector('#conv-project-panel input[name="conv-project"][value=""]');
    expect(auto).toBeNull();
  });

  it("needs_project=true → bannière ouverte + suggestions visibles", async () => {
    DISPATCH_RESPONSE = { needs_project: true, suggestions: [
      { name: "Demo App", slug: "demo-app" },
      { name: "OSS", slug: "bouzecode_oss" },
    ] };
    const fetchMock = await loadModule();
    await submitNew();
    // Le POST a bien eu lieu.
    expect(dispatchBody(fetchMock)).toBeTruthy();
    // Bannière projet ouverte.
    const toggle = document.getElementById("conv-project-toggle");
    const panel = document.getElementById("conv-project-panel");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(panel.hidden).toBe(false);
    expect(toggle.classList.contains("conv-project-needs")).toBe(true);
    // Suggestions visibles.
    const box = document.getElementById("conv-project-suggestions");
    expect(box.hidden).toBe(false);
    const btns = box.querySelectorAll("button.conv-project-suggestion");
    expect(btns.length).toBe(2);
    expect(btns[0].dataset.slug).toBe("demo-app");
    // Un clic sur une suggestion sélectionne le projet.
    btns[0].click();
    const radio = document.querySelector('#conv-project-panel input[name="conv-project"][value="demo-app"]');
    expect(radio.checked).toBe(true);
  });
});

describe("conversations.js — agent en démarrage (session absente)", () => {
  // Un agent VIVANT dont la session n'existe pas encore (backend renvoie state:"starting")
  // doit apparaître dans la sidebar avec un badge « démarrage… », en section « ● En cours ».
  const STARTING_TREE = {
    nodes: [
      {
        agent_id: "start-1",
        key: "agent/start-1",
        parent: "",
        title: "Nouvelle tâche en démarrage",
        title_full: "Nouvelle tâche en démarrage",
        state: "starting",
        started_at: "2026-07-09T18:00:00",
        saved_at: "",
        turn_count: 0,
        model: "",
        project_slug: "",
        project_name: "",
        repo: "",
        branch: "",
        kind: "work",
        parent_id: "",
      },
    ],
  };

  it("affiche l'agent démarrant avec le badge « démarrage… » en section « En cours »", async () => {
    await loadModule(STARTING_TREE);
    const node = document.querySelector('.conv-section-running [data-key="agent/start-1"]');
    expect(node).not.toBeNull();
    expect(node.textContent).toContain("Nouvelle tâche en démarrage");
    // En sidebar le badge est COMPACT (dot + tooltip, pas de libellé en texte) :
    // le libellé « démarrage… » vit dans le title du .badge.
    const badge = node.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge.className).toContain("st-run");
    expect(badge.title).toBe("démarrage…");
  });

  it("bascule sur le badge normal « en cours » quand la session arrive au polling suivant", async () => {
    // Même agent, mais la session existe désormais (backend renvoie state:"running").
    const runningTree = {
      nodes: [{ ...STARTING_TREE.nodes[0], state: "running" }],
    };
    await loadModule(runningTree);
    const node = document.querySelector('.conv-section-running [data-key="agent/start-1"]');
    expect(node).not.toBeNull();
    // Le badge bascule : title « en cours » (state running), plus « démarrage… ».
    const badge = node.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge.title).toBe("en cours");
    expect(badge.title).not.toBe("démarrage…");
  });
});

// ---------------------------------------------------------------------------
// Rendu OPTIMISTE d'un agent dans la sidebar au submit du prompt.
// Comportement livré : newConversation() pousse un node synthétique
// (key `optimistic:<ts>-<rand>`, state:"starting" → section « En cours »,
// title_full = prompt) et appelle renderList() SYNCHRONEMENT, AVANT le
// 1er `await fetch(/api/dispatch)` → l'entrée apparaît instantanément, sans
// attendre l'aller-retour serveur. reconcileOptimistic() (appelé après chaque
// refreshList réussi) retire l'optimiste dès qu'un vrai node porte le même
// title_full (= 1er message user = le prompt). removeOptimistic() le retire sur
// échec (data.error / needs_project / catch réseau).
// Fixtures DÉRIVÉES du réel : structure /api/agents/tree ({nodes:[...]}),
// /api/dispatch defer (ticket_id sans key), section rendue #conv-list.
// ---------------------------------------------------------------------------
describe("conversations.js — rendu optimiste agent au submit", () => {
  // Comme submitNew() mais SANS flush : on lit le DOM dans le même tick que le
  // submit pour prouver que l'entrée optimiste est rendue AVANT que le fetch
  // /api/dispatch résolve (rendu synchrone = instantanéité).
  function submitNoFlush(prompt) {
    const input = document.getElementById("conv-new-input");
    const form = document.getElementById("conv-new-bar");
    input.value = prompt;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  }

  it("(a) affiche INSTANTANÉMENT une entrée optimiste en « En cours » au submit, avant l'aller-retour serveur", async () => {
    await loadModule(TREE);
    const prompt = "Corrige le bug de login";
    // Submit SANS flush : le fetch /api/dispatch n'a PAS encore résolu.
    submitNoFlush(prompt);

    const opt = document.querySelector('#conv-list [data-key^="optimistic:"]');
    expect(opt).not.toBeNull(); // rendu au même tick, avant la réponse serveur
    // L'entrée optimiste est dans la section « En cours » (state:"starting").
    const optInRunning = document.querySelector('.conv-section-running [data-key^="optimistic:"]');
    expect(optInRunning).not.toBeNull();
    expect(opt.textContent).toContain(prompt);
  });

  it("(b) réconcilie au succès : l'optimiste disparaît quand le vrai node arrive, sans doublon", async () => {
    const prompt = "Ajoute un test optimiste";
    let dispatched = false;
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes("/api/dispatch")) {
        dispatched = true;
        // defer=true → réponse rapide avec ticket_id, SANS key.
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ticket_id: "T-1", deferred: true }) });
      }
      if (url.includes("/api/agents/tree")) {
        // Après le dispatch, le tree ramène le VRAI node (title_full === prompt).
        const nodes = dispatched
          ? [...TREE.nodes, { key: "agent/real-1", parent: null, state: "running", title: prompt, title_full: prompt }]
          : TREE.nodes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes }) });
      }
      if (url.includes("/api/typologies")) return Promise.resolve({ ok: true, json: () => Promise.resolve(TYPOLOGIES_FIXTURE) });
      if (url.includes("/api/projects")) return Promise.resolve({ ok: true, json: () => Promise.resolve(PROJECTS_RESPONSE) });
      if (url.includes("/blocks")) return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    // Submit synchrone : l'optimiste apparaît d'abord…
    submitNoFlush(prompt);
    expect(document.querySelector('#conv-list [data-key^="optimistic:"]')).not.toBeNull();

    // …puis la réponse serveur + refreshList(true) réconcilient.
    await flush();
    await flush();

    // Plus aucun optimiste, exactement UN node portant ce prompt (pas de doublon).
    expect(document.querySelector('#conv-list [data-key^="optimistic:"]')).toBeNull();
    const real = document.querySelectorAll('#conv-list [data-key="agent/real-1"]');
    expect(real.length).toBe(1);
  });

  it("(e) réconcilie l'ONGLET : un onglet ouvert sur la key optimiste est re-ciblé in-place vers la vraie key (pas de doublon, pas d'onglet vide)", async () => {
    const prompt = "Ouvre puis re-cible mon onglet";
    let dispatched = false;
    const blockUrls = [];
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/dispatch")) {
        dispatched = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ticket_id: "T-2", deferred: true }) });
      }
      if (url.includes("/api/agents/tree")) {
        const nodes = dispatched
          ? [...TREE.nodes, { key: "agent/real-1", parent: null, state: "running", title: prompt, title_full: prompt }]
          : TREE.nodes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes }) });
      }
      if (url.includes("/api/typologies")) return Promise.resolve({ ok: true, json: () => Promise.resolve(TYPOLOGIES_FIXTURE) });
      if (url.includes("/api/projects")) return Promise.resolve({ ok: true, json: () => Promise.resolve(PROJECTS_RESPONSE) });
      if (url.includes("/blocks")) {
        blockUrls.push(url);
        return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    // 1) Submit → entrée optimiste rendue instantanément.
    submitNoFlush(prompt);
    const optRow = document.querySelector('#conv-list [data-key^="optimistic:"]');
    expect(optRow).not.toBeNull();
    const optKey = optRow.dataset.key;

    // 2) L'utilisateur CLIQUE sur le row optimiste AVANT que le vrai agent spawn :
    //    un onglet placeholder s'ouvre sur la key optimiste (poll /api/sessions/optimistic:...).
    optRow.click();
    const tabsBox = document.getElementById("conv-tabs");
    expect(tabsBox.querySelectorAll(".conv-tab").length).toBe(1);
    // L'input de l'onglet porte la key optimiste (preuve que l'onglet cible le placeholder).
    expect(document.getElementById("conv-input-" + optKey)).not.toBeNull();

    // 3) Le vrai agent arrive (refreshList) → reconcileOptimistic re-cible l'onglet in-place.
    await flush();
    await flush();

    // Toujours UN SEUL onglet (retarget in-place, pas de 2e onglet parasite).
    expect(tabsBox.querySelectorAll(".conv-tab").length).toBe(1);
    // L'onglet cible désormais la VRAIE key : input renommé, plus d'input optimiste.
    expect(document.getElementById("conv-input-" + optKey)).toBeNull();
    expect(document.getElementById("conv-input-agent/real-1")).not.toBeNull();
    // Le poll re-ciblé interroge bien la vraie session (preuve du retarget du poller).
    expect(blockUrls.some((u) => u.includes("/api/sessions/agent/real-1/blocks"))).toBe(true);
    // La sidebar n'a plus d'optimiste et exactement un vrai node (pas de doublon).
    expect(document.querySelector('#conv-list [data-key^="optimistic:"]')).toBeNull();
    expect(document.querySelectorAll('#conv-list [data-key="agent/real-1"]').length).toBe(1);
  });

  it("(c) échec POST (data.error) : retire l'optimiste et affiche l'erreur", async () => {
    const prompt = "Ceci va échouer";
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/dispatch")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ error: "boum serveur" }) });
      }
      if (url.includes("/api/agents/tree")) return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      if (url.includes("/api/typologies")) return Promise.resolve({ ok: true, json: () => Promise.resolve(TYPOLOGIES_FIXTURE) });
      if (url.includes("/api/projects")) return Promise.resolve({ ok: true, json: () => Promise.resolve(PROJECTS_RESPONSE) });
      if (url.includes("/blocks")) return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    submitNoFlush(prompt);
    expect(document.querySelector('#conv-list [data-key^="optimistic:"]')).not.toBeNull();

    await flush();
    await flush();

    // L'optimiste est retiré et l'erreur serveur est affichée.
    expect(document.querySelector('#conv-list [data-key^="optimistic:"]')).toBeNull();
    expect(document.getElementById("conv-new-error").textContent).toContain("boum serveur");
  });

  it("(d) échec réseau (fetch reject) : retire l'optimiste via le catch", async () => {
    const prompt = "Panne réseau";
    const fetchMock = vi.fn((url) => {
      if (url.includes("/api/dispatch")) {
        return Promise.reject(new Error("network down"));
      }
      if (url.includes("/api/agents/tree")) return Promise.resolve({ ok: true, json: () => Promise.resolve(TREE) });
      if (url.includes("/api/typologies")) return Promise.resolve({ ok: true, json: () => Promise.resolve(TYPOLOGIES_FIXTURE) });
      if (url.includes("/api/projects")) return Promise.resolve({ ok: true, json: () => Promise.resolve(PROJECTS_RESPONSE) });
      if (url.includes("/blocks")) return Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_BLOCKS) });
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
    mountDom();
    global.fetch = fetchMock;
    vi.resetModules();
    await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
    await flush();

    submitNoFlush(prompt);
    expect(document.querySelector('#conv-list [data-key^="optimistic:"]')).not.toBeNull();

    await flush();
    await flush();

    // Le catch retire l'optimiste (pas de node fantôme laissé dans la sidebar).
    expect(document.querySelector('#conv-list [data-key^="optimistic:"]')).toBeNull();
  });
});

