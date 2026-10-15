import { describe, it, expect, vi, beforeEach } from "vitest";

// Page Agents — barre de lancement et liste, avec fetch simulé (SPEC.md §5.2, §5.4, R3, R4, R6, R11).

function res(status, body) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) });
}
const flush = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };

const LAUNCH_DOM = `
<form id="conv-new-bar"><textarea id="conv-new-input"></textarea><button id="conv-new-send" type="submit">Lancer</button>
<button type="button" id="ag-chip-repo" class="chip"><span></span></button>
<button type="button" id="ag-repo-add" class="chip">+ Dépôt</button>
<button type="button" id="ag-chip-profile" class="chip"><span></span></button>
<button type="button" id="ag-chip-env" class="chip"><span></span></button>
<div id="conv-new-error"></div></form>`;

describe("barre de lancement", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = LAUNCH_DOM;
    try { localStorage.clear(); } catch (e) { console.warn(e); }
  });

  function routes(extra = {}) {
    return vi.fn((url, init) => {
      if (url === "/api/projects") return res(200, { projects: [{ slug: "demo-api", name: "demo-api", path: "/p/a" }, { slug: "demo-front", name: "demo-front", path: "/p/b" }] });
      if (url === "/api/typologies") return res(200, { typologies: [{ name: "default" }, { name: "reviewer" }] });
      if (extra[url]) return extra[url](init);
      return res(404, { error: "inconnu" });
    });
  }

  it("aucun dépôt n'est deviné : le chip reste « choisir un dépôt » et l'envoi le demande sans perdre le texte", async () => {
    global.fetch = routes();
    const { wireLauncher } = await import("../../static/js/conversations/launcher.js");
    wireLauncher();
    await flush();
    const chip = document.getElementById("ag-chip-repo");
    expect(chip.textContent).toMatch(/choisir un dépôt/);
    expect(chip.dataset.tone).toBe("warn");
    document.getElementById("conv-new-input").value = "Fais X";
    document.getElementById("conv-new-bar").dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    expect(document.getElementById("conv-new-error").textContent).toMatch(/Choisis un dépôt/);
    expect(document.getElementById("conv-new-input").value).toBe("Fais X");
    expect(global.fetch.mock.calls.some(([u]) => u.endsWith("/tickets"))).toBe(false);
    // Le menu des dépôts s'est ouvert pour qu'on choisisse.
    expect(document.querySelector(".menu__list")).not.toBeNull();
  });

  it("ajouter un dépôt est visible : bouton « + Dépôt » et 1re entrée du menu ouvrent le dialogue d'ajout", async () => {
    global.fetch = routes();
    const { wireLauncher } = await import("../../static/js/conversations/launcher.js");
    wireLauncher();
    await flush();
    document.getElementById("ag-chip-repo").click();
    const first = document.querySelector(".menu__item");
    expect(first.textContent).toMatch(/Ajouter un dépôt/);
    first.click();
    await flush();
    expect(document.querySelector(".ag-repos__add")).not.toBeNull();
    document.querySelectorAll(".ag-repos__add").forEach((f) => f.closest("dialog, div")?.remove());
    document.getElementById("ag-repo-add").click();
    await flush();
    expect(document.querySelector(".ag-repos__add")).not.toBeNull();
  });

  it("environnement par défaut : « Copie isolée » (D3) ; le choix d'un autre est mémorisé et envoyé", async () => {
    localStorage.setItem("bz.conv.project", "demo-api");
    let body;
    global.fetch = routes({ "/api/projects/demo-api/tickets": (init) => { body = JSON.parse(init.body); return res(201, { ticket_id: "t7", launch_key: "launching/t7" }); } });
    const { wireLauncher } = await import("../../static/js/conversations/launcher.js");
    wireLauncher();
    await flush();
    const env = document.getElementById("ag-chip-env");
    expect(env.textContent).toMatch(/Copie isolée/);
    env.click();
    [...document.querySelectorAll(".menu__item")].find((b) => /Copie isolée \+ dépendances/.test(b.textContent)).click();
    expect(env.textContent).toMatch(/Copie isolée \+ dépendances/);
    expect(localStorage.getItem("bz.conv.isolation")).toBe("worktree_venv");
    document.getElementById("conv-new-input").value = "Mets à jour les dépendances";
    document.getElementById("conv-new-bar").dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    expect(body.isolation).toBe("worktree_venv");
  });

  it("le dernier dépôt utilisé est proposé ET affiché ; le lancement ouvre un onglet sur la clé de préparation", async () => {
    localStorage.setItem("bz.conv.project", "demo-front");
    let body;
    global.fetch = routes({ "/api/projects/demo-front/tickets": (init) => { body = JSON.parse(init.body); return res(201, { ticket_id: "t42", launch_key: "launching/t42", isolation: "worktree" }); } });
    const store = await import("../../static/js/conversations/store.js");
    const opened = [];
    store.on("open", (o) => opened.push(o));
    const { wireLauncher } = await import("../../static/js/conversations/launcher.js");
    wireLauncher();
    await flush();
    expect(document.getElementById("ag-chip-repo").textContent).toMatch(/demo-front/);
    document.getElementById("conv-new-input").value = "Corrige le bug\n[scn:reply]";
    document.getElementById("conv-new-bar").dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    expect(body).toMatchObject({ title: "Corrige le bug", launch: true, defer: true, isolation: "worktree", typology: "default" });
    expect(opened[0]).toMatchObject({ key: "launching/t42", title: "Corrige le bug" });
    expect(document.getElementById("conv-new-input").value).toBe("");
    expect(document.querySelector(".toast").textContent).toMatch(/Agent lancé/);
  });

  it("?profil=<nom> (bouton « Utiliser ce profil ») présélectionne le profil puis nettoie l'URL", async () => {
    window.history.replaceState(null, "", "/conversations?profil=reviewer");
    global.fetch = routes();
    const { wireLauncher } = await import("../../static/js/conversations/launcher.js");
    wireLauncher();
    await flush();
    expect(document.getElementById("ag-chip-profile").textContent).toMatch(/reviewer/);
    expect(document.querySelector(".toast").textContent).toMatch(/Profil « reviewer » sélectionné/);
    expect(localStorage.getItem("bz.conv.typology")).toBe("reviewer");
    expect(window.location.search).toBe("");
  });

  it("?profil=<inconnu> : erreur dite, profil par défaut conservé", async () => {
    window.history.replaceState(null, "", "/conversations?profil=fantome");
    global.fetch = routes();
    const { wireLauncher } = await import("../../static/js/conversations/launcher.js");
    wireLauncher();
    await flush();
    expect(document.getElementById("ag-chip-profile").textContent).toMatch(/default/);
    expect(document.querySelector(".toast[data-kind=err]").textContent).toMatch(/fantome/);
  });

  it("erreur serveur : message sous la barre, texte conservé, bouton rendu", async () => {
    localStorage.setItem("bz.conv.project", "demo-api");
    global.fetch = routes({ "/api/projects/demo-api/tickets": () => res(503, { error: { code: "env_indisponible", message: "API injoignable" } }) });
    const { wireLauncher } = await import("../../static/js/conversations/launcher.js");
    wireLauncher();
    await flush();
    document.getElementById("conv-new-input").value = "Fais Y";
    document.getElementById("conv-new-bar").dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    expect(document.getElementById("conv-new-error").textContent).toMatch(/API injoignable/);
    expect(document.getElementById("conv-new-input").value).toBe("Fais Y");
    expect(document.getElementById("conv-new-send").disabled).toBe(false);
  });
});

