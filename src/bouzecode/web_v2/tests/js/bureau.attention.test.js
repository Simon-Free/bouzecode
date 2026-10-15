import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Ce qui t'attend (SPEC §4.2) : chaque motif servi par le serveur dit en clair ce qu'il faut
// faire, et l'action attendue est SUR la carte (bande toujours visible, sans déplier).

import { state, poserLignes } from "../../static/js/bureau/store.js";
import { renderTache, registre } from "../../static/js/bureau/tache.js";

const json = (corps, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });

const tache = (extra = {}) => ({ id: "t1", titre: "Choisir le format", corps: "Choisir le format", statut_ui: "brouillon",
  libelle_statut: "", passages: [], projet_slug: "demo", projet_defaut: "demo", macro_id: "m1", motif: "", ...extra });

function monter(t) {
  poserLignes({ chantiers: [{ macro_id: "m1", titre: "Chantier", etat: "active", projets: ["demo"], lignes: [t] }], non_rattachees: [] });
  document.body.innerHTML = "";
  const el = renderTache(t);
  document.body.appendChild(el);
  return el;
}

const bande = (el) => el.querySelector(".bz-task__attente");
const boutons = (el) => [...bande(el).querySelectorAll("button")].map((b) => b.textContent);
const bouton = (el, texte) => [...el.querySelectorAll("button")].find((b) => b.textContent === texte);
const toasts = () => [...document.querySelectorAll(".toast")].map((t) => t.textContent).join(" ");

beforeEach(() => {
  registre.clear();
  state.deplies = new Set();
  state.projets = [{ slug: "demo", name: "demo" }];
  global.fetch = vi.fn(async () => json({ micro: {}, chantiers: [], non_rattachees: [] }));
});

afterEach(() => { vi.restoreAllMocks(); document.querySelectorAll(".toast").forEach((t) => t.remove()); });

describe("une décision laissée par un agent", () => {
  it("dit « À décider », explique qu'aucun agent n'attend, et propose de noter la décision ou de la confier", () => {
    const el = monter(tache({ statut_ui: "a_decider", motif: "point" }));
    expect(el.dataset.motif).toBe("point");
    expect(el.querySelector(".bz-task__badge").textContent).toContain("À décider");
    expect(el.querySelector(".bz-task__meta").textContent).toContain("Aucun agent n'attend");
    expect(boutons(el)).toEqual(["Noter ma décision…", "Confier à un agent…", "Abandonner"]);
    expect(el.querySelector(".bz-source")).toBeNull();
  });

  it("renvoie à la réponse finale de l'agent qui a laissé le choix : aperçu, texte complet, lien", () => {
    const el = monter(tache({ statut_ui: "a_decider", motif: "point", decision_source: {
      ticket_id: "t-42", slug: "demo", titre: "corriger le login", agent_id: "a1b2c3d4e5f6",
      resume: "J'ai corrigé le login.\nDeux tests ajoutés.", rapport_html: "<p>J'ai corrigé le <b>login</b>.</p>",
    } }));
    const src = el.querySelector(".bz-source");
    expect(src).not.toBeNull();
    expect(src.querySelector("summary").textContent).toContain("a1b2c3d4e5f6");
    expect(src.querySelector(".bz-source__apercu").textContent).toContain("J'ai corrigé le login.");
    expect(src.querySelector(".bz-source__rapport b").textContent).toBe("login");
    expect(src.querySelector(".bz-source__lien").getAttribute("href")).toContain("a1b2c3d4e5f6");
    expect(el.querySelector(".bz-task__meta").textContent).toContain("Aucun agent n'attend");
    expect(boutons(el)).toEqual(["Noter ma décision…", "Confier à un agent…", "Abandonner"]);
  });

  it("« Noter ma décision » l'ajoute au brief et clôt la tâche, avec Annuler", async () => {
    const el = monter(tache({ statut_ui: "a_decider", motif: "point" }));
    bouton(el, "Noter ma décision…").click();
    const zone = el.querySelector(".bz-consigne textarea");
    expect(zone.getAttribute("aria-label")).toBe("Ta décision");
    bouton(el, "Noter et clore").click();
    await vi.waitFor(() => expect(el.querySelector(".bz-consigne .field__error").textContent).toBe("Écris ta décision."));
    zone.value = "On garde le JSON";
    await vi.waitFor(() => expect(bouton(el, "Noter et clore")).toBeTruthy());
    bouton(el, "Noter et clore").click();
    await vi.waitFor(() => expect(toasts()).toContain("Décision notée — tâche close"));
    const [url, init] = fetch.mock.calls.find(([u]) => String(u).includes("/etat"));
    expect(url).toContain("/api/micros/t1/etat");
    expect(JSON.parse(init.body)).toEqual({ etat: "faite", pourquoi: "Décision : On garde le JSON" });
    expect(toasts()).toContain("Annuler");
  });
});

