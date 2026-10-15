import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Vue d'enquête — point d'entrée : une session sans aucun tour n'appelle jamais /tours/undefined,
// et un « % » tapé dans la recherche (hash non encodé, ou encodé) ne fait pas planter la page.

const json = (corps, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });
const flush = async (n = 10) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };

function page() {
  document.body.innerHTML = `
    <div class="eq" data-agent="a1">
      <p id="eq-resume"></p>
      <form id="eq-recherche"><input id="eq-q"></form>
      <div class="eq-onglets">
        <button class="tab" data-vue="tours"></button><button class="tab" data-vue="recherche" hidden></button>
      </div>
      <section class="eq-vue" data-vue="tours"><input type="checkbox" id="eq-anormaux"><ol id="eq-liste"></ol><div id="eq-tour"></div></section>
      <section id="vue-recherche" class="eq-vue" data-vue="recherche" hidden></section>
      <section id="vue-note" class="eq-vue" data-vue="note" hidden></section>
      <section id="vue-saturation" class="eq-vue" data-vue="saturation" hidden></section>
    </div>`;
}

let erreurs;
const surErreur = (e) => erreurs.push(e.reason || e.error || e);
beforeEach(() => {
  vi.resetModules();
  page();
  erreurs = [];
  window.addEventListener("unhandledrejection", surErreur);
  window.addEventListener("error", surErreur);
});
afterEach(() => {
  vi.restoreAllMocks();
  window.removeEventListener("unhandledrejection", surErreur);
  window.removeEventListener("error", surErreur);
  location.hash = "";
});

describe("point d'entrée de l'enquête", () => {
  it("session sans tour : aucun appel à /tours/undefined, un état vide lisible", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation((u) => Promise.resolve(json(String(u).includes("/frise")
      ? { tours: [], total_cout: 0, nb_anormaux: 0, libelles_marqueurs: {} } : {})));
    await import("../../static/js/enquete/main.js");
    await flush();
    expect(f.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("undefined"))).toEqual([]);
    expect(document.getElementById("eq-tour").textContent).toMatch(/Aucun tour/);
    // L'onglet Tours ne fabrique pas non plus #tour-undefined.
    document.querySelector(".tab[data-vue='tours']").click();
    expect(location.hash).not.toContain("undefined");
  });

  it("un « % » dans la recherche : pas d'exception, la recherche part avec le texte tapé", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation((u) => Promise.resolve(json(String(u).includes("/frise")
      ? { tours: [{ tour: 1, marqueurs: [], outils: [] }], total_cout: 0, nb_anormaux: 0, libelles_marqueurs: {} }
      : String(u).includes("/recherche") ? { q: "100%", resultats: [], limite_atteinte: false } : { tour: 1, elements: [], diff: {}, reponse: {} })));
    await import("../../static/js/enquete/main.js");
    await flush();
    document.getElementById("eq-q").value = "100%";
    document.querySelector(".tab[data-vue='recherche']").click();
    await flush();
    location.hash = "#recherche-50%";          // hash mal formé collé à la main
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await flush();
    expect(erreurs).toEqual([]);
    const recherches = f.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/recherche"));
    expect(recherches.some((u) => u.includes(`q=${encodeURIComponent("100%")}`))).toBe(true);
  });
});
