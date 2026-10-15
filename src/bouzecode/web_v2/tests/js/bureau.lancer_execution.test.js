import { describe, it, expect, vi, beforeEach } from "vitest";

// Dialogue Lancer d'une tâche du Bureau (static/js/bureau/lancer.js + lancer_execution.js) :
// choix Local (défaut) / Rundeck, mode Agent / Tests (commande pytest exigée AVANT l'appel, R4),
// fichiers non suivis proposés (secret grisé, jamais envoyé), projets secondaires, et le champ
// `execution` envoyé à POST /api/micros/<id>/lancer. Passage : lien Rundeck + fichiers refusés.

import { state } from "../../static/js/bureau/store.js";
import { ouvrirLancement } from "../../static/js/bureau/lancer.js";
import { champExecution, indicesDe } from "../../static/js/bureau/lancer_execution.js";
import { rendrePassages } from "../../static/js/bureau/passages.js";

const FICHIERS = { ok: true, slug: "demo", tronque: false, non_suivis: [
  { chemin: "notes/plan.md", taille: 8, pertinent: true, indices: ["plan"] },
  { chemin: "notes/autre.md", taille: 8, pertinent: false },
  { chemin: ".env", taille: 9, pertinent: false, exclu: "secret" },
  { chemin: "gros.bin", taille: 9, pertinent: false, exclu: "binaire" }] };

const json = (corps, status = 200) => ({ ok: status < 400, status, text: async () => JSON.stringify(corps) });

function serveur(reponseLancer = { ok: true, ticket_id: "tk1", launch_key: "launching/tk1" }) {
  global.fetch = vi.fn(async (url) => {
    const u = String(url);
    if (u.includes("/fichiers-non-suivis")) return json(FICHIERS);
    if (u.includes("/prompt")) return json({ prompt: "p", caracteres: 1 });
    if (u.includes("/lancer")) return typeof reponseLancer === "function" ? reponseLancer() : json(reponseLancer);
    return json({});
  });
}

const corpsDuLancement = () => {
  const [, init] = fetch.mock.calls.find(([u]) => String(u).includes("/lancer"));
  return JSON.parse(init.body);
};
const choisir = (el, nom, valeur) => {
  el.querySelector(`input[name=${nom}][value=${valeur}]`).click();
};

beforeEach(() => {
  document.body.innerHTML = '<div id="toasts"></div>';
  Object.assign(state, { projets: [{ slug: "demo", name: "demo" }, { slug: "autre", name: "autre" }], profils: [] });
});

describe("bloc Exécution", () => {
  async function monter() {
    const charger = vi.fn(async () => FICHIERS);
    const e = champExecution({ projets: state.projets, principal: () => "demo", indices: "Écrire le plan", charger });
    document.body.appendChild(e.el);
    await e.charger();
    return { e, charger };
  }

  it("Local par défaut : options Rundeck masquées, champ execution minimal", async () => {
    const { e, charger } = await monter();
    expect(charger).toHaveBeenCalledWith("demo", "écrire plan");
    expect(e.el.querySelector("[data-role=rundeck]").hidden).toBe(true);
    expect(e.valeur()).toEqual({ cible: "local", projets: ["demo"], fichiers_non_suivis: { demo: ["notes/plan.md"] } });
  });

  it("propose le plan, grise le secret, cache le binaire", async () => {
    const { e } = await monter();
    const cases = [...e.el.querySelectorAll("input[data-role=fichier]")];
    expect(cases.map((c) => c.value)).toEqual(["notes/plan.md", "notes/autre.md", ".env"]);
    expect(cases.map((c) => c.checked)).toEqual([true, false, false]);
    expect(cases[2].disabled).toBe(true);
    expect(e.el.textContent).toContain("secret, jamais transmis");
    expect(e.el.querySelector("[data-role=fichiers-etat]").textContent).toContain("1 exclu(s)");
  });

  it("Rundeck + Tests exige la commande pytest avant tout appel, puis l'envoie avec le navigateur", async () => {
    const { e } = await monter();
    choisir(e.el, "bz-cible", "rundeck");
    expect(e.el.querySelector("[data-role=rundeck]").hidden).toBe(false);
    choisir(e.el, "bz-mode-distant", "tests");
    expect(e.valider()).toBe(false);
    expect(e.el.textContent).toContain("Donne les arguments de pytest");
    e.el.querySelector("[data-role=commande]").value = "tests/web -x";
    e.el.querySelector("[data-role=navigateur]").checked = false;
    e.el.querySelector("input[data-role=projet][value=autre]").checked = true;
    expect(e.valider()).toBe(true);
    expect(e.valeur()).toEqual({ cible: "rundeck", projets: ["demo", "autre"], mode: "tests", commande: "tests/web -x",
      navigateur: false, fichiers_non_suivis: { demo: ["notes/plan.md"] } });
  });

  it("une lecture des fichiers en échec est dite, sans bloquer", async () => {
    const e = champExecution({ projets: state.projets, principal: () => "demo", charger: async () => { throw new Error("pas un dépôt git"); } });
    await e.charger();
    expect(e.el.textContent).toContain("Fichiers non suivis indisponibles : pas un dépôt git");
    expect(e.valider()).toBe(true);
  });

  it("les indices sont les mots de 4 lettres et plus", () => {
    expect(indicesDe("Fix le bug du plan de tests")).toEqual(["plan", "tests"]);
  });
});

