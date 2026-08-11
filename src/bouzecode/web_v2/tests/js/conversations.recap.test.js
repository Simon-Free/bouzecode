import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Tests DOM — refonte UI-3 : la vue « Récap » est un sous-onglet piloté par un
// segmented control [Conversation | Recap] dans l'en-tête du panneau. On joue le
// VRAI flux client : montage → clic pastille sidebar / bouton CTA → bascule de vue.
const SCRIPT = "../../static/js/conversations.js";

// n.has_recap = true → la pastille « Récap » apparaît dans la ligne de l'agent.
const TREE = {
  nodes: [
    { key: "agent/mgr-1", parent: null, state: "finished", title: "Manager 1", branch: "develop", has_recap: true },
  ],
};
const TREE_NO_RECAP = {
  nodes: [
    { key: "agent/mgr-2", parent: null, state: "finished", title: "Manager 2", branch: "develop", has_recap: false },
  ],
};

// Payload /recap complet (recap présent) : sections textuelles + diffs triés serveur.
const RECAP_FULL = {
  recap: {
    symptoms: "Ça plantait à la fin de la conversation.",
    explanation: "On renvoyait 2 au lieu de 1 ; correctif appliqué.",
    tests: "3 tests pytest verts.",
    changes: [{ file: "src/pkg/service.py", summary: "corrige run()" }],
  },
  recap_missing: false,
  diffs: [
    {
      file: "src/pkg/service.py",
      section: "changes",
      is_test: false,
      is_new: false,
      patch: "diff --git a/src/pkg/service.py b/src/pkg/service.py\n@@ -1 +1 @@\n-return 2\n+return 1\n",
    },
    {
      file: "src/pkg/helper.py",
      section: "other",
      is_test: false,
      is_new: false,
      patch: "diff --git a/src/pkg/helper.py b/src/pkg/helper.py\n@@ -1 +1 @@\n-x\n+y\n",
    },
    {
      file: "tests/test_service.py",
      section: "tests",
      is_test: true,
      is_new: true,
      patch: "diff --git a/tests/test_service.py b/tests/test_service.py\n@@ -0,0 +1 @@\n+def test_run(): pass\n",
    },
  ],
};

// Payload /recap fallback (session historique, pas de recap) : diffs bruts alpha.
const RECAP_MISSING = {
  recap: null,
  recap_missing: true,
  note: "session interrompue, récap indisponible",
  diffs: [
    {
      file: "a.py",
      section: "all",
      is_test: false,
      is_new: false,
      patch: "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-1\n+2\n",
    },
    {
      file: "b.py",
      section: "all",
      is_test: false,
      is_new: false,
      patch: "diff --git a/b.py b/b.py\n@@ -1 +1 @@\n-3\n+4\n",
    },
  ],
};

function mountDom() {
  document.body.innerHTML = `
    <div class="conv-main">
      <aside><div id="conv-list"></div></aside>
      <form id="conv-new-bar"><textarea id="conv-new-input"></textarea>
        <button id="conv-new-send" type="submit"></button></form>
      <div id="conv-new-error"></div>
      <div id="conv-tabs"></div>
      <div id="conv-panels"><div class="conv-empty">Vide</div></div>
    </div>
  `;
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

// fetchMock : /tree → tree, /blocks → status (finished par défaut), /recap → recapPayload.
// Capture les URL /recap appelées. `blockState` permet de simuler une session non finie.
function installFetch(recapPayload, recapCalls, tree = TREE, blockState = "finished") {
  const fetchMock = vi.fn((url) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(tree) });
    }
    if (url.includes("/recap")) {
      recapCalls.push(url);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(recapPayload) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ blocks: [], total: 0, status: { state: blockState }, meta: {} }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
  global.fetch = fetchMock;
  return fetchMock;
}