describe("liste des agents", () => {
  const TREE = {
    total_roots: 4,
    nodes: [
      { key: "agent/q1", agent_id: "q1", etat: "awaiting_input", title: "Choisir la base", parent: "dispatcher:manual", question: "Quelle base ?", saved_at: "2026-09-23T10:00:00Z" },
      { key: "agent/r1", agent_id: "r1", etat: "running", title: "Refacto export", parent: "dispatcher:manual", activity_label: "lit export.py", project_name: "demo-api" },
      { key: "agent/f1", agent_id: "f1", etat: "finished", title: "Doc", parent: "dispatcher:manual", tache_titre: "Documenter", micro_id: "m1" },
      { key: "agent/f2", agent_id: "f2", etat: "idle", title: "Manager", parent: "dispatcher:manual" },
      { key: "agent/k1", agent_id: "k1", etat: "finished", title: "Enfant", parent: "f2" },
    ],
  };

  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = "<div id='conv-list'></div><div id='toasts'></div>";
    try { localStorage.clear(); } catch (e) { console.warn(e); }
  });

  it("groupes avec compteurs, état en libellé, activité et tâche liée ; aucune purge au chargement (R11)", async () => {
    global.fetch = vi.fn((url) => (url.startsWith("/api/agents/tree") ? res(200, TREE) : res(404, {})));
    const { startList } = await import("../../static/js/conversations/list.js");
    startList();
    await flush();
    const groups = [...document.querySelectorAll(".ag-group")].map((g) => g.dataset.group);
    expect(groups).toEqual(["a_traiter", "en_cours", "termines", "archives"]);
    const count = (g) => document.querySelector(`.ag-group[data-group=${g}] .count`).textContent;
    expect(count("a_traiter")).toBe("1");
    expect(count("en_cours")).toBe("1");
    expect(count("termines")).toBe("2");
    const text = document.getElementById("conv-list").textContent;
    expect(text).toMatch(/Attend ta réponse/);
    expect(text).toMatch(/lit export\.py/);
    // Le contexte (tâche liée, dépôt, heure, id) est au survol : la carte tient sur deux lignes.
    const hovers = [...document.querySelectorAll(".ag-card__main")].map((m) => m.title).join("\n");
    expect(hovers).toMatch(/tâche : Documenter/);
    expect(text).toMatch(/1 sous-agent/);
    expect(global.fetch.mock.calls.map(([u]) => u).filter((u) => /purge|auto-archive/.test(u))).toEqual([]);
  });

  it("archiver : effet immédiat puis toast « Annuler » qui restaure", async () => {
    const calls = [];
    global.fetch = vi.fn((url, init) => {
      calls.push([url, init && init.method]);
      if (url.startsWith("/api/agents/tree")) return res(200, TREE);
      if (url === "/api/conversations/archive") return res(200, { archived: ["f1"], skipped: [] });
      if (url.endsWith("/restore")) return res(200, { ok: true });
      return res(404, {});
    });
    const { startList } = await import("../../static/js/conversations/list.js");
    startList();
    await flush();
    const card = document.querySelector(".ag-card[data-key='agent/f1']");
    card.querySelector(".ag-card__more").click();
    [...document.querySelectorAll(".menu__item")].find((b) => b.textContent === "Archiver").click();
    // Effet immédiat (avant la réponse serveur) : la carte quitte la liste.
    expect([...document.querySelectorAll(".ag-card")].some((c) => c.dataset.key === "agent/f1")).toBe(false);
    await flush(16);
    const toast = document.querySelector(".toast");
    expect(toast.textContent).toMatch(/archivé/);
    toast.querySelector(".toast__action").click();
    await flush();
    expect(calls.some(([u]) => u === "/api/sessions/agent/f1/restore")).toBe(true);
    expect(document.querySelector(".toast:last-child").textContent).toMatch(/restauré/);
  });

  it("échec de chargement initial : état d'erreur avec Réessayer (jamais « Chargement… » éternel)", async () => {
    global.fetch = vi.fn(() => res(500, { error: "boom" }));
    const { startList } = await import("../../static/js/conversations/list.js");
    startList();
    await flush();
    const list = document.getElementById("conv-list");
    expect(list.querySelector(".error-state").textContent).toMatch(/Impossible de charger la liste/);
    expect(list.querySelector(".error-state button").textContent).toBe("Réessayer");
  });

  function tree(nodes) {
    return vi.fn((url) => (url.startsWith("/api/agents/tree") ? res(200, { total_roots: nodes.length, nodes }) : res(404, {})));
  }
  const cardsIn = (g) => [...document.querySelectorAll(`.ag-group[data-group=${g}] > .ag-group__body > .ag-card`)];

  it("un sous-agent qui pose une question remonte en propre dans « À traiter » (avec son agent principal), les questions avant les arrêts", async () => {
    global.fetch = tree([
      { key: "agent/p", agent_id: "p", etat: "idle", title: "Principal", parent: "dispatcher:manual" },
      { key: "agent/k1", agent_id: "k1", etat: "running", title: "Enfant qui travaille", parent: "p" },
      { key: "agent/k2", agent_id: "k2", etat: "awaiting_input", title: "Enfant qui demande", parent: "agent/p", question: "Quelle base ?" },
      { key: "agent/k3", agent_id: "k3", etat: "crashed", title: "Enfant planté", parent: "p", saved_at: "2026-09-23T07:00:00Z" },
      { key: "agent/c", agent_id: "c", etat: "crashed", title: "Planté", parent: "dispatcher:manual", saved_at: "2026-09-23T08:00:00Z" },
      { key: "agent/v", agent_id: "v", etat: "awaiting_plan_validation", title: "Plan", parent: "dispatcher:manual", question: "Valider le plan ?", saved_at: "2026-09-23T09:00:00Z" },
    ]);
    const { startList } = await import("../../static/js/conversations/list.js");
    startList();
    await flush();
    // Les questions (réponse ou plan à valider) d'abord, puis les agents arrêtés, du plus ancien au plus récent.
    const aTraiter = cardsIn("a_traiter").map((c) => `${c.textContent}\n${c.querySelector(".ag-card__main").title}`);
    expect(aTraiter).toEqual([
      expect.stringContaining("sous-agent de « Principal »"), expect.stringContaining("Plan à valider"),
      expect.stringContaining("Enfant planté"), expect.stringContaining("Planté")]);
    expect(aTraiter[0]).toMatch(/« Quelle base \? »/);
    expect(aTraiter[1]).toMatch(/« Valider le plan \? »/);
    // L'agent principal travaille à travers son sous-agent : il est « en cours », déplié (un enfant attend).
    const principal = cardsIn("en_cours")[0];
    expect(principal.textContent).toMatch(/Principal/);
    const toggle = principal.querySelector(".ag-card__kids-toggle");
    expect(toggle.textContent).toBe("▾ 3 sous-agents · 1 attend ta réponse · 1 arrêté · 1 en cours");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    // Replier est un choix mémorisé qui prime sur l'ouverture automatique.
    toggle.click();
    expect(principal.querySelector(".ag-card__kids").hidden).toBe(true);
    expect(JSON.parse(localStorage.getItem("bz.agents.collapsed"))).toEqual(["agent/p"]);
  });

  it("un sous-agent dont l'agent principal a disparu devient une carte à part entière (jamais perdu)", async () => {
    global.fetch = tree([{ key: "agent/x", agent_id: "x", etat: "finished", title: "Orphelin", parent: "disparu" }]);
    const { startList } = await import("../../static/js/conversations/list.js");
    startList();
    await flush();
    expect(cardsIn("termines").map((c) => c.dataset.key)).toEqual(["agent/x"]);
  });

  it("un lancement échoué et un agent introuvable sont « À traiter » ; un lancement en cours est « En cours »", async () => {
    global.fetch = tree([
      { key: "failed/t2", etat: "launch_failed", title: "Échec", parent: "", launch_error: "dépôt inconnu" },
      { key: "launching/t1", etat: "preparing", title: "Lancement", parent: "" },
      { key: "agent/m", agent_id: "m", etat: "missing", title: "Disparu", parent: "dispatcher:manual" },
    ]);
    const { startList } = await import("../../static/js/conversations/list.js");
    startList();
    await flush();
    const aTraiter = cardsIn("a_traiter").map((c) => c.textContent);
    expect(aTraiter.find((t) => /Échec/.test(t))).toMatch(/Lancement échoué.*dépôt inconnu/s);
    expect(aTraiter.find((t) => /Disparu/.test(t))).toMatch(/Introuvable/);
    expect(cardsIn("en_cours")[0].textContent).toMatch(/Préparation…/);
  });

  it("filtre : tous les mots, sur titre, tâche, dépôt ; un agent principal reste visible si un sous-agent correspond", async () => {
    document.body.innerHTML = `<input id="ag-filter"><button id="ag-filter-clear" hidden></button><div id="ag-search-results" hidden></div>
      <div id='conv-list'></div>`;
    global.fetch = tree([
      { key: "agent/p", agent_id: "p", etat: "idle", title: "Principal", parent: "dispatcher:manual" },
      { key: "agent/k", agent_id: "k", etat: "finished", title: "Migrer DEMODB", parent: "p" },
      { key: "agent/o", agent_id: "o", etat: "finished", title: "Autre", parent: "dispatcher:manual", tache_titre: "Documenter", project_name: "demo-front" },
    ]);
    const { startList } = await import("../../static/js/conversations/list.js");
    const { wireSearch } = await import("../../static/js/conversations/search.js");
    startList();
    wireSearch();
    await flush();
    const filter = document.getElementById("ag-filter");
    const type = (v) => { filter.value = v; filter.dispatchEvent(new Event("input")); };
    type("demodb");
    expect(cardsIn("termines").map((c) => c.dataset.key)).toEqual(["agent/p"]);
    type("documenter front");
    expect(cardsIn("termines").map((c) => c.dataset.key)).toEqual(["agent/o"]);
    type("documenter api");
    expect(cardsIn("termines")).toEqual([]);
    type("zz");
    expect(document.querySelector(".ag-list__empty").textContent).toMatch(/Aucun agent ne correspond à « zz »/);
    expect(document.getElementById("ag-filter-clear").hidden).toBe(false);
  });
});

