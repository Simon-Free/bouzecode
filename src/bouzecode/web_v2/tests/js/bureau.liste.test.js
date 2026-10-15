import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Liste du Bureau (static/js/bureau/liste.js, vue_statut.js, vue_chantier.js, attente.js, tache.js)
// rendue dans happy-dom à partir de /api/lignes et /api/inbox figés : les DEUX modes de tri
// (Statut | Chantier), chaque tâche une seule fois, le point qui attend porté par sa tâche,
// les points hors tâche, la recherche, le rendu keyé et la protection de l'édition (R8).

import { state } from "../../static/js/bureau/store.js";
import { rendreListe, wireListe } from "../../static/js/bureau/liste.js";
import { registre } from "../../static/js/bureau/tache.js";
import { classerTache, rouvrirTache } from "../../static/js/bureau/actions.js";

function tache(id, statut, extra = {}) {
  const seg = { brouillon: "a_lancer", a_relire: "a_moi", a_repondre: "a_moi", en_cours: "en_cours", faite: "archivees",
    en_echec: "a_moi", a_decider: "a_moi", abandonnee: "archivees" }[statut];
  return { id, titre: `Tâche ${id}`, corps: `brief ${id}`, statut_ui: statut, segment: seg, libelle_statut: statut,
    passages: [], projet_slug: "demo", projet_defaut: "demo", updated_at: "2026-09-23T10:00:00", ...extra };
}

function donnees() {
  return {
    chantiers: [
      { macro_id: "c1", titre: "Chantier un", etat: "active", projets: ["demo"], compte_ui: {},
        lignes: [tache("t1", "brouillon"), tache("t2", "a_relire"), tache("t3", "en_cours"), tache("t6", "faite")] },
      { macro_id: "c2", titre: "Chantier deux", etat: "active", projets: [], compte_ui: {}, lignes: [tache("t4", "a_repondre")] },
    ],
    non_rattachees: [tache("t5", "brouillon", { titre: "Aiguille rare" })],
    titre_non_rattachees: "Sans chantier",
    stats: {},
  };
}

const QUESTION_T4 = { id: "question:a4", type: "question", urgence: 0, titre: "Tâche t4", agent_id: "a4",
  tache: { micro_id: "t4", titre: "Tâche t4", chantier: "Chantier deux" },
  question: { texte: "Quelle base ?", options: [{ label: "PostgreSQL" }, { label: "SQLite" }], allow_freetext: true },
  actions: ["repondre", "ouvrir"] };
const HORS_TACHE = { id: "question:a9", type: "question", urgence: 0, titre: "Conversation libre", agent_id: "a9", tache: null,
  question: { texte: "On y va ?", options: ["Oui"], allow_freetext: true }, actions: ["repondre", "ouvrir"] };

function monterDom() {
  document.body.innerHTML = `
    <div id="bz-mode"><button data-mode="statut"></button><button data-mode="chantier"></button></div>
    <input id="bz-search"><div id="lignes-liste"></div><form id="chantier-nouveau" hidden></form>`;
}

const rendre = () => rendreListe();
const ids = () => [...document.querySelectorAll("#lignes-liste .bz-task[data-id^='t']")].map((el) => el.dataset.id);
const idsDe = (sel) => [...document.querySelectorAll(`${sel} .bz-task`)].map((el) => el.dataset.id);

beforeEach(() => {
  registre.clear();
  monterDom();
  localStorage.clear();
  state.lignes = donnees();
  state.inbox = { items: [QUESTION_T4, HORS_TACHE], compte: 2 };
  state.projets = [{ slug: "demo", name: "demo" }];
  state.recherche = "";
  state.mode = "statut";
  state.deplies = new Set();
  state.replies = new Set();
  state.archivesOuvertes = new Set();
});

afterEach(() => { vi.restoreAllMocks(); });

describe("bascule entre les deux modes", () => {
  it("un clic sur « Chantier » change la vue, marque le bouton et mémorise le choix", () => {
    wireListe();
    window.addEventListener("bz:render", rendre);
    rendre();
    expect(document.querySelector("[data-mode='statut']").getAttribute("aria-pressed")).toBe("true");
    document.querySelector("[data-mode='chantier']").click();
    window.removeEventListener("bz:render", rendre);
    expect(document.querySelector("[data-mode='chantier']").getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector(".bz-ch[data-chantier='c1']")).not.toBeNull();
    expect(document.querySelector(".bz-sec[data-sec='a_moi']")).toBeNull();
    expect(JSON.parse(localStorage.getItem("bz.bureau.prefs")).mode).toBe("chantier");
    // « + Nouveau chantier » n'existe qu'en mode Chantier.
    expect(document.getElementById("chantier-nouveau").hidden).toBe(false);
  });

  it("les flèches du clavier passent d'un mode à l'autre", () => {
    wireListe();
    window.addEventListener("bz:render", rendre);
    rendre();
    document.getElementById("bz-mode").dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    window.removeEventListener("bz:render", rendre);
    expect(state.mode).toBe("chantier");
  });
});

