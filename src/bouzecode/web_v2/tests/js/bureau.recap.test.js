import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Le récap d'un passage (carte « Passage #1 ✓ Terminé ») dit ce qu'est devenu chaque point
// « reste à faire » / « à décider » : la tâche qui le porte (statut, lien qui la montre), ou
// « Aucune tâche créée » + « Créer la tâche ». Cas réel du 2026-09-24 : les deux tâches
// existaient, la carte ne le disait pas, l'utilisateur a cru que l'agent n'avait rien créé.

import { state, poserLignes } from "../../static/js/bureau/store.js";
import { renderTache, registre, deplier } from "../../static/js/bureau/tache.js";

const json = (corps, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });

const RESTE = "Améliorer la difficulté estimée";
const DECISION = "Étendre le scraping aux autres sources du catalogue";

const suite = (id, titre, extra = {}) => ({ id, titre, lien: "creee", statut_ui: "brouillon", libelle_statut: "Brouillon", ...extra });

function tacheLivree(suites) {
  return { id: "t1", titre: "Scraper les énigmes", corps: "Scraper les énigmes", statut_ui: "a_relire", libelle_statut: "À vérifier",
    projet_slug: "demo", projet_defaut: "demo", macro_id: "m1",
    passages: [{ numero: 1, ticket_id: "k1", agent_id: "a1", etat: "finished", libelle_etat: "Terminé",
      recap: { fait: ["Scraper le Kangourou"], reste: [RESTE], a_decider: [DECISION], resume: "", ...(suites ? { suites } : {}) } }] };
}

const brouillon = (id, titre, extra = {}) => ({ id, titre, corps: titre, statut_ui: "brouillon", libelle_statut: "Brouillon",
  macro_id: "m1", passages: [], projet_slug: "demo", ...extra });

function monter(taches) {
  poserLignes({ chantiers: [{ macro_id: "m1", titre: "Portail des énigmes", etat: "active", projets: ["demo"], lignes: taches }], non_rattachees: [] });
  document.body.innerHTML = "";
  const els = taches.map((t) => { const el = renderTache(t); document.body.appendChild(el); return el; });
  deplier(registre.get("t1"), true, null, false);
  return els;
}

const point = (el, texte) => [...el.querySelectorAll(".bz-passage .bz-recap li")].find((li) => li.textContent.startsWith(texte));

beforeEach(() => {
  registre.clear();
  state.deplies = new Set();
  state.projets = [{ slug: "demo", name: "demo" }];
});

afterEach(() => { vi.restoreAllMocks(); document.getElementById("toasts")?.remove(); });

describe("récap d'un passage : les tâches créées pour les points laissés", () => {
  it("chaque point dit sa tâche et son statut actuel : « → tâche créée : … · brouillon »", () => {
    const [el] = monter([tacheLivree({ reste: [suite("t2", RESTE)],
      a_decider: [suite("t3", DECISION, { statut_ui: "a_decider", libelle_statut: "Décision à prendre" })] }),
    brouillon("t2", RESTE), brouillon("t3", DECISION, { statut_ui: "a_decider" })]);
    expect(point(el, RESTE).querySelector(".bz-suite").textContent).toBe(`→ tâche créée : ${RESTE} · brouillon`);
    expect(point(el, DECISION).querySelector(".bz-suite").textContent).toBe(`→ tâche créée : ${DECISION} · décision à prendre`);
  });

  it("le lien montre la tâche : dépliée, surlignée", () => {
    const [, cible] = monter([tacheLivree({ reste: [suite("t2", RESTE)], a_decider: [null] }), brouillon("t2", RESTE)]);
    expect(cible.querySelector(".bz-task__titre").getAttribute("aria-expanded")).toBe("false");
    document.querySelector(".bz-suite__lien[data-tache='t2']").click();
    expect(cible.querySelector(".bz-task__titre").getAttribute("aria-expanded")).toBe("true");
    expect(cible.classList.contains("is-highlighted")).toBe(true);
  });

  it("un point déjà porté par une tâche ouverte le dit autrement", () => {
    const [el] = monter([tacheLivree({ reste: [suite("t2", RESTE, { lien: "existante" })], a_decider: [null] }), brouillon("t2", RESTE)]);
    expect(point(el, RESTE).querySelector(".bz-suite").textContent).toMatch(/^→ tâche déjà ouverte : /);
  });

  it("sans tâche, la carte le dit et « Créer la tâche » la crée (décision comprise), puis la montre", async () => {
    const t = tacheLivree({ reste: [suite("t2", RESTE)], a_decider: [null] });
    const [el] = monter([t, brouillon("t2", RESTE)]);
    const ligne = point(el, DECISION);
    expect(ligne.querySelector(".bz-suite--aucune").textContent).toMatch(/^Aucune tâche créée pour ce point\./);
    global.fetch = vi.fn(async (url) => {
      if (!String(url).includes("/suites")) return json({ chantiers: [], non_rattachees: [] });
      const creee = brouillon("t9", DECISION, { statut_ui: "a_decider" });
      poserLignes({ chantiers: [{ macro_id: "m1", titre: "Portail", etat: "active", projets: [], lignes: [t, creee] }], non_rattachees: [] });
      document.body.appendChild(renderTache(creee));
      return json({ ok: true, deja: false, micro: { id: creee.id, titre: creee.titre } }, 201);
    });
    ligne.querySelector("button").click();
    await vi.waitFor(() => expect(document.querySelector("#toasts")?.textContent || "").toMatch(/Tâche créée/));
    const [url, init] = fetch.mock.calls.find(([u]) => String(u).includes("/suites"));
    expect(String(url)).toMatch(/\/api\/micros\/t1\/passages\/k1\/suites$/);
    expect(JSON.parse(init.body)).toEqual({ libelle: DECISION, decision: true });
    await vi.waitFor(() => expect(document.querySelector(".bz-task[data-id='t9'] .bz-task__titre").getAttribute("aria-expanded")).toBe("true"));
  });

  it("un récap sans information de lien (ancien serveur) reste une simple liste", () => {
    const [el] = monter([tacheLivree(null)]);
    expect(point(el, RESTE)).toBeTruthy();
    expect(el.querySelectorAll(".bz-suite")).toHaveLength(0);
  });
});
