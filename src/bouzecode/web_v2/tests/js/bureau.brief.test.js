import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Une tâche = UN champ, le brief, enregistré automatiquement (demande du 2026-09-24) :
// à la frappe (≈ 800 ms), à la perte de focus ; « Enregistrement… » → « Enregistré » ; en erreur,
// message + nouvel essai, texte jamais perdu ; la dernière frappe gagne ; le rafraîchissement
// n'écrase pas une frappe en attente. Plus de titre, plus de sélecteur de chantier visible,
// plus de bouton « décision », un seul « Lancer » dans le détail.

import { state } from "../../static/js/bureau/store.js";
import { renderTache, registre, deplier } from "../../static/js/bureau/tache.js";
import { briefAffiche } from "../../static/js/bureau/tache_editeur.js";
import { zoneAjout } from "../../static/js/bureau/sections.js";
import { horloge } from "../../static/js/bureau/autosave.js";

const tache = (extra = {}) => ({ id: "t1", titre: "Migrer la base", corps: "Migrer la base\n\nle détail", statut_ui: "brouillon",
  segment: "a_lancer", libelle_statut: "Brouillon", passages: [], projet_slug: "demo", projet_defaut: "demo", ...extra });

const json = (corps, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });

function monter(t = tache()) {
  document.body.innerHTML = "";
  const el = renderTache(t);
  document.body.appendChild(el);
  deplier(registre.get(t.id), true, null, false);
  return el;
}

function taper(champ, texte) {
  champ.value = texte;
  champ.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  registre.clear();
  state.deplies = new Set();
  state.projets = [{ slug: "demo", name: "demo" }];
  state.lignes = { chantiers: [], non_rattachees: [] };
  vi.useFakeTimers();
});

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("un seul champ", () => {
  it("pas de champ titre, pas de sélecteur de chantier, pas de bouton décision, un seul Lancer", () => {
    const el = monter();
    expect(el.querySelector(".bz-ed__titre")).toBeNull();
    expect(el.querySelector("select[aria-label='Chantier']")).toBeNull();
    expect(el.querySelector(".bz-ed__brief").value).toBe("Migrer la base\n\nle détail");
    const boutons = [...el.querySelectorAll(".bz-task__body button")].map((b) => b.textContent);
    expect(boutons.filter((b) => b === "Lancer")).toHaveLength(1);
    expect(boutons.some((b) => /décision/i.test(b))).toBe(false);
    expect(boutons).not.toContain("Enregistrer");
    // « Déplacer vers… » existe, mais dans le menu ⋯ seulement.
    expect(el.querySelector(".bz-task__menu").getAttribute("aria-label")).toBe("Autres actions sur la tâche");
  });

  it("le titre posé par un agent reste en tête du brief affiché", () => {
    expect(briefAffiche({ titre: "Titre agent", corps: "autre chose" })).toBe("Titre agent\n\nautre chose");
    expect(briefAffiche({ titre: "Même", corps: "# Même\nsuite" })).toBe("# Même\nsuite");
  });

  it("une 1re ligne de plus de 120 caractères n'est pas dupliquée (le titre en est la coupe)", () => {
    const ligne = "Une première ligne très longue ".repeat(6).trim();
    expect(ligne.length).toBeGreaterThan(120);
    const titre = ligne.slice(0, 120).trim();
    expect(briefAffiche({ titre, corps: `${ligne}\nsuite` })).toBe(`${ligne}\nsuite`);
    //  Coupe du serveur : au mot, marquée « … ».
    const coupe = `${ligne.slice(0, 110).split(" ").slice(0, -1).join(" ")}…`;
    expect(briefAffiche({ titre: coupe, corps: `${ligne}\nsuite` })).toBe(`${ligne}\nsuite`);
  });
});

