import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Bureau — un agent qui pose une DEUXIÈME question après qu'on a répondu à la première : la
// nouvelle question doit s'afficher (le bloc « Réponse envoyée » de la précédente ne la bloque pas).

import { state } from "../../static/js/bureau/store.js";
import { renderTache, registre } from "../../static/js/bureau/tache.js";

const json = (corps, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });
const question = (texte, options) => ({ texte, options: options.map((label) => ({ label })), allow_freetext: true, agent_id: "ag1" });
const tache = (q) => ({ id: "t1", titre: "Brancher la base", corps: "Brancher la base", statut_ui: "a_repondre",
  segment: "a_moi", libelle_statut: "À répondre", question: q,
  passages: [{ agent_id: "ag1", etat: "awaiting_input", question: q }], projet_slug: "demo", projet_defaut: "demo" });

beforeEach(() => {
  registre.clear();
  state.deplies = new Set();
  state.projets = [{ slug: "demo", name: "demo" }];
  state.lignes = { chantiers: [], non_rattachees: [] };
  state.inbox = { items: [] };
});
afterEach(() => { vi.restoreAllMocks(); });

describe("questions successives d'un même agent", () => {
  it("après la réponse à la 1re question, la 2e s'affiche", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ ok: true }));
    const q1 = question("Quelle base ?", ["PostgreSQL", "SQLite"]);
    document.body.innerHTML = "";
    const el = renderTache(tache(q1));
    document.body.appendChild(el);
    expect(el.textContent).toContain("Quelle base ?");
    [...el.querySelectorAll(".bz-q__opt")].find((b) => b.textContent === "PostgreSQL").click();
    await vi.waitFor(() => expect(el.querySelector(".bz-q").dataset.done).toBe("true"));
    renderTache(tache(question("Quelle version de PostgreSQL ?", ["15", "16"])));
    expect(el.textContent).toContain("Quelle version de PostgreSQL ?");
    expect([...el.querySelectorAll(".bz-q__opt")].map((b) => b.textContent)).toEqual(["15", "16"]);
  });
});
