import { describe, it, expect } from "vitest";

// Lexique unique des états (SPEC §1.1 / §1.2) : un mot technique du backend ne sort jamais
// tel quel, et chaque état a icône + libellé (jamais la couleur seule).

import {
  AGENT_STATES, TASK_STATUSES, AGENT_GROUPS, TASK_SEGMENTS, agentStateKey, agentState,
  isAgentActive, taskStatusKey, taskStatus, badge,
} from "../../static/js/lib/states.js";

describe("agents", () => {
  const cases = [
    [{ state: "running" }, "running"],
    [{ state: "running", phase: "demarrage" }, "preparing"],
    [{ state: "running", phase: "attente_modele" }, "thinking"],
    [{ state: "provisioning" }, "preparing"],
    [{ state: "starting" }, "preparing"],
    [{ state: "awaiting_input" }, "awaiting_input"],
    [{ state: "awaiting_plan_validation" }, "awaiting_plan_validation"],
    [{ state: "finished", liveness: "crashed" }, "crashed"],
    [{ state: "finished", interrupted: true }, "crashed"],
    [{ state: "finished", suspect_dead: true }, "crashed"],
    [{ state: "launch_failed" }, "launch_failed"],
    [{ state: "finished", launch_failed: true }, "launch_failed"],
    [{ state: "idle" }, "idle"],
    [{ state: "finished" }, "finished"],
    [{ state: "cli" }, "finished"],
    [{ state: "waiting_children" }, "orchestrating"],
    [{ state: "running", archived: true }, "archived"],
    [{ state: "awaiting_input", liveness: "crashed" }, "awaiting_input"],
    [{ state: "zorglub" }, "unknown"],
    [null, "unknown"],
    ["running", "running"],
  ];
  it.each(cases)("%j → %s", (node, key) => {
    expect(agentStateKey(node)).toBe(key);
  });

  it("un agent fini avec des enfants vivants orchestre", () => {
    expect(agentStateKey({ state: "finished" }, { hasLiveChildren: true })).toBe("orchestrating");
  });

  it("aucun libellé ne réutilise un mot technique banni", () => {
    const banned = /\b(running|idle|cli|chaud|finished|crashed|awaiting|provisioning)\b/i;
    for (const s of Object.values(AGENT_STATES)) {
      expect(s.label).not.toMatch(banned);
      expect(s.icon.length).toBeGreaterThan(0);
      expect(["info", "warn", "danger", "ok", "neutral"]).toContain(s.tone);
      expect(AGENT_GROUPS.map((g) => g.key)).toContain(s.group);
    }
  });

  it("agentState et isAgentActive", () => {
    expect(agentState({ state: "awaiting_input" })).toMatchObject({ key: "awaiting_input", label: "Attend ta réponse", tone: "warn", group: "a_traiter" });
    expect(agentState("crashed").label).toBe("Arrêté sans finir");
    expect(isAgentActive({ state: "running" })).toBe(true);
    expect(isAgentActive({ state: "provisioning" })).toBe(true);
    expect(isAgentActive({ state: "finished" })).toBe(false);
    expect(isAgentActive({ state: "awaiting_input" })).toBe(false);
  });
});

describe("tâches", () => {
  const cases = [
    [{ statut: "en_cours" }, "en_cours"],
    [{ statut: "inactif", raison: "a_faire" }, "brouillon"],
    [{ statut: "inactif", raison: "a_decider" }, "a_decider"],
    [{ statut: "inactif", raison: "a_repondre" }, "a_repondre"],
    [{ statut: "inactif", raison: "a_relire" }, "a_relire"],
    [{ statut: "inactif", raison: "figee" }, "en_echec"],
    [{ statut: "inactif", raison: "en_echec" }, "en_echec"],
    [{ statut: "archive", raison: "faite" }, "faite"],
    [{ statut: "archive", raison: "abandonnee" }, "abandonnee"],
    [{ statut: "a_relire" }, "a_relire"],
    [{ etat: "brouillon" }, "brouillon"],
    [{ etat: "brouillon", decision: true }, "a_decider"],
    [{ etat: "lancee" }, "en_cours"],
    [{ etat: "faite" }, "faite"],
    ["a_repondre", "a_repondre"],
    ["inconnu", "brouillon"],
  ];
  it.each(cases)("%j → %s", (t, key) => {
    expect(taskStatusKey(t)).toBe(key);
  });

  it("segments : À moi regroupe répondre, relire, échec, trancher", () => {
    const aMoi = Object.entries(TASK_STATUSES).filter(([, s]) => s.segment === "a_moi").map(([k]) => k).sort();
    expect(aMoi).toEqual(["a_decider", "a_relire", "a_repondre", "en_echec"]);
    for (const s of Object.values(TASK_STATUSES)) expect(TASK_SEGMENTS.map((g) => g.key)).toContain(s.segment);
    expect(taskStatus("a_repondre").rank).toBeLessThan(taskStatus("brouillon").rank);
  });
});

describe("badge()", () => {
  it("porte ton, icône, libellé, infobulle", () => {
    const b = badge(agentState("awaiting_input"));
    expect(b.className).toBe("badge");
    expect(b.dataset.tone).toBe("warn");
    expect(b.dataset.state).toBe("awaiting_input");
    expect(b.querySelector(".badge__icon").textContent).toBe("?");
    expect(b.querySelector(".badge__label").textContent).toBe("Attend ta réponse");
    expect(b.title).toContain("Attend ta réponse");
  });

  it("compact garde le libellé dans le DOM (lecteurs d'écran) et pulse si vivant", () => {
    const b = badge(agentState("running"), { compact: true });
    expect(b.classList.contains("badge--compact")).toBe(true);
    expect(b.dataset.pulse).toBe("true");
    expect(b.querySelector(".badge__label").textContent).toBe("En cours");
  });
});
