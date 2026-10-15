import { describe, it, expect } from "vitest";

// Lot L3 : le front parle aux routes cibles (spec ticketing §6) — corps de création d'un ticket,
// isolation par défaut (D3) et message d'une intégration asynchrone (202, `integrating`).

describe("création d'un ticket depuis l'écran", () => {
  it("titre tiré du prompt, isolation par défaut `worktree`, ancienne forme `worktree+venv` normalisée", async () => {
    const { ticketBody, normalizeIsolation, DEFAULT_ISOLATION } = await import("../../static/js/conversations/model.js");
    expect(DEFAULT_ISOLATION).toBe("worktree");
    expect(ticketBody({ prompt: "\n  Corrige le bug\nsuite", isolation: "" })).toEqual({
      title: "Corrige le bug", prompt: "\n  Corrige le bug\nsuite", typology: "default",
      isolation: "worktree", launch: true, defer: true });
    expect(normalizeIsolation("worktree+venv")).toBe("worktree_venv");
    expect(normalizeIsolation("bidon")).toBe("worktree");
  });
});

describe("intégration d'un passage du Bureau", () => {
  it("202 integrating : annoncée lancée, jamais « intégrée »", async () => {
    const { messageIntegration } = await import("../../static/js/bureau/actions.js");
    expect(messageIntegration({ ok: true, state: "integrating" })).toMatch(/en cours/);
    expect(messageIntegration({ ok: true, state: "integrating" })).not.toMatch(/intégré\b/);
    expect(messageIntegration({ ok: true, state: "closed", message: "Fusionné." })).toBe("Fusionné.");
  });
});
