import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";

// LE DÉFAUT À TUER : une carte « en cours » ne disait RIEN de ce que l'agent faisait.
// Mesuré sur l'agent eac1f0bef295 : onze minutes de « en cours » pendant qu'il pilotait un
// outil, sans que l'utilisateur puisse le distinguer d'un agent bloqué. Le backend sert
// désormais les FAITS (`activity`, `activity_live`, `idle_seconds`, `phase`), sa propre
// phrase française (`activity_label` / `phase_label`) et un drapeau de silence anormal
// (`stale`). L'interface étant bilingue, elle recompose la phrase à partir des faits ; ces
// tests prouvent que la carte la MONTRE, et qu'un node servi sans `activity_live` (cache
// antérieur au champ) retombe sur la phrase du serveur plutôt que d'affirmer un faux.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(__dirname, "../../static/js/conversations.js");

const KEY = "agent/eac1f0bef295";

const NODE_AU_TRAVAIL = {
  key: KEY, agent_id: "eac1f0bef295", parent: null, state: "running", liveness: "running",
  turn_count: 9, title: "Déployer sur Azure", title_full: "Déployer la branche develop",
  started_at: "2026-07-30T08:43:09Z",
  activity: "Bash", activity_live: true,
  activity_label: "Bash en cours depuis 3 min", idle_seconds: 180,
  turn: 9, stale: false,
};

const NODE_EN_PREPARATION = {
  key: "launching/042828f3", agent_id: "042828f3", ticket_id: "042828f3", parent: null,
  state: "provisioning", liveness: "running", turn_count: 0, title: "Nouvelle conversation",
  started_at: "2026-07-30T08:43:00Z",
  phase: "provisioning_worktree", phase_label: "création du worktree",
  phase_detail: "depuis develop",
};

const BLOCKS = { blocks: [], total: 0, meta: { model: "opus" }, status: { state: "running" } };

function mountDom() {
  document.body.innerHTML = `
    <aside><div id="conv-list"></div></aside>
    <form id="conv-new-bar"><textarea id="conv-new-input"></textarea>
      <button id="conv-new-send" type="submit"></button></form>
    <div id="conv-new-error"></div>
    <div id="conv-tabs"></div>
    <div id="conv-panels"><div class="conv-empty">Vide</div></div>
  `;
}

function installFetch(tree) {
  global.fetch = vi.fn((url) => {
    if (url.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(tree) });
    }
    if (url.includes("/blocks")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(BLOCKS) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

async function loadModule(nodes) {
  mountDom();
  installFetch({ nodes, total_roots: nodes.length });
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
}

function carte(key) {
  return document.querySelector(`#conv-list .conv-item[data-key="${key}"]`);
}

beforeEach(() => {
  vi.useFakeTimers();
  try { localStorage.clear(); } catch (_e) { /* pas de localStorage */ }
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("une carte dit ce que l'agent est en train de faire", () => {
  it("l'outil en cours et son ancienneté s'affichent sur la carte", async () => {
    await loadModule([NODE_AU_TRAVAIL]);

    const chip = carte(KEY).querySelector(".conv-item-activity");
    expect(chip).toBeTruthy();
    // Phrase RECOMPOSÉE depuis activity + activity_live + idle_seconds, pas le libellé
    // français du serveur : c'est ce qui la rend traduisible.
    expect(chip.textContent).toBe("Bash running for 3 min");
    expect(chip.classList.contains("is-stale")).toBe(false);
  });

  it("un node servi SANS activity_live retombe sur la phrase du serveur", async () => {
    // Cache antérieur au champ `activity_live` : « en cours » et « dernier outil vu » sont
    // indécidables côté client. Rendre la phrase du serveur vaut mieux qu'en affirmer une
    // fausse — le libellé reste français, mais il est EXACT.
    const { activity_live: _omis, ...sansLive } = NODE_AU_TRAVAIL;
    await loadModule([sansLive]);

    const chip = carte(KEY).querySelector(".conv-item-activity");
    expect(chip.textContent).toBe("Bash en cours depuis 3 min");
  });

  it("un silence anormal est signalé PAR DU TEXTE, jamais par un point seul", async () => {
    await loadModule([{ ...NODE_AU_TRAVAIL,
      activity_label: "Bash en cours depuis 12 min", idle_seconds: 720, stale: true }]);

    const chip = carte(KEY).querySelector(".conv-item-activity");
    expect(chip.classList.contains("is-stale")).toBe(true);
    expect(chip.textContent).toContain("12 min");
    // L'alerte explique son critère au survol, et se garde EXPLICITEMENT de conclure.
    expect(chip.title).toContain("heartbeat");
    expect(chip.title).toContain("not a death certificate");
  });

  it("un ticket en préparation dit « préparation… » et l'étape en cours", async () => {
    await loadModule([NODE_EN_PREPARATION]);

    const row = carte("launching/042828f3");
    // La vignette de sidebar est compacte (point + tooltip) : le mot vit dans le tooltip du
    // badge et dans la description de la carte. Ce qui compte : plus jamais « provisioning ».
    expect(row.querySelector(".badge").title).toContain("preparing…");
    expect(row.title).toContain("preparing…");
    expect(row.title).not.toContain("provisioning");
    // L'ÉTAPE, elle, est du texte visible sur la carte : c'est la réponse à « il fait quoi ? »
    // La phase est traduite depuis sa CLÉ ; `phase_detail` porte une donnée (la base du
    // worktree), pas un libellé : il reste tel que le serveur l'a composé.
    const chip = row.querySelector(".conv-item-activity");
    expect(chip.textContent).toBe("creating the worktree — depuis develop");
  });

  it("un agent terminé n'affiche aucune activité", async () => {
    await loadModule([{ key: "agent/ffffff", agent_id: "ffffff", parent: null,
      state: "finished", liveness: "delivered", turn_count: 4, title: "Fini",
      started_at: "2026-07-29T08:00:00Z" }]);

    expect(carte("agent/ffffff").querySelector(".conv-item-activity")).toBeNull();
  });
});
