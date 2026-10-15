import { describe, it, expect, vi, beforeEach } from "vitest";

// Ajouter un dépôt directement depuis le Bureau : le dialogue « Dépôts du chantier » et le
// dialogue Lancer d'une tâche proposent « + Ajouter un dépôt… », qui ouvre le dialogue
// d'enregistrement (projects_admin.js) au lieu de renvoyer vers la page Agents.

import { state } from "../../static/js/bureau/store.js";
import { depots } from "../../static/js/bureau/chantier.js";
import { ouvrirLancement } from "../../static/js/bureau/lancer.js";
import { construireCorps } from "../../static/js/bureau/tache_editeur.js";

const json = (corps, status = 200) => ({ ok: status < 400, status, text: async () => JSON.stringify(corps),
  json: async () => corps });

beforeEach(() => {
  document.body.innerHTML = "";
  Object.assign(state, { projets: [{ slug: "demo", name: "demo" }], profils: [] });
  global.fetch = vi.fn(async (url) => {
    const u = String(url);
    if (u.includes("/api/projects")) return json({ ok: true, projects: state.projets });
    if (u.includes("/fichiers-non-suivis")) return json({ ok: true, slug: "demo", tronque: false, non_suivis: [] });
    if (u.includes("/prompt")) return json({ prompt: "p", caracteres: 1 });
    return json({});
  });
});

const dialogueDepotOuvert = () => [...document.querySelectorAll("dialog, .ag-repos, form")]
  .some((el) => el.textContent.includes("Chemin absolu du dépôt"));

describe("ajouter un dépôt depuis le Bureau", () => {
  it("le dialogue Dépôts du chantier propose « + Ajouter un dépôt… »", async () => {
    depots({ id: "c1", titre: "Chantier", projets: [] });
    const btn = document.querySelector("[data-role=ajouter-depot]");
    expect(btn).not.toBeNull();
    expect(btn.textContent).toContain("Ajouter un dépôt");
    btn.click();
    await vi.waitFor(() => expect(dialogueDepotOuvert()).toBe(true));
  });

  it("le dialogue Lancer d'une tâche propose « + Ajouter un dépôt… »", async () => {
    ouvrirLancement({ id: "m1", titre: "Écrire le plan", projet_defaut: "demo" }, {});
    await vi.waitFor(() => expect(document.querySelector("[data-role=ajouter-depot]")).not.toBeNull());
    document.querySelector("[data-role=ajouter-depot]").click();
    await vi.waitFor(() => expect(dialogueDepotOuvert()).toBe(true));
  });

  it("la tâche dépliée d'un chantier propose « + dépôt » à côté du sélecteur", async () => {
    const el = document.createElement("div");
    document.body.appendChild(el);
    construireCorps({ el, t: { id: "m2", titre: "Tâche", brief: "", projet_defaut: "demo", macro_id: "c1" } });
    const btn = el.querySelector("[data-role=ajouter-depot]");
    expect(btn).not.toBeNull();
    btn.click();
    await vi.waitFor(() => expect(dialogueDepotOuvert()).toBe(true));
  });
});
