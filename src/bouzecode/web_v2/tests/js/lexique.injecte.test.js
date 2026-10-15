import { describe, it, expect, beforeEach, vi } from "vitest";

// Le lexique UNIQUE vient du serveur (services/work/lexique.py), injecté par base.html dans
// <script id="bz-lexique">. Le JS ne garde que des valeurs par défaut : c'est la table servie
// qui fait foi, pour les badges de tâche, les états d'agent ET les motifs « À traiter ».

function injecter(table) {
  document.body.innerHTML = "";
  const s = document.createElement("script");
  s.type = "application/json";
  s.id = "bz-lexique";
  s.textContent = JSON.stringify(table);
  document.body.appendChild(s);
}

const TABLE = {
  entrees: {
    brouillon: { mot: "Pas lancée (serveur)", aide: "aide serveur", ton: "neutral", icone: "○" },
    crashed: { mot: "Arrêt (serveur)", aide: "aide agent", ton: "danger", icone: "!" },
    a_repondre: { mot: "Réponds (serveur)", aide: "aide question", ton: "warn", icone: "?" },
  },
  motifs: { question: "a_repondre" },
  tickets: {},
};

beforeEach(() => { vi.resetModules(); });

describe("lexique injecté par le serveur", () => {
  it("les statuts de tâche, les états d'agent et les motifs prennent les mots du serveur", async () => {
    injecter(TABLE);
    const states = await import("../../static/js/lib/states.js");
    const attention = await import("../../static/js/bureau/attention.js");
    expect(states.taskStatus("brouillon").label).toBe("Pas lancée (serveur)");
    expect(states.taskStatus("brouillon").hint).toBe("aide serveur");
    expect(states.agentState("crashed").label).toBe("Arrêt (serveur)");
    expect(attention.MOTIFS.question.mot).toBe("Réponds (serveur)");
    expect(states.entreeLexique("crashed").label).toBe("Arrêt (serveur)");
  });

  it("sans lexique injecté, les valeurs par défaut (égales à la table serveur) s'appliquent", async () => {
    document.body.innerHTML = "";
    const states = await import("../../static/js/lib/states.js");
    expect(states.taskStatus("brouillon").label).toBe("À lancer");
    expect(states.taskStatus("a_decider").label).toBe("À décider");
    expect(states.taskStatus("en_echec").label).toBe(states.agentState("crashed").label);
  });
});