describe("enregistrement automatique", () => {
  it("enregistre ≈ 800 ms après la frappe, puis dit « Enregistré » et met le libellé à jour", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ micro: { titre: "Nouvelle 1re ligne", corps: "Nouvelle 1re ligne\nsuite" } }));
    const el = monter();
    taper(el.querySelector(".bz-ed__brief"), "Nouvelle 1re ligne\nsuite");
    await vi.advanceTimersByTimeAsync(500);
    expect(f).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(400);
    expect(f).toHaveBeenCalledTimes(1);
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain("/api/micros/t1");
    expect(JSON.parse(init.body)).toEqual({ corps: "Nouvelle 1re ligne\nsuite" });
    await vi.runOnlyPendingTimersAsync();
    expect(el.querySelector(".bz-ed__etat").textContent).toBe("Enregistré");
    expect(el.querySelector(".bz-task__titre").textContent).toBe("Nouvelle 1re ligne");
  });

  it("la dernière frappe gagne : une frappe pendant un envoi en vol repart ensuite avec la valeur finale", async () => {
    let relacher;
    const f = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => new Promise((r) => { relacher = () => r(json({ micro: { titre: "a", corps: "a" } })); }))
      .mockResolvedValue(json({ micro: { titre: "ab", corps: "ab" } }));
    const el = monter();
    const brief = el.querySelector(".bz-ed__brief");
    taper(brief, "a");
    await vi.advanceTimersByTimeAsync(900);
    expect(el.querySelector(".bz-ed__etat").textContent).toBe("Enregistrement…");
    taper(brief, "ab");
    await vi.advanceTimersByTimeAsync(900);
    expect(f).toHaveBeenCalledTimes(1);
    relacher();
    await vi.runOnlyPendingTimersAsync();
    expect(f).toHaveBeenCalledTimes(2);
    expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ corps: "ab" });
  });

  it("en erreur : message à côté, texte gardé, nouvel essai automatique", async () => {
    const f = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ error: "base verrouillée" }, 500))
      .mockResolvedValue(json({ micro: { titre: "garde-moi", corps: "garde-moi" } }));
    const el = monter();
    const brief = el.querySelector(".bz-ed__brief");
    taper(brief, "garde-moi");
    await vi.advanceTimersByTimeAsync(900);
    const etat = el.querySelector(".bz-ed__etat");
    expect(etat.textContent).toContain("base verrouillée");
    expect(etat.dataset.erreur).toBe("true");
    expect(brief.value).toBe("garde-moi");
    await vi.advanceTimersByTimeAsync(5100);
    expect(f).toHaveBeenCalledTimes(2);
    expect(etat.textContent).toBe("Enregistré");
  });

  it("une lecture partie AVANT l'enregistrement et arrivée après n'écrase pas le brief enregistré", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ micro: { titre: "nouveau", corps: "nouveau" } }));
    const el = monter();
    const brief = el.querySelector(".bz-ed__brief");
    const lecture = horloge();                 // rafraîchissement parti maintenant…
    taper(brief, "nouveau");
    await vi.advanceTimersByTimeAsync(900);
    await vi.runOnlyPendingTimersAsync();
    expect(el.querySelector(".bz-ed__etat").textContent).toBe("Enregistré");
    brief.blur();
    state.lueNo = lecture;                     // … qui répond avec le brief d'AVANT l'enregistrement
    renderTache(tache({ corps: "ancien", titre: "ancien" }));
    expect(brief.value).toBe("nouveau");
    state.lueNo = horloge();                   // une lecture postérieure, elle, fait foi
    renderTache(tache({ corps: "changé ailleurs", titre: "changé ailleurs" }));
    expect(brief.value).toBe("changé ailleurs");
    delete state.lueNo;
  });

  it("le rafraîchissement n'écrase pas une frappe pas encore enregistrée", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ micro: { titre: "x", corps: "x" } }));
    const el = monter();
    const brief = el.querySelector(".bz-ed__brief");
    taper(brief, "en train d'écrire");
    renderTache(tache({ corps: "version serveur", titre: "version serveur" }));
    expect(brief.value).toBe("en train d'écrire");
  });
});

describe("création", () => {
  it("le texte tapé dans « + Ajouter une tâche » part dans le BRIEF (le serveur en tire le titre)", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ micro: { id: "n1", titre: "Ligne un", corps: "Ligne un\nLigne deux" } }, 201));
    document.body.innerHTML = "";
    const zone = zoneAjout("c1");
    document.body.appendChild(zone);
    const champ = zone.querySelector(".bz-add__input");
    champ.value = "Ligne un\nLigne deux";
    champ.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await vi.runOnlyPendingTimersAsync();
    const corps = JSON.parse(f.mock.calls[0][1].body);
    expect(corps.corps).toBe("Ligne un\nLigne deux");
    expect(corps.titre).toBe("");
    expect(corps.macro_id).toBe("c1");
  });

  it("Entrée sur une zone vide : le message parle du brief (plus de « titre » à part)", () => {
    const f = vi.spyOn(globalThis, "fetch");
    document.body.innerHTML = "";
    const zone = zoneAjout("c1");
    document.body.appendChild(zone);
    zone.querySelector(".bz-add__input").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    const message = zone.querySelector(".field__error").textContent;
    expect(message).not.toMatch(/titre de la tâche/);
    expect(message).toMatch(/1re ligne/);
    expect(f).not.toHaveBeenCalled();
  });
});
