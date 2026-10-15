import { describe, it, expect, beforeEach } from "vitest";

// Tâche classée sans être lancée (SPEC §4.6) : la carte dit ce qu'elle est devenue (Faite par…,
// Doublon de…, Caduque), le commentaire, qui l'a dit et quand ; le détail garde l'historique des
// classements rouverts ; le menu ⋯ propose les trois gestes, sauf si un agent y travaille.

import { state } from "../../static/js/bureau/store.js";
import { rendreListe } from "../../static/js/bureau/liste.js";
import { registre, deplier } from "../../static/js/bureau/tache.js";
import { texteClassement, texteHistorique, dateCourte } from "../../static/js/bureau/classement.js";
import { entreesClassement } from "../../static/js/bureau/classer.js";

const FAITE_PAR_L_ASSISTANT = {
  motif: "faite", libelle: "Faite", auteur: "assistant", at: "2026-09-25T03:12:40",
  commentaire: "fait dans la tâche 84fef31c, tour de retours du 25/09 (commit 0059681)",
  lien: { id: "84fef31c", titre: "Scraper les énigmes" }, rouvert_at: "", rouvert_par: "",
};

describe("la phrase d'une tâche classée", () => {
  it("fait ailleurs, dit par l'assistant : où, pourquoi, qui, quand", () => {
    expect(texteClassement(FAITE_PAR_L_ASSISTANT)).toBe(
      "Faite par « Scraper les énigmes » — fait dans la tâche 84fef31c, tour de retours du 25/09 " +
      "(commit 0059681) (commentaire de l'assistant, 25/09 03:12)");
  });

  it("doublon marqué par toi, sans commentaire", () => {
    expect(texteClassement({ motif: "doublon", libelle: "Doublon", auteur: "humain", commentaire: "",
      at: "2026-09-25T09:05:00", lien: { id: "2f38555a", titre: "Étendre le scraping" } }))
      .toBe("Doublon de « Étendre le scraping » (marquée par toi, 25/09 09:05)");
  });

  it("caduque avec ton commentaire", () => {
    expect(texteClassement({ motif: "caduque", libelle: "Caduque", auteur: "humain", lien: null,
      commentaire: "le worktree n'existe plus", at: "2026-09-25T09:05:00" }))
      .toBe("Caduque — le worktree n'existe plus (ton commentaire, 25/09 09:05)");
  });

  it("un classement rouvert le dit dans l'historique", () => {
    expect(texteHistorique({ ...FAITE_PAR_L_ASSISTANT, rouvert_at: "2026-09-25T10:00:00", rouvert_par: "humain" }))
      .toMatch(/— rouverte 25\/09 10:00 par toi$/);
  });

  it("rien sans classement, et une date illisible ne casse rien", () => {
    expect(texteClassement(null)).toBe("");
    expect(dateCourte("pas une date")).toBe("");
  });
});

function tache(extra) {
  return { id: "t1", titre: "Corriger les 10 points", corps: "brief", statut_ui: "faite", segment: "archivees",
    libelle_statut: "Faite", passages: [], projet_slug: "demo", projet_defaut: "demo", macro_id: "c1",
    updated_at: "2026-09-25T03:12:40", precisions: [], classement: null, classements: [], ...extra };
}

function rendreAvec(t) {
  state.lignes = { chantiers: [{ macro_id: "c1", titre: "Portail", etat: "active", projets: [], compte_ui: {}, lignes: [t] }],
    non_rattachees: [], titre_non_rattachees: "Sans chantier", stats: {} };
  rendreListe();
  return document.querySelector(".bz-task[data-id='t1']");
}

beforeEach(() => {
  registre.clear();
  document.body.innerHTML = `<div id="bz-mode"><button data-mode="statut"></button><button data-mode="chantier"></button></div>
    <input id="bz-search"><div id="lignes-liste"></div><form id="chantier-nouveau" hidden></form>`;
  localStorage.clear();
  Object.assign(state, { inbox: { items: [], compte: 0 }, projets: [{ slug: "demo", name: "demo" }], recherche: "",
    mode: "statut", deplies: new Set(), replies: new Set(), archivesOuvertes: new Set(["statut"]) });
});

describe("sur la carte, dans les archivées", () => {
  it("la ligne dit pourquoi, et le mot d'état est celui du classement", () => {
    const doublon = { motif: "doublon", libelle: "Doublon", auteur: "assistant", commentaire: "même sujet",
      at: "2026-09-25T03:12:40", lien: { id: "t2", titre: "Étendre le scraping" }, rouvert_at: "" };
    const el = rendreAvec(tache({ statut_ui: "abandonnee", libelle_statut: "Abandonnée", classement: doublon,
      classements: [doublon] }));
    expect(el.querySelector(".bz-task__meta").textContent)
      .toBe("Doublon de « Étendre le scraping » — même sujet (commentaire de l'assistant, 25/09 03:12)");
    expect(el.querySelector(".bz-task__badge").textContent).toContain("Doublon");
  });

  it("dépliée, elle montre l'historique, le classement rouvert compris", () => {
    const ancien = { motif: "caduque", libelle: "Caduque", auteur: "humain", commentaire: "plus utile",
      at: "2026-09-24T20:00:00", lien: null, rouvert_at: "2026-09-24T21:00:00", rouvert_par: "humain" };
    rendreAvec(tache({ classement: FAITE_PAR_L_ASSISTANT, classements: [ancien, FAITE_PAR_L_ASSISTANT] }));
    deplier(registre.get("t1"), true);
    const items = [...document.querySelectorAll(".bz-classement")].map((li) => li.textContent);
    expect(items).toHaveLength(2);
    expect(items[0]).toContain("Faite par « Scraper les énigmes »");
    expect(items[1]).toBe("Caduque — plus utile (ton commentaire, 24/09 20:00) — rouverte 24/09 21:00 par toi");
  });

  it("une tâche archivée sans classement motivé garde sa ligne d'avant", () => {
    const el = rendreAvec(tache({ archive_auto: { texte: "Archivée automatiquement : branche intégrée." } }));
    expect(el.querySelector(".bz-task__meta").textContent).toBe("Archivée automatiquement : branche intégrée.");
  });
});

describe("le menu ⋯", () => {
  it("propose les trois gestes sur une tâche ouverte", () => {
    const labels = entreesClassement(tache({ statut_ui: "brouillon" })).filter((e) => e !== "sep").map((e) => e.label);
    expect(labels).toEqual(["Marquer faite…", "Doublon de…", "Caduque…"]);
  });

  it("les désactive, en disant pourquoi, quand un agent travaille dessus", () => {
    const entrees = entreesClassement(tache({ statut_ui: "en_cours", agent_actif: true })).filter((e) => e !== "sep");
    expect(entrees.every((e) => e.disabled)).toBe(true);
    expect(entrees[0].hint).toMatch(/arrête-le ou attends sa livraison/);
  });

  it("ne les propose pas sur une tâche déjà classée (Rouvrir d'abord)", () => {
    expect(entreesClassement(tache({ statut_ui: "faite" }))).toEqual([]);
  });
});
