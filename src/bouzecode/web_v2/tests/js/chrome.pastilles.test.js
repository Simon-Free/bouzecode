// Pastilles de navigation : UNE lecture de /api/nav/counts par tick, tous onglets confondus.
// Un onglet qui vient de lire les pastilles les partage (BroadcastChannel) ; les autres sautent
// leur propre lecture. Sans ça, deux onglets (Bureau + Agents), repartis ensemble au retour du
// serveur, interrogeaient /api/nav/counts à la même seconde à chaque tick.
//
// UN seul onglet chargé pour tout le fichier : chrome.js pose des écouteurs sur `window` qu'on ne
// peut pas retirer, un second chargement doublerait les lectures comptées.
import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";

const flush = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };
const attendre = (ms) => new Promise((r) => setTimeout(r, ms));

let appelsPastilles = 0;
let autreOnglet = null;
const partages = [];

function reponse(corps) {
  return Promise.resolve({ ok: true, status: 200, headers: { get: () => "application/json" },
    text: async () => JSON.stringify(corps) });
}

beforeAll(async () => {
  document.body.innerHTML = `<nav><a href="/bureau"><span data-nav-count="a_moi"></span></a></nav>`;
  global.fetch = vi.fn((url) => {
    if (String(url).startsWith("/api/nav/counts")) {
      appelsPastilles += 1;
      return reponse({ a_moi: 3, inbox: 3, en_cours: 1 });
    }
    return reponse({ ok: true });
  });
  autreOnglet = new BroadcastChannel("bz.nav-counts");
  autreOnglet.onmessage = (e) => partages.push(e.data.counts);
  await import("../../static/js/chrome.js");
  await flush();
  await attendre(20);
});

afterAll(() => { autreOnglet.close(); });

const pastille = () => document.querySelector("[data-nav-count='a_moi']").textContent;

describe("pastilles partagées entre onglets", () => {
  it("l'onglet lit les pastilles à l'ouverture et les partage aux autres onglets", () => {
    expect(appelsPastilles).toBe(1);
    expect(pastille()).toBe("3");
    expect(partages).toEqual([{ a_moi: 3, inbox: 3, en_cours: 1 }]);
  });

  it("un tick qui suit les pastilles d'un autre onglet ne relit pas le serveur", async () => {
    appelsPastilles = 0;
    autreOnglet.postMessage({ counts: { a_moi: 7, inbox: 7, en_cours: 0 } });
    await attendre(20);
    expect(pastille()).toBe("7");
    window.dispatchEvent(new CustomEvent("ui:online"));  // un tick ordinaire du poller
    await flush();
    expect(appelsPastilles).toBe(0);
  });

  it("une relecture demandée après un geste interroge toujours le serveur", async () => {
    appelsPastilles = 0;
    autreOnglet.postMessage({ counts: { a_moi: 7, inbox: 7, en_cours: 0 } });
    await attendre(20);
    window.dispatchEvent(new CustomEvent("ui:counts-changed"));
    await flush();
    expect(appelsPastilles).toBe(1);
    expect(pastille()).toBe("3");
  });
});
