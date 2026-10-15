import { describe, it, expect, vi, afterEach } from "vitest";

// Page Agents — onglet Récap : la vérification périodique (à chaque lecture du fil, ~1,5 s) ne
// redessine RIEN tant que le récap n'a pas changé, même sans `recap_version` (pas encore de récap
// structuré, seulement des diffs) ni quand seule la session a été réécrite : un diff déplié le
// reste, la position de lecture aussi.

import { createRecapView } from "../../static/js/conversations/panel/recap.js";

const json = (corps, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });
const flush = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };

afterEach(() => { vi.restoreAllMocks(); });

describe("onglet Récap", () => {
  it.each([
    ["sans récap structuré (pas de recap_version)", { recap: null, recap_missing: true }],
    ["avec récap, session réécrite à chaque tour", { recap: { symptoms: "ça plante" }, recap_version: "v1" }],
  ])("%s : la vérification périodique ne redessine pas", async (_nom, recap) => {
    const payload = { ...recap, diffs: [{ section: "changes", file: "src/app.py", diff: "--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n" }] };
    let mtime = 0;  // recap_version = mtime de la session : il bouge à chaque tour de l'agent
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(json(
      payload.recap_version ? { ...payload, recap_version: `v${++mtime}` } : payload)));
    document.body.innerHTML = "<div id='pane'></div>";
    const pane = document.getElementById("pane");
    const view = createRecapView({ key: "agent/a1" }, pane);
    view.show();
    await flush();
    const corps = pane.querySelector(".ag-recap");
    const premier = corps.firstElementChild;
    expect(premier).not.toBeNull();
    const diff = corps.querySelector("details");
    if (diff) diff.open = true;
    for (let i = 0; i < 3; i++) { view.maybeRefresh(); await flush(); }
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(4);
    expect(corps.firstElementChild).toBe(premier);
    expect(corps.querySelector(".skeleton")).toBeNull();
    if (diff) expect(corps.querySelector("details")).toBe(diff);
  });
});
