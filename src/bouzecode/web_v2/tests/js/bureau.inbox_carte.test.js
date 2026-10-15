import { describe, it, expect, vi, afterEach } from "vitest";

// Carte d'un signalement hors tâche (/api/inbox, type "signalement") : son agent est souvent un
// pseudo-agent de process ("process:4392") sans fiche — « Ouvrir la conversation » mène à un agent
// introuvable. La carte doit donc offrir « Acquitter » (POST /api/signalements/<id>/acquitter)
// pour pouvoir la retirer, et ne pas proposer d'ouvrir une conversation qui n'existe pas.

import { contenuCarte } from "../../static/js/bureau/inbox_carte.js";

// Forme réelle relevée sur /api/inbox (inbox_signalements.cartes).
const SIGNALEMENT = { type: "signalement", id: "signalement:s1", signalement_id: "s1", titre: "Proxy KO",
  agent_id: "process:4392", key: "process:4392", projet_slug: "", tache: null,
  actions: ["acquitter", "ouvrir"] };

function boutons(nodes) {
  const box = document.createElement("div");
  nodes.forEach((n) => box.appendChild(n));
  document.body.appendChild(box);
  return box;
}

afterEach(() => { document.body.innerHTML = ""; vi.unstubAllGlobals(); });

describe("carte signalement hors tâche", () => {
  it("propose Acquitter et pas d'ouverture de conversation pour un pseudo-agent process:", () => {
    const box = boutons(contenuCarte(SIGNALEMENT));
    const libelles = [...box.querySelectorAll("button, a")].map((b) => b.textContent);
    expect(libelles).toContain("Acquitter");
    expect(libelles).not.toContain("Ouvrir la conversation");
  });

  it("garde Ouvrir pour un signalement d'un vrai agent", () => {
    const box = boutons(contenuCarte({ ...SIGNALEMENT, agent_id: "a12", key: "a12" }));
    const libelles = [...box.querySelectorAll("button, a")].map((b) => b.textContent);
    expect(libelles).toContain("Acquitter");
    expect(libelles).toContain("Ouvrir la conversation");
  });

  it("Acquitter appelle POST /api/signalements/<id>/acquitter", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }),
      { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const box = boutons(contenuCarte(SIGNALEMENT));
    const b = [...box.querySelectorAll("button")].find((x) => x.textContent === "Acquitter");
    b.click();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/signalements/s1/acquitter");
    expect((opts && opts.method) || "").toBe("POST");
  });
});
