import { describe, it, expect, beforeEach } from "vitest";

// Carte d'une tâche (static/js/bureau/tache.js) : une précision transmise à l'agent en cours
// se voit sur la ligne repliée — horodatée, et lue ou pas encore lue (SPEC §4.5, §4.6).

import { state } from "../../static/js/bureau/store.js";
import { rendreListe } from "../../static/js/bureau/liste.js";
import { registre, derniereTransmission } from "../../static/js/bureau/tache.js";

function precision(texte, statut, mode = "ajout") {
  return { id: `p-${texte}`, texte, auteur: "assistant", created_at: "2026-09-24T14:32:05",
    transmissions: [{ queue_id: "q1", agent_id: "a1", statut, mode, lu_at: statut === "lue" ? "2026-09-24T14:32:40" : "" }] };
}

function tache(statut, precisions) {
  const seg = { en_cours: "en_cours", a_relire: "a_moi", faite: "archivees" }[statut];
  return { id: "t1", titre: "Écrire le rapport", corps: "brief", statut_ui: statut, segment: seg, libelle_statut: statut,
    passages: [{ agent_id: "a1", etat: "running" }], projet_slug: "demo", projet_defaut: "demo",
    updated_at: "2026-09-24T14:00:00", precisions };
}

function rendreAvec(t) {
  state.lignes = { chantiers: [{ macro_id: "c1", titre: "C", etat: "active", projets: [], compte_ui: {}, lignes: [t] }],
    non_rattachees: [], titre_non_rattachees: "Sans chantier", stats: {} };
  rendreListe();
  return document.querySelector(".bz-task[data-id='t1'] .bz-task__transmis");
}

beforeEach(() => {
  registre.clear();
  document.body.innerHTML = `<div id="bz-mode"><button data-mode="statut"></button><button data-mode="chantier"></button></div>
    <input id="bz-search"><div id="lignes-liste"></div><form id="chantier-nouveau" hidden></form>`;
  localStorage.clear();
  Object.assign(state, { inbox: { items: [], compte: 0 }, projets: [{ slug: "demo", name: "demo" }], recherche: "",
    mode: "statut", deplies: new Set(), replies: new Set(), archivesOuvertes: new Set() });
});

describe("précision transmise à l'agent, vue sur la carte", () => {
  it("dit l'heure et qu'elle n'est pas encore lue", () => {
    const el = rendreAvec(tache("en_cours", [precision("BILAN.md", "en_attente")]));
    expect(el.hidden).toBe(false);
    expect(el.textContent).toBe("✎ Précision transmise à 14:32 — pas encore lue par l'agent");
    expect(el.dataset.lecture).toBe("en_attente");
  });

  it("passe à « lue » en place, sans recréer la carte", () => {
    const avant = rendreAvec(tache("en_cours", [precision("BILAN.md", "en_attente")]));
    const apres = rendreAvec(tache("en_cours", [precision("BILAN.md", "lue")]));
    expect(apres).toBe(avant);
    expect(apres.textContent).toContain("lue par l'agent");
    expect(apres.dataset.lecture).toBe("lue");
  });

  it("dit quand le tour a été interrompu, et montre la DERNIÈRE précision transmise", () => {
    const el = rendreAvec(tache("en_cours", [precision("a", "lue"), precision("b", "en_attente", "interruption"),
      { id: "p-c", texte: "c", created_at: "2026-09-24T15:00:00", transmissions: [] }]));
    expect(el.textContent).toBe("✎ Précision transmise (tour interrompu) à 14:32 — pas encore lue par l'agent");
  });

  it("rien sur une tâche close ou sans transmission", () => {
    expect(rendreAvec(tache("faite", [precision("a", "lue")]))).toBeNull();
    expect(derniereTransmission(tache("en_cours", [{ id: "p", texte: "x", transmissions: [] }]))).toBeNull();
    registre.clear();
    expect(rendreAvec(tache("en_cours", [])).hidden).toBe(true);
  });
});
