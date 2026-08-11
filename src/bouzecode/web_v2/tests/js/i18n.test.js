import { beforeEach, describe, expect, it, vi } from "vitest";

// Le noyau bilingue : anglais par défaut, français au choix, choix qui survit à la visite.
//
// Ces tests attaquent le noyau par sa surface PUBLIQUE (`t`, `setLang`, `applyDom`) et par le
// DOM, comme le reste du harnais. Le noyau s'installe une fois pour toutes sur `window` : pour
// rejouer un premier chargement — celui qui décide de la langue initiale — il faut donc à la
// fois vider le registre de modules et retirer l'objet installé.

const MODULE = "../../static/js/i18n/index.js";

async function loadFresh() {
  vi.resetModules();
  delete window.i18n;
  return import(MODULE);
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.lang = "";
  document.body.innerHTML = "";
});

describe("la langue par défaut", () => {
  it("est l'anglais quand l'utilisateur n'a jamais choisi", async () => {
    const { t, getLang } = await loadFresh();

    expect(getLang()).toBe("en");
    expect(t("state.running")).toBe("running");
    expect(t("state.finished")).toBe("done");
  });

  it("est annoncée sur <html lang>, pour les lecteurs d'écran comme pour la césure", async () => {
    await loadFresh();

    expect(document.documentElement.lang).toBe("en");
  });
});

describe("la bascule vers le français", () => {
  it("rend les libellés que l'interface servait avant d'être bilingue", async () => {
    const { t, setLang } = await loadFresh();

    setLang("fr");

    expect(t("state.running")).toBe("en cours");
    expect(t("state.finished")).toBe("terminé");
    expect(t("state.crashed")).toBe("planté");
    expect(t("conv.empty"))
      .toBe("Sélectionne une conversation à gauche, ou lance-en une nouvelle ci-dessus.");
  });

  it("réécrit la page en place, sans rechargement", async () => {
    const { setLang } = await loadFresh();
    document.body.innerHTML = `
      <h2 data-i18n="conv.sidebar_title">Conversations</h2>
      <p data-i18n="conv.loading">Loading…</p>
      <input data-i18n-placeholder="conv.new_placeholder" placeholder="New conversation…">
      <button data-i18n-title="conv.send" title="Send">↑</button>`;

    setLang("fr");

    expect(document.querySelector("p").textContent).toBe("Chargement…");
    expect(document.querySelector("input").getAttribute("placeholder"))
      .toContain("Nouvelle conversation");
    expect(document.querySelector("button").getAttribute("title")).toBe("Envoyer");
    expect(document.documentElement.lang).toBe("fr");
  });

  it("prévient les zones que le JavaScript a construites, qui ne portent aucune clé", async () => {
    const { setLang, onLangChange } = await loadFresh();
    const seen = [];
    onLangChange((event) => seen.push(event.detail.lang));

    setLang("fr");

    expect(seen).toEqual(["fr"]);
  });

  it("ne fait rien quand on rechoisit la langue déjà active", async () => {
    const { setLang, onLangChange } = await loadFresh();
    let calls = 0;
    onLangChange(() => { calls += 1; });

    setLang("en");

    expect(calls).toBe(0);
  });
});

describe("la persistance du choix", () => {
  it("garde le français d'une visite à l'autre", async () => {
    const first = await loadFresh();
    first.setLang("fr");

    const second = await loadFresh();

    expect(second.getLang()).toBe("fr");
    expect(second.t("state.running")).toBe("en cours");
    expect(document.documentElement.lang).toBe("fr");
  });

  it("ignore une langue stockée qu'on ne sait pas servir", async () => {
    window.localStorage.setItem("bouzecode.lang", "eo");

    const { getLang } = await loadFresh();

    expect(getLang()).toBe("en");
  });
});

describe("une clé manquante", () => {
  it("se voit à l'écran plutôt que de laisser un trou", async () => {
    const { t } = await loadFresh();

    expect(t("conv.this_key_does_not_exist")).toBe("⟦conv.this_key_does_not_exist⟧");
  });

  it("retombe sur l'anglais quand seul le français manque", async () => {
    const { t, setLang } = await loadFresh();
    window.i18n.register("en", { "test.only_english": "English only" });
    setLang("fr");

    expect(t("test.only_english")).toBe("English only");
  });
});

describe("les fragments rendus par le serveur", () => {
  it("se traduisent après insertion, parce qu'ils gardent leur clé dans le DOM", async () => {
    const { setLang, applyDom } = await loadFresh();
    // Ce que `services/message_view.py` écrit pour une réponse finale.
    document.body.innerHTML =
      '<div class="block final-answer">'
      + '<div class="role" data-i18n="block.final_answer">✅ Final answer</div></div>';
    applyDom(document);
    expect(document.querySelector(".role").textContent).toBe("✅ Final answer");

    setLang("fr");

    expect(document.querySelector(".role").textContent).toBe("✅ Réponse finale");
  });

  it("compose leurs arguments : le serveur envoie les faits, le client la phrase", async () => {
    const { setLang, applyDom } = await loadFresh();
    document.body.innerHTML =
      '<span data-i18n="block.tool_result" data-i18n-arg-name="Bash" '
      + 'data-i18n-arg-size="1 240">Bash result — 1 240 chars</span>';

    applyDom(document);
    expect(document.querySelector("span").textContent).toBe("Bash result — 1 240 chars");

    setLang("fr");
    expect(document.querySelector("span").textContent).toBe("résultat Bash — 1 240 car.");
  });
});
