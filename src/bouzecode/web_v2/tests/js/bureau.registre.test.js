import { describe, it, expect, beforeEach } from "vitest";

// Bureau — registre des tâches rendues : une tâche supprimée (ou disparue du serveur) en sort au
// rendu suivant, au lieu de garder son élément et son éditeur en mémoire pour toute la session.

import { state } from "../../static/js/bureau/store.js";
import { renderTache, registre, oublierDisparues } from "../../static/js/bureau/tache.js";

const tache = (id) => ({ id, titre: id, corps: id, statut_ui: "brouillon", segment: "a_lancer", libelle_statut: "Brouillon",
  passages: [], projet_slug: "demo", projet_defaut: "demo" });

beforeEach(() => {
  registre.clear();
  state.deplies = new Set();
  state.projets = [{ slug: "demo", name: "demo" }];
});

describe("registre des tâches", () => {
  it("oublie les tâches qui ne sont plus servies, garde les autres", () => {
    for (const id of ["t1", "t2"]) document.body.appendChild(renderTache(tache(id)));
    registre.get("t2").el.remove();                // supprimée : retirée de la page
    oublierDisparues(new Set(["t1"]));
    expect([...registre.keys()]).toEqual(["t1"]);
  });
});
