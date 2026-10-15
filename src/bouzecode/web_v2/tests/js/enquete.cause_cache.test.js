import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Enquête : un tour dont le cache lu chute affiche sa cause probable (préfixe modifié chez nous,
// note réécrite chez nous ou simplement allongée, ou raté côté fournisseur), dans la frise
// (infobulle) et dans le tour à la loupe.

import { etat } from "../../static/js/enquete/etat.js";
import { rendreFrise } from "../../static/js/enquete/frise.js";
import { afficherTour } from "../../static/js/enquete/tour.js";

const FOURNISSEUR = "raté côté fournisseur (DeepInfra) : préfixe identique";

const json = (corps) => new Response(JSON.stringify(corps),
  { status: 200, headers: { "Content-Type": "application/json" } });

const ligne = (tour, extra = {}) => ({ tour, horodatage: 0, duree_s: 2, plein_tarif: 100, cache_lu: 900,
  cache_ecrit: 0, sortie: 50, sortie_estimee: false, cout: 0.01, outils: [], marqueurs: [],
  anormal: false, annexes: 0, cause_cache: null, ...extra });

const tour = (cause) => ({
  tour: 3, precedent: 2, suivant: null, cause_cache: cause,
  api: { api_input_tokens: 15538, api_cache_read: 2048, api_cache_create: 0, api_output_tokens: 50 },
  elements: [], diff: { premier_tour: false, rupture: null, ajoutes: [], retires: [], modifies: [] },
  reponse: null, annexes: [],
});

beforeEach(() => {
  document.body.innerHTML = '<ol id="eq-liste"></ol><div id="eq-tour"></div>';
  etat.agent = "a1";
  etat.details = new Map();
  etat.tour = 3;
  etat.frise = { tours: [ligne(2), ligne(3, { marqueurs: ["cache_rate"], anormal: true, cause_cache: FOURNISSEUR })],
    libelles_marqueurs: { cache_rate: "Cache raté" } };
});

afterEach(() => { vi.restoreAllMocks(); });

describe("cause d'un cache raté", () => {
  it("la frise la donne dans l'infobulle du seul tour raté", () => {
    rendreFrise();
    const [t2, t3] = document.querySelectorAll(".eq-ligne");
    expect(t3.title).toContain(`Cache raté : ${FOURNISSEUR}`);
    expect(t2.title).not.toContain("Cache raté");
  });

  it("le tour à la loupe l'affiche en clair", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(tour("préfixe modifié chez nous : liste des outils")));
    await afficherTour(3, null);
    expect(document.querySelector(".eq-cause").textContent)
      .toBe("Cache raté — cause probable : préfixe modifié chez nous : liste des outils");
  });

  it("une note réécrite chez nous : position, extrait et passe en cause, dans la frise et le tour", async () => {
    const reecrite = "note réécrite chez nous (à la position 1548 : « …## snippet: /tmp/x.py L1-2… ») : "
      + "purge d'extraits périmés";
    etat.frise.tours[1].cause_cache = reecrite;
    rendreFrise();
    expect(document.querySelectorAll(".eq-ligne")[1].title).toContain(`Cache raté : ${reecrite}`);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(tour(reecrite)));
    await afficherTour(3, null);
    expect(document.querySelector(".eq-cause").textContent)
      .toBe(`Cache raté — cause probable : ${reecrite}`);
  });

  it("une note seulement allongée renvoie au fournisseur", async () => {
    const allongee = "note simplement allongée, préfixe intact : raté côté fournisseur (DeepInfra)";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(tour(allongee)));
    await afficherTour(3, null);
    expect(document.querySelector(".eq-cause").textContent).toContain("raté côté fournisseur (DeepInfra)");
  });

  it("rien n'est affiché quand le cache n'a pas chuté", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(tour(null)));
    await afficherTour(3, null);
    expect(document.querySelector(".eq-cause")).toBeNull();
  });
});