describe("un travail rendu à vérifier", () => {
  const passage = { numero: 1, ticket_id: "k1", agent_id: "a1", etat: "finished", integrable: true, integre: false,
    recap: { resume: "3 fichiers modifiés" } };

  it("« À vérifier » : Valider et clore, Renvoyer avec un retour, Intégrer, Voir le travail", () => {
    const el = monter(tache({ statut_ui: "a_relire", motif: "livraison", passages: [passage] }));
    expect(el.querySelector(".bz-task__badge").textContent).toContain("À vérifier");
    expect(boutons(el)).toEqual(["Valider et clore", "Renvoyer avec un retour…", "Intégrer", "Voir le travail"]);
    expect([...bande(el).querySelectorAll("a")].map((a) => a.textContent)).toEqual(["Voir l'agent"]);
  });

  it("« Valider et clore » classe la tâche faite et le dit, avec Annuler", async () => {
    const el = monter(tache({ statut_ui: "a_relire", motif: "livraison", passages: [{ ...passage, integrable: false }] }));
    expect(boutons(el)).not.toContain("Intégrer");
    bouton(el, "Valider et clore").click();
    await vi.waitFor(() => expect(toasts()).toContain("Tâche validée et close"));
    const [, init] = fetch.mock.calls.find(([u]) => String(u).includes("/etat"));
    expect(JSON.parse(init.body).etat).toBe("faite");
  });

});

describe("un agent arrêté avant la fin, ou qui n'a pas démarré", () => {
  const passage = { numero: 1, ticket_id: "k1", agent_id: "a1", etat: "crashed" };

  it("planté et joignable : Continuer en premier, puis Relancer", () => {
    const el = monter(tache({ statut_ui: "en_echec", motif: "plante", joignable: true, raison_echec: "L'agent s'est arrêté sans réponse finale",
      passages: [passage] }));
    expect(el.querySelector(".bz-task__badge").textContent).toContain("Arrêté sans finir");
    expect(el.querySelector(".bz-task__meta").textContent).toBe("L'agent s'est arrêté sans réponse finale");
    expect(boutons(el)).toEqual(["Continuer…", "Relancer", "Abandonner"]);
    expect(bouton(el, "Continuer…").className).toContain("btn--primary");
  });

  it("arrêté par toi : dit que c'est un arrêt voulu, pas un plantage", () => {
    const el = monter(tache({ statut_ui: "en_echec", motif: "arrete", joignable: false, raison_echec: "Arrêté à ta demande",
      passages: [passage] }));
    expect(el.querySelector(".bz-task__badge").textContent).toContain("Arrêté par toi");
    expect(boutons(el)).toEqual(["Relancer", "Abandonner"]);
  });

  it("lancement impossible : action manuelle, « Corriger et relancer… »", () => {
    const el = monter(tache({ statut_ui: "en_echec", motif: "lancement", raison_echec: "Lancement échoué : dépôt inconnu",
      passages: [{ ...passage, agent_id: "", etat: "launch_failed" }] }));
    expect(el.querySelector(".bz-task__badge").textContent).toContain("Lancement échoué");
    expect(el.querySelector(".bz-task__meta").textContent).toContain("dépôt inconnu");
    expect(boutons(el)).toEqual(["Corriger et relancer…", "Abandonner"]);
  });
});

describe("une tâche qui n'attend rien de toi", () => {
  it("n'a pas de bande ; ses gestes sont dans le détail", () => {
    const el = monter(tache());
    expect(bande(el).hidden).toBe(true);
    expect(el.classList.contains("is-attention")).toBe(false);
  });
});

describe("poignée de déplacement", () => {
  it("est un bouton : un clic (ou Entrée) ouvre « Déplacer vers… » avec les chantiers", () => {
    if (typeof HTMLDialogElement === "undefined" || !HTMLDialogElement.prototype.showModal) return;
    const el = monter(tache());
    const grip = el.querySelector(".bz-grip");
    expect(grip.tagName).toBe("BUTTON");
    expect(grip.getAttribute("aria-label")).toBe("Déplacer la tâche vers un autre chantier");
    grip.click();
    const dlg = document.querySelector("dialog.ui-dialog");
    expect(dlg.textContent).toContain("Déplacer vers…");
    expect([...dlg.querySelectorAll(".bz-deplacer__choix")].map((b) => [b.textContent, b.disabled]))
      .toEqual([["Chantier — actuel", true], ["Sans chantier", false]]);
    dlg.remove();
  });
});