describe("dialogue Lancer", () => {
  const TACHE = { id: "m1", titre: "Écrire le plan", projet_defaut: "demo" };

  it("envoie le champ execution (Local par défaut) à /api/micros/<id>/lancer", async () => {
    serveur();
    const fini = ouvrirLancement(TACHE, {});
    await vi.waitFor(() => expect(document.querySelector("input[data-role=fichier]")).not.toBeNull());
    document.querySelector("[data-role=go]").click();
    expect(await fini).toBe(true);
    expect(corpsDuLancement()).toMatchObject({ projet_slug: "demo",
      execution: { cible: "local", projets: ["demo"], fichiers_non_suivis: { demo: ["notes/plan.md"] } } });
  });

  it("premier lancement ordinaire (local, aucun fichier) : pas de champ execution", async () => {
    serveur();
    const fini = ouvrirLancement(TACHE, {});
    await vi.waitFor(() => expect(document.querySelector("input[data-role=fichier]")).not.toBeNull());
    document.querySelector("input[data-role=fichier][value='notes/plan.md']").click();
    document.querySelector("[data-role=go]").click();
    expect(await fini).toBe(true);
    expect(corpsDuLancement().execution).toBeUndefined();
  });

  it("une relance envoie toujours le choix (Local compris) à /relancer", async () => {
    serveur({ ok: true, ticket_id: "tk2", mode: "nouvel_agent" });
    const fini = ouvrirLancement({ ...TACHE, joignable: false }, { mode: "relancer", retourInitial: "refais" });
    await vi.waitFor(() => expect(document.querySelector("input[data-role=fichier]")).not.toBeNull());
    document.querySelector("input[data-role=fichier][value='notes/plan.md']").click();
    document.querySelector("[data-role=go]").click();
    expect(await fini).toBe(true);
    const [url, init] = fetch.mock.calls.find(([u]) => String(u).includes("/relancer"));
    expect(url).toContain("/api/micros/m1/relancer");
    expect(JSON.parse(init.body).execution).toEqual({ cible: "local", projets: ["demo"], fichiers_non_suivis: {} });
  });

  it("Rundeck : le toast dit l'exécution et les fichiers NON transmis", async () => {
    serveur({ ok: true, ticket_id: "tk1", distant: { ok: true, execution_id: "77", url: "http://rundeck/77",
      fichiers_refuses: { demo: [{ chemin: ".env", raison: "secret" }] } } });
    const fini = ouvrirLancement(TACHE, {});
    await vi.waitFor(() => expect(document.querySelector("input[data-role=fichier]")).not.toBeNull());
    choisir(document, "bz-cible", "rundeck");
    document.querySelector("[data-role=go]").click();
    expect(await fini).toBe(true);
    expect(corpsDuLancement().execution).toMatchObject({ cible: "rundeck", mode: "agent" });
    const toasts = document.getElementById("toasts").textContent;
    expect(toasts).toContain("Lancé sur Rundeck — exécution 77");
    expect(toasts).toContain("demo/.env (secret)");
  });

  it("mode Tests sans commande : refus dans le dialogue, aucun appel de lancement", async () => {
    serveur();
    ouvrirLancement(TACHE, {});
    await vi.waitFor(() => expect(document.querySelector("input[data-role=fichier]")).not.toBeNull());
    choisir(document, "bz-cible", "rundeck");
    choisir(document, "bz-mode-distant", "tests");
    document.querySelector("[data-role=go]").click();
    await new Promise((r) => setTimeout(r, 20));
    expect(fetch.mock.calls.some(([u]) => String(u).includes("/lancer"))).toBe(false);
    expect(document.activeElement.dataset.role).toBe("commande");
  });

  it("un refus du serveur (cible indisponible) est dit dans le dialogue avec l'issue", async () => {
    serveur(() => json({ error: { code: "cible_indisponible", message: "Rundeck absent" } }, 501));
    ouvrirLancement(TACHE, {});
    await vi.waitFor(() => expect(document.querySelector("input[data-role=fichier]")).not.toBeNull());
    choisir(document, "bz-cible", "rundeck");
    document.querySelector("[data-role=go]").click();
    await vi.waitFor(() => expect(document.querySelector(".bz-launch__erreur").textContent).toContain("Rundeck absent"));
    expect(document.querySelector(".bz-launch__erreur").textContent).toContain("Sur ce poste");
  });
});

describe("passage exécuté sur Rundeck", () => {
  it("montre le lien de l'exécution et les fichiers refusés", () => {
    const [, bloc] = rendrePassages({ id: "m1", passages: [{ ticket_id: "tk1", numero: 1, etat: "running",
      distant: { execution_id: "77", url: "http://rundeck/77", mode: "tests",
        fichiers_refuses: { demo: [{ chemin: ".env", raison: "secret" }] } } }] });
    const lien = bloc.querySelector("[data-role=distant] a");
    expect(lien.getAttribute("href")).toBe("http://rundeck/77");
    expect(lien.textContent).toBe("exécution 77");
    expect(bloc.textContent).toContain("Rundeck (tests)");
    expect(bloc.textContent).toContain("Fichiers non transmis : demo/.env (secret)");
  });
});