describe("mode Statut", () => {
  it("range les tâches en À traiter / En cours / À lancer, archivées repliées, chacune une seule fois", () => {
    rendre();
    expect(idsDe(".bz-sec[data-sec='a_moi']")).toEqual(["question:a9", "t4", "t2"]);
    // « À traiter » est groupé par ce qu'il faut faire : décider (questions), puis vérifier.
    expect(idsDe(".bz-cat[data-cat='decider']")).toEqual(["question:a9", "t4"]);
    expect(idsDe(".bz-cat[data-cat='verifier']")).toEqual(["t2"]);
    expect(document.querySelector(".bz-cat[data-cat='reprendre']")).toBeNull();
    expect(idsDe(".bz-sec[data-sec='en_cours']")).toEqual(["t3"]);
    expect(idsDe(".bz-sec[data-sec='a_lancer']")).toEqual(["t1", "t5"]);
    expect(idsDe(".bz-sec[data-sec='archivees']")).toEqual([]);
    const bascule = document.querySelector(".bz-sec[data-sec='archivees'] .bz-sec__bascule");
    expect(bascule.textContent).toContain("Archivées (1)");
    expect(new Set(ids()).size).toBe(ids().length);
  });

  it("rappelle le chantier de chaque tâche en étiquette discrète", () => {
    rendre();
    const t2 = document.querySelector(".bz-task[data-id='t2'] .bz-task__chantier");
    expect(t2.textContent).toBe("Chantier un");
    expect(document.querySelector(".bz-task[data-id='t5'] .bz-task__chantier").textContent).toBe("Sans chantier");
  });

  it("ouvrir les archivées les montre et le mémorise", () => {
    window.addEventListener("bz:render", rendre);
    rendre();
    document.querySelector(".bz-sec[data-sec='archivees'] .bz-sec__bascule").click();
    window.removeEventListener("bz:render", rendre);
    expect(idsDe(".bz-sec[data-sec='archivees']")).toEqual(["t6"]);
    expect(JSON.parse(localStorage.getItem("bz.bureau.prefs")).archivesOuvertes).toContain("statut");
  });
});

describe("mode Chantier", () => {
  beforeEach(() => { state.mode = "chantier"; });

  it("un bloc par chantier, les tâches qui t'attendent en tête, les archivées repliées en bas", () => {
    rendre();
    expect(idsDe(".bz-ch[data-chantier='c1'] .bz-ch__corps")).toEqual(["t2", "t3", "t1"]);
    expect(document.querySelector(".bz-ch[data-chantier='c1'] .bz-arch__btn").textContent).toContain("1 archivée");
    expect(idsDe(".bz-ch[data-chantier='c1'] .bz-arch__corps")).toEqual([]);
    expect(idsDe(".bz-ch[data-chantier='sans']")).toEqual(["t5"]);
    expect(new Set(ids()).size).toBe(ids().length);
  });

  it("montre « Hors chantier » en tête seulement s'il y a des points d'agents sans tâche", () => {
    rendre();
    const blocs = [...document.getElementById("lignes-liste").children];
    expect(blocs[0].dataset.sec).toBe("hors");
    expect(idsDe(".bz-sec[data-sec='hors']")).toEqual(["question:a9"]);
    state.inbox = { items: [QUESTION_T4], compte: 1 };
    rendre();
    expect(document.querySelector(".bz-sec[data-sec='hors']")).toBeNull();
  });
});

