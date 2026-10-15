import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Vue d'enquête : ce que l'utilisateur voit dans la frise et dans un tour à partir des réponses
// de l'API (/api/enquete/*), sans navigateur.

import { etat } from "../../static/js/enquete/etat.js";
import { rendreFrise, brancherFiltre, voisin } from "../../static/js/enquete/frise.js";
import { afficherTour } from "../../static/js/enquete/tour.js";

const json = (corps, status = 200) => new Response(JSON.stringify(corps),
  { status, headers: { "Content-Type": "application/json" } });

const ligne = (tour, extra = {}) => ({ tour, horodatage: 0, duree_s: 2, plein_tarif: 100, cache_lu: 900,
  cache_ecrit: 0, sortie: 50, sortie_estimee: false, cout: 0.01, outils: ["Bash"], marqueurs: [],
  anormal: false, annexes: 0, ...extra });

const TOUR_2 = {
  tour: 2, precedent: 1, suivant: 3,
  api: { api_input_tokens: 400, api_cache_read: 900, api_cache_create: 0, api_output_tokens: 50 },
  elements: [
    { indice: 0, cle: "systeme:0", genre: "system_block", libelle: "Prompt", tokens: 10, cache: "cached", apercu: "P", tronque: false, taille: 1 },
    { indice: 1, cle: "systeme:1", genre: "system_block", libelle: "[METHODOLOGY]", tokens: 500, cache: "new-cache", apercu: "N", tronque: true, taille: 9000 },
  ],
  diff: { premier_tour: false, rupture: 1, ajoutes: [], retires: [],
    modifies: [{ indice: 1, nature: "ajout_en_fin", ajoutes: 1234, position: 10 }] },
  reponse: { texte: "", reflexion: "je réfléchis", appels: [{ nom: "Bash", id: "b1", entree: { command: "ls" } }],
    resultats: [{ nom: "Bash", id: "b1", texte: "Traceback", tronque: false, taille: 9 }] },
  annexes: [],
};

function page() {
  document.body.innerHTML = `
    <input type="checkbox" id="eq-anormaux"><ol id="eq-liste"></ol><div id="eq-tour"></div>`;
}

beforeEach(() => {
  page();
  etat.agent = "a1";
  etat.details = new Map();
  etat.tour = 2;
  etat.frise = { tours: [ligne(1, { marqueurs: ["entree"] }),
    ligne(2, { marqueurs: ["erreur", "cache_rate"], anormal: true }), ligne(3)],
  libelles_marqueurs: { erreur: "Erreur d'outil", cache_rate: "Cache raté", entree: "Message d'entrée" } };
});

afterEach(() => { vi.restoreAllMocks(); location.hash = ""; });

describe("frise des tours", () => {
  it("affiche une ligne par tour, le tour courant et les marqueurs lisibles", () => {
    rendreFrise();
    const lignes = document.querySelectorAll(".eq-ligne");
    expect(lignes).toHaveLength(3);
    expect(document.querySelector('[aria-current="true"]').dataset.tour).toBe("2");
    expect(lignes[1].textContent).toContain("Erreur d'outil");
    expect(lignes[1].dataset.anormal).toBe("1");
  });

  it("le filtre « anormaux » ne garde que les tours à regarder", () => {
    brancherFiltre();
    rendreFrise();
    const box = document.getElementById("eq-anormaux");
    box.checked = true;
    box.dispatchEvent(new Event("change"));
    expect([...document.querySelectorAll(".eq-ligne")].map((b) => b.dataset.tour)).toEqual(["2"]);
    box.checked = false;
    box.dispatchEvent(new Event("change"));
    expect(document.querySelectorAll(".eq-ligne")).toHaveLength(3);
  });

  it("cliquer une ligne mène au permalien du tour", () => {
    rendreFrise();
    document.querySelectorAll(".eq-ligne")[2].click();
    expect(location.hash).toBe("#tour-3");
  });
});

describe("navigation j/k", () => {
  it("deux pressions rapides partent du tour de l'URL, pas d'un état en retard d'un hashchange", () => {
    location.hash = "#tour-2";
    voisin(1);                        // j : l'URL passe à #tour-3, le hashchange n'a pas encore eu lieu
    expect(location.hash).toBe("#tour-3");
    expect(etat.tour).toBe(2);
    voisin(-1);                       // k aussitôt : revient au tour 2 (et non au tour 1)
    expect(location.hash).toBe("#tour-2");
  });
});

describe("un tour à la loupe", () => {
  it("une réponse arrivée après qu'on a changé de tour n'écrase pas le tour affiché", async () => {
    let livrer;
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise((r) => { livrer = r; }));
    etat.tour = 3;
    const lent = afficherTour(3, null);
    etat.tour = 2;
    etat.details.set(2, TOUR_2);
    await afficherTour(2, null);
    livrer(json({ ...TOUR_2, tour: 3 }));
    await lent;
    expect(document.querySelector("#eq-tour h2").textContent).toBe("Tour 2");
  });


  it("explique quel élément casse le préfixe et pourquoi", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(TOUR_2));
    await afficherTour(2, null);
    const zone = document.getElementById("eq-tour");
    expect(zone.querySelector(".eq-rupture").textContent).toMatch(/élément #1 .*a reçu 1 234 caractères en fin|élément #1 .*a reçu 1 234 caractères en fin/);
    expect(zone.querySelector("#element-1").dataset.rupture).toBe("1");
    expect(zone.querySelector("#element-1 .eq-el__cache").textContent).toBe("écrit au cache");
    expect(zone.textContent).toContain("Réflexion");
  });

  it("déplier un élément tronqué charge son texte intégral", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(TOUR_2))
      .mockResolvedValueOnce(json({ texte: "NOTE ENTIÈRE" }));
    await afficherTour(2, null);
    const el = document.getElementById("element-1");
    el.open = true;
    el.dispatchEvent(new Event("toggle"));
    await vi.waitFor(() => expect(el.querySelector(".eq-pre").textContent).toBe("NOTE ENTIÈRE"));
    expect(fetchMock.mock.calls[1][0]).toContain("/tours/2/elements/1");
  });

  it("un tour sans cause de cache ni élément retiré n'affiche jamais « null »", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ ...TOUR_2, cause_cache: null,
      diff: { ...TOUR_2.diff, retires: [] }, reponse: { texte: "", reflexion: "", appels: [], resultats: [] } }));
    await afficherTour(2, null);
    const zone = document.getElementById("eq-tour");
    expect(zone.textContent).not.toMatch(/null|undefined/);
    expect([...zone.childNodes].some((n) => n.nodeType === 3)).toBe(false);
  });

  it("une erreur de chargement propose de réessayer", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ error: "tour 2 introuvable" }, 404));
    await afficherTour(2, null);
    const zone = document.getElementById("eq-tour");
    expect(zone.querySelector(".error-state").textContent).toContain("tour 2 introuvable");
    expect(zone.querySelector(".error-state button")).not.toBeNull();
  });
});