describe("densité d'une carte d'agent", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = "<div id='conv-list'></div><div id='toasts'></div>";
    try { localStorage.clear(); } catch (e) { console.warn(e); }
  });

  it("titre + UNE ligne (état en texte, puis la précision la plus utile) ; dépôt, branche, heure et id au survol", async () => {
    global.fetch = vi.fn((url) => (url.startsWith("/api/agents/tree")
      ? res(200, { total_roots: 2, nodes: [
        { key: "agent/q", agent_id: "q", etat: "awaiting_input", title: "Choisir la base", parent: "", question: "Quelle base ?",
          project_name: "demo-api", branch: "agent/q1", tache_titre: "Brancher la base", saved_at: "2026-09-23T08:00:00Z" },
        { key: "agent/r", agent_id: "r", etat: "running", title: "Refacto", parent: "", activity_label: "lit export.py",
          tache_titre: "Refacto" },
      ] })
      : res(404, {})));
    const { startList } = await import("../../static/js/conversations/list.js");
    startList();
    await flush();
    const card = document.querySelector(".ag-card[data-key='agent/q']");
    const main = card.querySelector(".ag-card__main");
    expect([...main.children].map((c) => c.className)).toEqual(["ag-card__title", "ag-card__line"]);
    const line = main.querySelector(".ag-card__line");
    expect(line.querySelector(".badge--text").textContent).toMatch(/Attend ta réponse/);
    expect(line.querySelector(".ag-card__detail").textContent).toBe("« Quelle base ? »");
    expect(main.textContent).not.toMatch(/demo-api|agent\/q1/);
    expect(main.title).toMatch(/dépôt : demo-api/);
    expect(main.title).toMatch(/branche : agent\/q1/);
    expect(main.title).toMatch(/tâche : Brancher la base/);
    expect(main.title).toMatch(/#q/);
    const running = document.querySelector(".ag-card[data-key='agent/r'] .ag-card__detail");
    expect(running.textContent).toBe("lit export.py");
  });
});