describe("ce qui t'attend, porté par la tâche", () => {
  it("la tâche est surlignée, dit ce qu'il faut faire, et la question se répond SUR la carte, sans la déplier", () => {
    rendre();
    const t4 = document.querySelector(".bz-task[data-id='t4']");
    expect(t4.classList.contains("is-attention")).toBe(true);
    expect(t4.classList.contains("is-open")).toBe(false);
    expect(t4.querySelector(".bz-task__badge").textContent).toContain("Attend ta réponse");
    const bande = t4.querySelector(".bz-task__attente");
    expect(bande.hidden).toBe(false);
    expect(bande.querySelector(".bz-q__texte").textContent).toBe("Quelle base ?");
    expect([...bande.querySelectorAll(".bz-q__opt")].map((b) => b.textContent)).toEqual(["PostgreSQL", "SQLite"]);
    expect(t4.querySelectorAll(".bz-q")).toHaveLength(1);
    // Pas d'action « au survol » en doublon : les gestes attendus sont déjà visibles.
    expect(t4.querySelector(".bz-task__action button")).toBeNull();
  });

  it("une ligne repliée ne montre que l'état, le titre et une ligne secondaire (le reste en infobulle)", () => {
    rendre();
    const t1 = document.querySelector(".bz-task[data-id='t1']");
    expect(t1.querySelector(".bz-task__meta").hidden).toBe(true);
    expect(t1.querySelector(".bz-task__attente").hidden).toBe(true);
    expect(t1.querySelector(".bz-task__row").title).toContain("dépôt demo");
  });

  it("une question re-servie à l'identique n'est pas redessinée (le clic en cours n'est pas perdu)", () => {
    rendre();
    const t4 = document.querySelector(".bz-task[data-id='t4']");
    const bloc = t4.querySelector(".bz-q");
    state.inbox = { items: [{ ...QUESTION_T4, question: { ...QUESTION_T4.question, options: ["PostgreSQL", "SQLite"] } }], compte: 1 };
    rendre();
    expect(t4.querySelector(".bz-q")).toBe(bloc);
  });

  it("un point hors tâche montre sa question et ses gestes sans rien déplier", () => {
    rendre();
    const p = document.querySelector(".bz-point[data-id='question:a9']");
    expect(p.querySelector(".bz-task__badge").textContent).toContain("Attend ta réponse");
    expect(p.querySelector(".bz-q__texte").textContent).toBe("On y va ?");
    const lien = [...p.querySelectorAll("a")].find((a) => a.textContent === "Ouvrir la conversation");
    expect(lien.getAttribute("href")).toBe("/conversations?agent=a9");
  });
});

describe("recherche", () => {
  it("filtre les deux modes pareil, sans accents ni casse, et le dit quand rien ne correspond", () => {
    state.recherche = "aiguille RARE";
    rendre();
    expect(ids()).toEqual(["t5"]);
    state.mode = "chantier";
    rendre();
    expect(ids()).toEqual(["t5"]);
    state.recherche = "introuvable";
    rendre();
    expect(document.querySelector("#lignes-liste .empty").textContent).toContain("Aucune tâche pour « introuvable »");
  });
});

describe("rendu keyé et protection de l'édition", () => {
  it("garde les mêmes nœuds d'un rafraîchissement à l'autre, et d'un mode à l'autre", () => {
    rendre();
    const avant = document.querySelector(".bz-task[data-id='t1']");
    state.lignes = donnees();
    rendre();
    expect(document.querySelector(".bz-task[data-id='t1']")).toBe(avant);
    state.mode = "chantier";
    rendre();
    expect(document.querySelector(".bz-task[data-id='t1']")).toBe(avant);
  });

  it("n'écrase pas un brief modifié et garde la tâche visible même si son statut change", () => {
    rendre();
    const t1 = document.querySelector(".bz-task[data-id='t1']");
    t1.querySelector(".bz-task__titre").click();
    const brief = t1.querySelector(".bz-ed__brief");
    brief.value = "en cours d'écriture";
    brief.dispatchEvent(new Event("input", { bubbles: true }));
    const d = donnees();
    d.chantiers[0].lignes[0] = tache("t1", "en_cours", { corps: "version serveur" });
    state.lignes = d;
    rendre();
    const encore = document.querySelector(".bz-task[data-id='t1']");
    expect(encore).toBe(t1);
    expect(encore.querySelector(".bz-ed__brief").value).toBe("en cours d'écriture");
  });
});

describe("classer / rouvrir : les agents archivés avec la tâche sont annoncés", () => {
  const reponse = (corps) => vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(corps), { status: 200, headers: { "Content-Type": "application/json" } }));
  const toasts = () => [...document.querySelectorAll(".toast")].map((t) => t.textContent);

  it("« Tâche classée faite — 2 agents archivés » avec Annuler", async () => {
    reponse({ micro: {}, archives: { tickets: 1, conversations: 2 } });
    await classerTache("t2", "faite", "Tâche classée faite");
    expect(toasts().join(" ")).toContain("Tâche classée faite — 2 agents archivés.");
    expect(toasts().join(" ")).toContain("Annuler");
  });

  it("« Tâche rouverte — 1 agent restauré » ; sans champ, le message reste simple", async () => {
    reponse({ micro: {}, restaures: { tickets: 1, conversations: 1 } });
    await rouvrirTache("t2");
    expect(toasts().join(" ")).toContain("Tâche rouverte — 1 agent restauré.");
    document.querySelectorAll(".toast").forEach((t) => t.remove());
    reponse({ micro: {} });
    await classerTache("t2", "abandonnee", "Tâche abandonnée");
    expect(toasts().join(" ")).toContain("Tâche abandonnée.");
  });
});