// Monte le module et laisse le premier poll de l'arbre peindre la sidebar.
async function mountTree(recapPayload, recapCalls, tree = TREE, blockState = "finished") {
  mountDom();
  installFetch(recapPayload, recapCalls, tree, blockState);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

// Clic sur la pastille Récap de la ligne de l'agent → ouvre l'onglet + bascule vue récap.
async function clickRecapPill() {
  document.querySelector("#conv-list .conv-recap-pill").click();
  await flush();
}

// Ouvre l'onglet (vue conversation) sans forcer la vue récap.
async function openConversation() {
  document.querySelector("#conv-list .conv-item").click();
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_) {}
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("Récap — affordance de dépliage (caret)", () => {
  it("chaque bloc diff porte un caret en tête de summary, ouvert = ▾", async () => {
    // RECAP_FULL : 3 diffs courts (<200 lignes) → tous open par défaut → caret ▾.
    await mountTree(RECAP_FULL, []);
    await clickRecapPill();

    const blocks = [...document.querySelectorAll(".conv-pane-recap .recap-diff")];
    expect(blocks.length).toBe(3);
    for (const block of blocks) {
      const summary = block.querySelector("summary.recap-diff-head");
      const caret = summary.querySelector(".recap-diff-caret");
      // Le caret existe ET est le PREMIER enfant du summary (devant le nom de fichier).
      expect(caret).toBeTruthy();
      expect(summary.firstElementChild).toBe(caret);
      expect(caret.getAttribute("aria-hidden")).toBe("true");
      // Bloc ouvert par défaut → chevron bas.
      expect(block.open).toBe(true);
      expect(caret.textContent).toBe("▾");
    }
  });

  it("caret reflète l'état : replié = ▸, puis dépliage → ▾", async () => {
    // Gros diff (>200 lignes) → replié par défaut → caret ▸.
    const bodyLines = Array.from({ length: 300 }, (_, i) => `+line ${i}`).join("\n");
    const bigPatch =
      "diff --git a/src/pkg/big.py b/src/pkg/big.py\n@@ -0,0 +1,300 @@\n" + bodyLines + "\n";
    const payload = {
      recap: RECAP_FULL.recap,
      recap_missing: false,
      diffs: [{ file: "src/pkg/big.py", section: "changes", is_test: false, is_new: true, patch: bigPatch }],
    };
    await mountTree(payload, []);
    await clickRecapPill();
    await flush();

    const block = document.querySelector(".conv-pane-recap .recap-diff");
    const caret = block.querySelector(".recap-diff-caret");
    // Replié à l'init → chevron droit.
    expect(block.open).toBe(false);
    expect(caret.textContent).toBe("▸");

    // L'utilisateur déplie → le listener 'toggle' met le caret à jour.
    block.open = true;
    block.dispatchEvent(new Event("toggle"));
    await flush();
    expect(caret.textContent).toBe("▾");
  });
});

describe("Récap — rendu des diffs (offline, side-by-side maison)", () => {
  // Le rendu diff est 100% offline (renderDiffBlock → renderSideBySideDiff /
  // renderPreDiff dans conversations.js) : aucun CDN, aucun Monaco. Deux chemins :
  //   • payload SANS original/modified (sessions historiques) → <pre> unifié coloré ;
  //   • payload AVEC original ET modified (snapshots) → grille side-by-side .recap-sxs.

  it("payload sans original/modified : rend le <pre> coloré (add/del), pas de side-by-side", async () => {
    // RECAP_FULL ne porte ni original ni modified → fallback <pre>.
    await mountTree(RECAP_FULL, []);
    await clickRecapPill();
    await flush();

    const first = document.querySelector(".conv-pane-recap .recap-diff");
    const pre = first.querySelector("pre.recap-diff-body");
    expect(pre).toBeTruthy();
    // Le <pre> porte bien les lignes colorées à la main (add/del).
    expect(pre.querySelector(".diff-add")).toBeTruthy();
    expect(pre.querySelector(".diff-del")).toBeTruthy();
    // Pas de grille side-by-side sans snapshots.
    expect(first.querySelector(".recap-sxs")).toBeNull();
  });

  it("fallback : gros diff (>400 lignes) tronqué avec indicateur du nombre de lignes masquées", async () => {
    // Patch de 500 lignes ajoutées, sans original/modified → renderPreDiff.
    const bodyLines = Array.from({ length: 500 }, (_, i) => `+line ${i}`).join("\n");
    const bigPatch =
      "diff --git a/src/pkg/big.py b/src/pkg/big.py\n@@ -0,0 +1,500 @@\n" + bodyLines + "\n-removed line\n";
    const payload = {
      recap: RECAP_FULL.recap,
      recap_missing: false,
      diffs: [{ file: "src/pkg/big.py", section: "changes", is_test: false, is_new: true, patch: bigPatch }],
    };
    await mountTree(payload, []);
    await clickRecapPill();
    await flush();

    const first = document.querySelector(".conv-pane-recap .recap-diff");
    // Gros diff : replié par défaut (>200 lignes). On simule l'ouverture utilisateur
    // pour déclencher mount() → renderPreDiff.
    first.open = true;
    first.dispatchEvent(new Event("toggle"));
    await flush();

    const pre = first.querySelector("pre.recap-diff-body");
    expect(pre).toBeTruthy();
    // Troncature : au plus 400 lignes de diff rendues (add/del/hunk/ctx) + 1 indicateur.
    const diffLines = pre.querySelectorAll(".diff-add, .diff-del, .diff-hunk, .diff-ctx");
    expect(diffLines.length).toBe(400);
    // L'indicateur de troncature est présent et chiffre les lignes masquées.
    const trunc = pre.querySelector(".diff-truncated");
    expect(trunc).toBeTruthy();
    expect(trunc.textContent).toMatch(/more lines hidden/);
  });

  it("payload enrichi (original + modified) : rend la grille side-by-side .recap-sxs (add/del), pas de <pre>", async () => {
    // Cas ENRICHI : le diff porte original ET modified → renderSideBySideDiff.
    const payload = {
      recap: RECAP_FULL.recap,
      recap_missing: false,
      diffs: [{
        file: "src/pkg/service.py", section: "changes", is_test: false, is_new: false,
        patch: "@@ -1,1 +1,1 @@\n-    return 1\n+    return 2\n",
        original: "def run():\n    return 1\n",
        modified: "def run():\n    return 2\n",
      }],
    };
    await mountTree(payload, []);
    await clickRecapPill();
    await flush();

    const first = document.querySelector(".conv-pane-recap .recap-diff");
    const grid = first.querySelector(".recap-sxs");
    expect(grid).toBeTruthy();
    // La grille distingue les lignes égales / supprimées / ajoutées.
    expect(grid.querySelector(".sxs-row.sxs-eq")).toBeTruthy();
    expect(grid.querySelector(".sxs-row.sxs-del")).toBeTruthy();
    expect(grid.querySelector(".sxs-row.sxs-add")).toBeTruthy();
    // Le chemin side-by-side ne rend PAS le <pre> unifié.
    expect(first.querySelector("pre.recap-diff-body")).toBeNull();
  });
});

describe("Récap — pastille dans la ligne de l'agent", () => {
  it("affiche la pastille Récap quand la session a un récap (has_recap)", async () => {
    await mountTree(RECAP_FULL, []);
    const pill = document.querySelector("#conv-list .conv-recap-pill");
    expect(pill).toBeTruthy();
    expect(pill.textContent).toBe("Recap");
    expect(pill.hidden).toBe(false);
  });

  it("masque la pastille quand la session n'a PAS de récap", async () => {
    await mountTree(RECAP_FULL, [], TREE_NO_RECAP);
    const pill = document.querySelector("#conv-list .conv-recap-pill");
    expect(pill).toBeTruthy();       // l'élément existe toujours…
    expect(pill.hidden).toBe(true);  // …mais reste masqué (has_recap=false)
  });
});

describe("Récap — segmented control [Conversation | Recap]", () => {
  it("l'en-tête du panneau porte un segmented control à 2 vues", async () => {
    await mountTree(RECAP_FULL, []);
    await openConversation();

    const btns = [...document.querySelectorAll(".conv-view-switch .conv-view-btn")];
    expect(btns.length).toBe(2);
    const views = btns.map((b) => b.dataset.view);
    expect(views).toEqual(["conv", "recap"]);
    // Le lien « ← conversation » a disparu : remplacé par le segmented control.
    expect(document.querySelector(".conv-recap-back")).toBeNull();
  });

  it("un seul pane est visible à la fois", async () => {
    await mountTree(RECAP_FULL, []);
    await openConversation();

    const paneConv = document.querySelector(".conv-pane-conv");
    const paneRecap = document.querySelector(".conv-pane-recap");
    // Vue conversation par défaut.
    expect(paneConv.hidden).toBe(false);
    expect(paneRecap.hidden).toBe(true);

    // Bascule vers Recap : exactement l'autre pane visible.
    await clickRecapPill();
    expect(paneConv.hidden).toBe(true);
    expect(paneRecap.hidden).toBe(false);
  });

  it("le composer est masqué en vue Recap (footer dans le pane conversation)", async () => {
    await mountTree(RECAP_FULL, []);
    await clickRecapPill();

    const footer = document.querySelector(".conv-input");
    expect(footer).toBeTruthy();
    // Le footer/composer vit dans .conv-pane-conv, masqué en vue Recap.
    expect(footer.closest(".conv-pane-conv")).toBeTruthy();
    expect(document.querySelector(".conv-pane-conv").hidden).toBe(true);
  });

  it("le bouton Recap est grisé tant que la session n'est pas finished + tooltip", async () => {
    // Session en cours : /blocks renvoie state=running → onglet Recap désactivé.
    await mountTree(RECAP_FULL, [], TREE, "running");
    await openConversation();

    const recapBtn = document.querySelector('.conv-view-btn[data-view="recap"]');
    expect(recapBtn.disabled).toBe(true);
    expect(recapBtn.title).toContain("available once the session ends");
  });

  it("le bouton Recap est dégrisé une fois la session finished", async () => {
    await mountTree(RECAP_FULL, [], TREE, "finished");
    await openConversation();

    const recapBtn = document.querySelector('.conv-view-btn[data-view="recap"]');
    expect(recapBtn.disabled).toBe(false);
  });
});

describe("Récap — points d'entrée (pill sidebar + CTA bloc final)", () => {
  it("la pastille sidebar ouvre directement le sous-onglet Recap", async () => {
    await mountTree(RECAP_FULL, []);
    await clickRecapPill();
    expect(document.querySelector(".conv-pane-recap").hidden).toBe(false);
    expect(document.querySelector(".conv-pane-conv").hidden).toBe(true);
  });

  it("le bloc final expose un bouton « View recap → » qui bascule sur Recap", async () => {
    await mountTree(RECAP_FULL, []);
    await openConversation();

    // Session finished → CTA injecté dans le fil.
    const cta = document.querySelector(".conv-recap-cta");
    expect(cta).toBeTruthy();
    expect(cta.textContent).toContain("View recap");

    cta.click();
    await flush();
    expect(document.querySelector(".conv-pane-recap").hidden).toBe(false);
    expect(document.querySelector(".conv-pane-conv").hidden).toBe(true);
  });
});

describe("Récap — retour Conversation restaure le scroll", () => {
  it("le segmented control ramène à Conversation et restaure la position de scroll", async () => {
    await mountTree(RECAP_FULL, []);
    await openConversation();

    const conv = document.querySelector(".conv-messages");
    // L'utilisateur a scrollé dans le fil.
    conv.scrollTop = 420;

    // Bascule Recap puis retour Conversation via le segmented control.
    await clickRecapPill();
    expect(document.querySelector(".conv-pane-conv").hidden).toBe(true);

    document.querySelector('.conv-view-btn[data-view="conv"]').click();
    await flush();
    expect(document.querySelector(".conv-pane-conv").hidden).toBe(false);
    // Position de scroll du fil restaurée.
    expect(conv.scrollTop).toBe(420);
  });
});

describe("Récap — contenu (INCHANGÉ)", () => {
  it("ouvre la vue Récap et affiche les 6 sections au clic sur la pastille", async () => {
    const recapCalls = [];
    await mountTree(RECAP_FULL, recapCalls);
    await clickRecapPill();

    const pane = document.querySelector(".conv-pane-recap");
    expect(pane.hidden).toBe(false);                              // vue récap visible…
    expect(document.querySelector(".conv-pane-conv").hidden).toBe(true); // …conversation masquée

    // a/b/c : sections textuelles Symptômes / Cause-plan / Tests.
    const titles = [...pane.querySelectorAll(".recap-section-title")].map((n) => n.textContent);
    expect(titles).toContain("Symptoms");
    expect(titles).toContain("Cause / plan");
    expect(titles).toContain("Tests");
    expect(titles).toContain("Changes");
    // d : liste ordonnée des changements.
    const changeFiles = [...pane.querySelectorAll(".recap-change-file")].map((n) => n.textContent);
    expect(changeFiles).toEqual(["src/pkg/service.py"]);

    // e/f : diffs collapsibles, ordre serveur = changes → other → tests.
    const diffFiles = [...pane.querySelectorAll(".recap-diff-file")].map((n) => n.textContent);
    expect(diffFiles).toEqual(["src/pkg/service.py", "src/pkg/helper.py", "tests/test_service.py"]);

    // Titres de section de diff dans l'ordre reçu.
    const sectionTitles = [...pane.querySelectorAll(".recap-diff-section-title")].map((n) => n.textContent);
    expect(sectionTitles).toEqual(["Changes", "Other changes", "Tests"]);

    // Compteur +n/−n présent dans l'en-tête de chaque bloc.
    const first = pane.querySelector(".recap-diff");
    expect(first.querySelector(".recap-diff-add").textContent).toBe("+1");
    expect(first.querySelector(".recap-diff-del").textContent).toBe("−1");
    // Petit diff (<200 lignes) : ouvert par défaut.
    expect(first.open).toBe(true);

    // Un seul appel /recap (garde recapLoaded).
    expect(recapCalls.length).toBe(1);
  });

  it("vue manager : concatène les récaps des sous-agents (une carte par enfant)", async () => {
    const AGG = {
      recap: null,
      recap_missing: false,
      is_aggregate: true,
      diffs: [],
      children: [
        {
          agent_id: "child-a", title: "feature A",
          recap: { symptoms: "sa", explanation: "ea", tests: "ta", changes: [{ file: "src/a.py", summary: "fix a" }] },
          diffs: [{ file: "src/a.py", section: "changes", is_test: false, is_new: false, patch: "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-1\n+2\n" }],
        },
        {
          agent_id: "child-b", title: "feature B",
          recap: { symptoms: "sb", explanation: "eb", tests: "tb", changes: [{ file: "src/b.py", summary: "fix b" }] },
          diffs: [{ file: "src/b.py", section: "changes", is_test: false, is_new: false, patch: "diff --git a/src/b.py b/src/b.py\n@@ -1 +1 @@\n-3\n+4\n" }],
        },
      ],
    };
    await mountTree(AGG, []);
    await clickRecapPill();

    const pane = document.querySelector(".conv-pane-recap");
    // Une carte .recap-child par sous-agent, titrée, dans l'ordre reçu.
    const cards = [...pane.querySelectorAll(".recap-child-title")].map((n) => n.textContent);
    expect(cards).toEqual(["feature A", "feature B"]);
    // Chaque carte porte les sections + diffs de son enfant.
    const diffFiles = [...pane.querySelectorAll(".recap-diff-file")].map((n) => n.textContent);
    expect(diffFiles).toEqual(["src/a.py", "src/b.py"]);
  });

  it("montre le bandeau et les diffs bruts quand le récap est absent", async () => {
    // has_recap=true (pastille visible) mais /recap renvoie recap_missing (course rare).
    await mountTree(RECAP_MISSING, []);
    await clickRecapPill();

    const pane = document.querySelector(".conv-pane-recap");
    // Bandeau « récap non généré ».
    expect(pane.querySelector(".recap-banner")).toBeTruthy();
    // Aucune section textuelle (pas de recap).
    expect(pane.querySelectorAll(".recap-section-title").length).toBe(0);
    // Les diffs bruts sont quand même rendus, dans l'ordre reçu (alpha côté serveur).
    const diffFiles = [...pane.querySelectorAll(".recap-diff-file")].map((n) => n.textContent);
    expect(diffFiles).toEqual(["a.py", "b.py"]);
  });

  it("vue manager : enfant SANS récap → carte lien-seul (bandeau, aucune section/diff)", async () => {
    const AGG = {
      recap: null,
      recap_missing: false,
      is_aggregate: true,
      diffs: [],
      children: [
        {
          agent_id: "child-a", title: "feature A",
          recap: { symptoms: "sa", explanation: "ea", tests: "ta", changes: [{ file: "src/a.py", summary: "fix a" }] },
          diffs: [{ file: "src/a.py", section: "changes", is_test: false, is_new: false, patch: "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-1\n+2\n" }],
        },
        // Enfant sans récap structuré : uniquement un lien vers sa conversation.
        { agent_id: "child-b", title: "feature B", recap: null, diffs: [], has_recap: false },
      ],
    };
    await mountTree(AGG, []);
    await clickRecapPill();

    const pane = document.querySelector(".conv-pane-recap");
    const cards = [...pane.querySelectorAll(".recap-child")];
    expect(cards.length).toBe(2);
    // Les deux titres sont rendus et cliquables (classe .recap-child-link).
    const titles = [...pane.querySelectorAll(".recap-child-title")].map((n) => n.textContent);
    expect(titles).toEqual(["feature A", "feature B"]);
    expect(pane.querySelectorAll(".recap-child-title.recap-child-link").length).toBe(2);
    // La 2e carte (sans recap) porte le bandeau « non disponible » et AUCUN diff.
    const bBanner = cards[1].querySelector(".recap-banner");
    expect(bBanner).toBeTruthy();
    expect(bBanner.textContent).toContain("Recap unavailable");
    expect(cards[1].querySelectorAll(".recap-diff-file").length).toBe(0);
    expect(cards[1].querySelectorAll(".recap-section-title").length).toBe(0);
    // Seul l'enfant A porte des diffs.
    const diffFiles = [...pane.querySelectorAll(".recap-diff-file")].map((n) => n.textContent);
    expect(diffFiles).toEqual(["src/a.py"]);
  });

  it("vue manager : le verdict OK/KO d'un enfant s'affiche en badge séparé", async () => {
    const AGG = {
      recap: null,
      recap_missing: false,
      is_aggregate: true,
      diffs: [],
      children: [
        { agent_id: "child-a", title: "feature A", recap: null, diffs: [], has_recap: false, verdict: "OK" },
        { agent_id: "child-b", title: "feature B", recap: null, diffs: [], has_recap: false, verdict: "KO" },
      ],
    };
    await mountTree(AGG, []);
    await clickRecapPill();

    const pane = document.querySelector(".conv-pane-recap");
    const badges = [...pane.querySelectorAll(".recap-child-verdict")].map((n) => n.textContent);
    expect(badges).toEqual(["OK", "KO"]);
    // Classe de couleur dérivée du verdict (minuscule).
    expect(pane.querySelector(".recap-child-verdict-ok")).toBeTruthy();
    expect(pane.querySelector(".recap-child-verdict-ko")).toBeTruthy();
    // Le badge n'est PAS dans le titre (textContent du titre = libellé seul).
    const titles = [...pane.querySelectorAll(".recap-child-title")].map((n) => n.textContent);
    expect(titles).toEqual(["feature A", "feature B"]);
  });
});
