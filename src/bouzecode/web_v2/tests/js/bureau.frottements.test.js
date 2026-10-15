import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Frottements relevés en pilotant le Bureau avec un vrai modèle (2026-09-24) : infobulle
// « Sans chantier » à tort, deux « Lancer » à la fois, « Continuer » sans message possible,
// tâche restée « À relire » pendant que l'agent reprenait, erreur d'envoi invisible.

//  Modules rechargés à chaque test : store.js garde les reprises optimistes dans une Map privée
//  (10 s) ; un test qui clique « Continuer… » laissait la tâche t1 « Reprise… » pour le suivant,
//  et « dépliée, un seul Lancer » échouait selon l'ordre d'exécution (--sequence.shuffle).
let state, poserLignes, marquerReprise, renderTache, registre, deplier;

const json = (corps, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });

const tache = (extra = {}) => ({ id: "t1", titre: "Scraper le Kangourou", corps: "Scraper le Kangourou", statut_ui: "brouillon",
  libelle_statut: "Brouillon", passages: [], projet_slug: "demo", projet_defaut: "demo", ...extra });

function chantierAvec(t) {
  return { chantiers: [{ macro_id: "m1", titre: "Portail des énigmes", etat: "active", projets: ["demo"], lignes: [t] }], non_rattachees: [] };
}

function monter(t, { deplie = false } = {}) {
  document.body.innerHTML = "";
  const el = renderTache(t);
  document.body.appendChild(el);
  if (deplie) deplier(registre.get(t.id), true, null, false);
  return el;
}

const visibles = (el, texte) => [...el.querySelectorAll("button")]
  .filter((b) => b.textContent === texte && !b.closest("[hidden]"));

beforeEach(async () => {
  vi.resetModules();
  ({ state, poserLignes, marquerReprise } = await import("../../static/js/bureau/store.js"));
  ({ renderTache, registre, deplier } = await import("../../static/js/bureau/tache.js"));
  registre.clear();
  state.deplies = new Set();
  state.projets = [{ slug: "demo", name: "demo" }];
});

afterEach(() => { vi.restoreAllMocks(); });

describe("frottements du pilote", () => {
  it("l'infobulle d'une tâche nomme son chantier, dès le chargement (mode Chantier compris)", () => {
    const t = tache();
    poserLignes(chantierAvec(t));
    const el = monter(t);
    expect(el.querySelector(".bz-task__row").title).toMatch(/Portail des énigmes/);
    expect(el.querySelector(".bz-task__row").title).not.toMatch(/Sans chantier/);
  });

  it("dépliée, une tâche n'offre qu'UN bouton « Lancer »", () => {
    const t = tache();
    poserLignes(chantierAvec(t));
    const el = monter(t, { deplie: true });
    expect(visibles(el, "Lancer")).toHaveLength(1);
    deplier(registre.get(t.id), false);
    expect(el.querySelector(".bz-task__action").hidden).toBe(false);
  });

  it("« Continuer… » ouvre un message optionnel, l'envoie avec la reprise, et la tâche passe « En cours » aussitôt", async () => {
    const t = tache({ statut_ui: "en_echec", libelle_statut: "En échec", joignable: true,
      passages: [{ agent_id: "a1", ticket_id: "k1", numero: 1, etat: "crashed" }] });
    poserLignes(chantierAvec(t));
    global.fetch = vi.fn(async (url, init) => {
      if (String(url).includes("/relancer")) return json({ ok: true, mode: "continuer", agent_id: "a1" });
      return json({ chantiers: [], non_rattachees: [] });
    });
    const el = monter(t, { deplie: true });
    visibles(el, "Continuer…")[0].click();
    const champ = el.querySelector(".bz-consigne textarea");
    expect(champ.getAttribute("aria-label")).toBe("Message pour l'agent (optionnel)");
    champ.value = "le test X échoue encore";
    el.querySelector(".bz-consigne .btn--primary").click();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    const [, init] = fetch.mock.calls.find(([u]) => String(u).includes("/relancer"));
    expect(JSON.parse(init.body)).toMatchObject({ mode: "continuer", retour: "le test X échoue encore" });
    await vi.waitFor(() => expect(t.statut_ui).toBe("en_cours"));
    expect(t.libelle_statut).toBe("Reprise…");
  });

  it("la reprise optimiste tient face à un poll en retard, puis cède quand le serveur confirme", () => {
    const t = tache({ statut_ui: "a_relire", libelle_statut: "À relire" });
    poserLignes(chantierAvec(t));
    marquerReprise("t1");
    const retard = tache({ statut_ui: "a_relire", libelle_statut: "À relire" });
    poserLignes(chantierAvec(retard));
    expect(retard.statut_ui).toBe("en_cours");
    const confirme = tache({ statut_ui: "a_repondre", libelle_statut: "Attend ta réponse" });
    poserLignes(chantierAvec(confirme));
    expect(confirme.statut_ui).toBe("a_repondre");
    const ensuite = tache({ statut_ui: "a_relire", libelle_statut: "À relire" });
    poserLignes(chantierAvec(ensuite));
    expect(ensuite.statut_ui).toBe("a_relire");
  });

  it("une erreur d'envoi de consigne est affichée sous le champ, texte conservé (plus de 409 muet)", async () => {
    const t = tache({ statut_ui: "en_cours", libelle_statut: "En cours", agent_actif: true,
      passages: [{ agent_id: "a1", ticket_id: "k1", numero: 1, etat: "running" }] });
    poserLignes(chantierAvec(t));
    global.fetch = vi.fn(async () => json({ error: "l'agent n'a pas pu recevoir le message" }, 409));
    const el = monter(t, { deplie: true });
    visibles(el, "Ajouter une consigne…")[0].click();
    const champ = el.querySelector(".bz-consigne textarea");
    champ.value = "pense au cas vide";
    el.querySelector(".bz-consigne .btn--primary").click();
    await vi.waitFor(() => expect(el.querySelector(".bz-consigne .field__error").textContent)
      .toMatch(/Consigne non transmise : l'agent n'a pas pu recevoir le message/));
    expect(el.querySelector(".bz-consigne textarea").value).toBe("pense au cas vide");
  });
});
