import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Page Agents — panneau d'un agent vu par l'utilisateur (SPEC.md §5.3, §5.4) : progression du
// lancement dans l'onglet, puis bascule sur l'agent né ; libellés du champ de message selon l'état.

function res(status, body) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) });
}
const flush = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };

beforeEach(() => {
  vi.resetModules();
  document.body.innerHTML = `<div id="conv-tabs"></div><div id="conv-panels"><div class="conv-empty"></div></div>`;
  try { localStorage.clear(); } catch (e) { console.warn(e); }
});
afterEach(() => { vi.useRealTimers(); });

const currentStep = () => document.querySelector(".ag-steps__item.is-current").textContent;

describe("onglet d'un agent en lancement", () => {
  it("montre l'étape en cours (environnement, puis démarrage), puis bascule sur l'agent une fois né", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    // Le serveur répond selon l'avancement : environnement, puis démarrage, puis l'agent est né.
    let launchReads = 0;
    const launchReply = () => {
      launchReads += 1;
      if (launchReads <= 2) return { status: { phase_label: "création du worktree", phase_detail: "git worktree add" } };
      return launchReads === 3 ? { status: { phase_label: "démarrage de l'agent" } } : { agent_key: "agent/n1" };
    };
    global.fetch = vi.fn((url) => {
      if (url.startsWith("/api/sessions/launching/t1/blocks")) return res(200, launchReply());
      if (url.startsWith("/api/sessions/agent/n1/blocks")) return res(200, { blocks: [], total: 0, status: { state: "running" }, queue: [] });
      return res(200, {});
    });
    const { initTabs, openTab } = await import("../../static/js/conversations/tabs.js");
    initTabs();
    openTab({ key: "launching/t1", title: "Corrige le bug", launch: { prompt: "Corrige le bug", project_slug: "demo-api", isolation: "worktree" } });
    await vi.advanceTimersByTimeAsync(0);
    expect(currentStep()).toMatch(/Préparation de l'environnement — création du worktree — git worktree add/);
    expect(document.querySelector(".ag-head").textContent).toMatch(/Copie isolée/);
    expect(document.querySelector(".ag-composer__send").textContent).toBe("Mettre en file");
    await vi.advanceTimersByTimeAsync(1600);
    expect(currentStep()).toMatch(/Démarrage de l'agent/);
    await vi.advanceTimersByTimeAsync(1600);
    await vi.advanceTimersByTimeAsync(0);
    expect(global.fetch.mock.calls.some(([u]) => u.startsWith("/api/sessions/agent/n1/blocks"))).toBe(true);
    expect(new URL(location.href).searchParams.get("agent")).toBe("n1");
  });
});

describe("onglet d'un agent né", () => {
  function agentWith(status) {
    global.fetch = vi.fn((url) => (url.startsWith("/api/sessions/agent/a1/blocks")
      ? res(200, { blocks: [], total: 0, status, queue: [] }) : res(200, {})));
  }

  it("lien profond ?agent=<id nu> : ouvre l'onglet de cet agent", async () => {
    agentWith({ state: "finished" });
    window.history.replaceState(null, "", "/conversations?agent=a1");
    const { initTabs, restoreTabs } = await import("../../static/js/conversations/tabs.js");
    initTabs();
    restoreTabs();
    await flush();
    expect(global.fetch.mock.calls.some(([u]) => u === "/api/sessions/agent/a1/blocks?after=0&tail=80")).toBe(true);
    expect(document.querySelector(".ag-tab[aria-selected=true]")).not.toBeNull();
    window.history.replaceState(null, "", "/conversations");
  });

  it.each([
    [{ state: "starting" }, /Démarrage de l'agent/],
    [{ state: "running", phase: "attente_modele" }, /Le modèle lit ta demande/],
    [{ state: "starting", phase: "attente_modele" }, /Le modèle lit ta demande/],
  ])("conversation encore vide (%o) : l'étape du démarrage est affichée", async (status, step) => {
    agentWith(status);
    const { initTabs, openTab } = await import("../../static/js/conversations/tabs.js");
    initTabs();
    openTab({ key: "agent/a1", title: "A" });
    await flush();
    expect(currentStep()).toMatch(step);
  });

  it("conversation terminée sans message : « Aucun message dans cette conversation. »", async () => {
    agentWith({ state: "finished" });
    const { initTabs, openTab } = await import("../../static/js/conversations/tabs.js");
    initTabs();
    openTab({ key: "agent/a1", title: "A" });
    await flush();
    expect(document.querySelector(".ag-thread__state").textContent).toBe("Aucun message dans cette conversation.");
  });
});

describe("champ de message selon l'état de l'agent", () => {
  const cases = [
    ["running", "Mettre en file", false, /à sa prochaine étape/],
    ["awaiting_input", "Répondre", false, /Réponds à l'agent/],
    ["idle", "Envoyer", false, /continuer la conversation/],
    ["crashed", "Continuer avec ce message", false, /reprend là où il s'est arrêté/],
    ["launch_failed", "Envoyer", true, /lancement a échoué/],
    ["archived", "Envoyer", true, /restaure-le/],
  ];
  it.each(cases)("%s → bouton « %s », désactivé=%s", async (state, label, disabled, placeholder) => {
    const { createComposer } = await import("../../static/js/conversations/panel/composer.js");
    const conv = document.createElement("div");
    const c = createComposer({ key: "agent/a" }, { conv: () => conv, scrollToEnd: () => {}, kick: () => {} });
    c.update(state, []);
    expect(c.el.querySelector(".ag-composer__send").textContent).toBe(label);
    expect(c.input.disabled).toBe(disabled);
    expect(c.input.placeholder).toMatch(placeholder);
  });
});

describe("vue Coûts & tours", () => {
  const COSTS = {
    models: { "claude-x": { calls: 2, side_calls: 1, input_tokens: 1200, output_tokens: 300, cache_read_tokens: 5000,
      cache_write_tokens: 800, cache_hit_pct: 81, cost: 0.5, output_estimated_calls: 1 } },
    total: { calls: 2, side_calls: 1, input_tokens: 1200, output_tokens: 300, cache_read_tokens: 5000,
      cache_write_tokens: 800, cache_hit_pct: 81, cost: 0.5, output_estimated_calls: 1 },
  };
  const TURNS = {
    model: "claude-x", system_prompt_tokens: 18000, missing_dumps: false,
    calls: [
      { turn: 1, time: "10:00:00", delta_s: null, input_tokens: 1000, output_tokens: 200, cache_read: 0, cache_create: 800, cache_hit_pct: 0, output_estimated: false, tools: ["Read"], cost: 0.2 },
      { turn: 2, time: "10:00:05", delta_s: 5, input_tokens: 200, output_tokens: 100, cache_read: 5000, cache_create: 0, cache_hit_pct: 96, output_estimated: true, tools: [], cost: 0.1 },
    ],
    side_calls: { count: 1, cost: 0.2 },
    total_cost: 0.5,
  };
  const DETAIL = { turn: 1, wire_message_count: 3, input_tokens: 1000, output_tokens: 200, cache_read: 0, cache_create: 800,
    items: [{ kind: "system", label: "prompt système", est_tokens: 800, cache_status: "new-cache", cache_label: "écrit au cache", content: "…" }],
    response_html: "<p>ok</p>" };

  async function openCosts() {
    global.fetch = vi.fn((url) => {
      if (url.includes("/blocks")) return res(200, { blocks: [], total: 0, status: { state: "finished" }, queue: [] });
      if (/\/costs(\?|$)/.test(url)) return res(200, COSTS);
      if (url.endsWith("/turns")) return res(200, TURNS);
      if (url.endsWith("/turns/1")) return res(200, DETAIL);
      return res(200, {});
    });
    const { initTabs, openTab } = await import("../../static/js/conversations/tabs.js");
    initTabs();
    openTab({ key: "agent/a1", title: "A" });
    await flush();
    document.querySelector(".ag-views [data-view=costs]").click();
    await flush();
    return document.querySelector(".ag-pane--costs");
  }

  it("total servi par l'API (appels annexes compris), jamais une somme des lignes ; aucun symbole monétaire", async () => {
    const pane = await openCosts();
    // Somme des lignes = 0.3 ; l'API annonce 0.5 (annexes compris) : c'est 0.5 qui est affiché.
    expect(pane.querySelector(".ag-costs__intro").textContent).toMatch(/coût total 0\.5000 \(unités du tarif\)/);
    expect(pane.querySelector(".ag-costs__intro").textContent).toMatch(/\+ 1 appel annexe \(0\.2000\)/);
    expect(pane.textContent).toMatch(/Appels annexes .* : 1, inclus dans les totaux/);
    expect(pane.textContent).not.toMatch(/[$€]/);
  });

  it("coût agrégé avec les sous-agents : total servi par l'API + détail par sous-agent", async () => {
    COSTS.sous_agents = [{ agent_id: "s1", titre: "Lot A", cost: 0.25, calls: 3 }, { agent_id: "s2", titre: "Lot B", cost: 0.25, calls: 2 }];
    COSTS.total_avec_sous_agents = 1;
    try {
      const pane = await openCosts();
      expect(fetch.mock.calls.some(([u]) => String(u).includes("/costs?avec_sous_agents=1"))).toBe(true);
      expect(pane.querySelector(".ag-costs__total-tree").textContent).toMatch(/Total avec sous-agents : 1\.0000 unités du tarif \(2 sous-agents\)/);
      expect([...pane.querySelectorAll(".ag-costs__subs td")].map((td) => td.textContent)).toContain("Lot A");
    } finally {
      delete COSTS.sous_agents;
      delete COSTS.total_avec_sous_agents;
    }
  });

  it("sortie estimée : « ~ » et infobulle explicative", async () => {
    const pane = await openCosts();
    const estimated = [...pane.querySelectorAll("td.is-estimated")];
    // Ligne du modèle, ligne Total, puis le tour 2 (le seul dont la sortie est estimée).
    expect(estimated.map((td) => td.textContent)).toEqual(["~300", "~300", "~100"]);
    expect(estimated[0].title).toMatch(/l'API n'a pas renvoyé le compte/);
  });

  it("entrée estimée (flux coupé avant l'usage) : « ~ » sur l'entrée aussi, et une note", async () => {
    TURNS.calls[0].input_estimated = true;
    COSTS.total.input_estimated_calls = 1;
    try {
      const pane = await openCosts();
      const cellules = [...pane.querySelectorAll("td.is-estimated")].map((td) => td.textContent);
      expect(cellules).toContain("~1.2k");
      expect(cellules).toContain("~1.0k");
      expect(pane.textContent).toMatch(/Entrée estimée sur 1 appel/);
    } finally {
      delete TURNS.calls[0].input_estimated;
      delete COSTS.total.input_estimated_calls;
    }
  });

  it("détail d'un tour : bloc système « écrit au cache » et légende des statuts", async () => {
    const pane = await openCosts();
    pane.querySelector(".ag-table__clickable").click();
    await flush();
    const detail = pane.querySelector(".ag-turn-detail");
    expect(detail.querySelector(".ag-payload .badge").textContent).toBe("écrit au cache");
    expect(detail.querySelector(".ag-payload .badge").dataset.tone).toBe("info");
    expect(detail.querySelector(".ag-payload__legend").textContent).toMatch(/écrit au cache = mis en cache à cet appel/);
  });
});

describe("fil paginé d'un agent", () => {
  it("n'ouvre que la dernière page, puis insère les messages précédents au-dessus, dans l'ordre", async () => {
    const bloc = (i) => ({ idx: i, html: `<div class="block user" data-i="${i}">m${i}</div>` });
    const page = (blocks, debut) => res(200, { blocks, total: 102, debut, status: { state: "finished" }, queue: [] });
    global.fetch = vi.fn((url) => {
      if (url.endsWith("/blocks?after=0&tail=80")) return page([bloc(100), bloc(101)], 100);
      if (url.endsWith("/blocks?after=20&before=100")) return page([bloc(20), bloc(21)], 20);
      if (url.endsWith("/blocks?after=0&before=20")) return page([bloc(0)], 0);
      if (url.includes("/blocks")) return page([], 102);
      return res(200, {});
    });
    const { initTabs, openTab } = await import("../../static/js/conversations/tabs.js");
    initTabs();
    openTab({ key: "agent/a1", title: "A" });
    await flush();
    const ordre = () => [...document.querySelectorAll(".ag-thread__msgs [data-i]")].map((el) => el.dataset.i);
    expect(ordre()).toEqual(["100", "101"]);
    const bouton = document.querySelector(".ag-thread__older");
    expect(bouton.hidden).toBe(false);
    expect(bouton.textContent).toMatch(/100/);
    bouton.click();
    await flush();
    expect(ordre()).toEqual(["20", "21", "100", "101"]);
    bouton.click();
    await flush();
    expect(ordre()).toEqual(["0", "20", "21", "100", "101"]);
    expect(document.querySelector(".ag-thread__older")).toBeNull();
  });
});

describe("en-tête : agent sur un code antérieur", () => {
  async function openWithMeta(meta) {
    global.fetch = vi.fn((url) => (url.startsWith("/api/sessions/agent/a1/blocks")
      ? res(200, { blocks: [], total: 0, status: { state: "running" }, queue: [], meta }) : res(200, {})));
    const { initTabs, openTab } = await import("../../static/js/conversations/tabs.js");
    initTabs();
    openTab({ key: "agent/a1", title: "A" });
    await flush();
    return document.querySelector(".ag-head");
  }

  it("la puce « code antérieur » dit les deux commits et conseille de relancer", async () => {
    const head = await openWithMeta({ code_stale: true, code_boot_sha: "a".repeat(40), code_head_sha: "f".repeat(40) });
    const puce = head.querySelector(".ag-head__stale");
    expect(puce).not.toBeNull();
    expect(puce.textContent).toMatch(/code antérieur/);
    expect(puce.title).toMatch(/aaaaaaaa/);
    expect(puce.title).toMatch(/ffffffff/);
    expect(puce.title).toMatch(/[Rr]elance/);
  });

  it("rien quand l'agent est à jour ou que son commit de démarrage est inconnu", async () => {
    expect((await openWithMeta({ code_stale: false, code_boot_sha: "f".repeat(40) })).querySelector(".ag-head__stale")).toBeNull();
    vi.resetModules();
    document.body.innerHTML = `<div id="conv-tabs"></div><div id="conv-panels"><div class="conv-empty"></div></div>`;
    expect((await openWithMeta({})).querySelector(".ag-head__stale")).toBeNull();
  });
});
