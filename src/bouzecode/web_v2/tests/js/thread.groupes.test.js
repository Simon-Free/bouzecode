import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Fil d'une conversation (page Agents ET tiroir de l'assistant) vu par l'utilisateur : les tours
// consécutifs du modèle forment UN groupe, séparés par une fine ligne ; un message de
// l'utilisateur ouvre un nouveau groupe ; le texte en cours s'écrit dans le groupe courant ; un
// outil déplié le reste quand de nouveaux blocs arrivent.

import { appendBlocks, renderStreamingPartial, startSessionThread } from "../../static/js/shared/session_thread.js";

const user = (t) => ({ html: `<div class="block user pui-bubble pui-bubble--user"><p>${t}</p></div>` });
const tour = (t, outils = "") => ({
  html: `<div class="block assistant pui-bubble pui-bubble--ai"><p>${t}</p>${outils}</div>`,
});
const outils = '<details class="tools-group"><summary>2 outils · Read, Bash</summary>'
  + '<details class="tc toolcall" data-tool-id="t1"><summary>Read</summary><pre>{}</pre></details></details>';
const resultat = { html: '<details class="tr" data-tool-call-id="t1"><summary>résultat Read</summary><pre>ok</pre></details>' };
const finale = { html: '<div class="block final-answer"><div class="role">✅ Réponse finale</div><p>Fini.</p></div>' };

let fil;
beforeEach(() => {
  document.body.innerHTML = '<div class="conv-messages" id="fil"></div>';
  fil = document.getElementById("fil");
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

const enfants = (el, cls) => [...el.children].filter((c) => c.classList.contains(cls));
const groupes = () => enfants(fil, "turn-group");
const separateurs = (g) => enfants(g, "turn-sep").length;

describe("tours du modèle regroupés", () => {
  it("N tours consécutifs du modèle → un seul groupe, N-1 fines lignes, résultats et réponse finale dedans", () => {
    appendBlocks(fil, [user("Ajoute un NOTES.md"), tour("Je regarde.", outils), resultat, tour("Je lis le README."),
      tour("J'écris la note."), finale]);
    expect(enfants(fil, "user")).toHaveLength(1);
    expect(groupes()).toHaveLength(1);
    const [g] = groupes();
    expect(enfants(g, "assistant")).toHaveLength(3);
    expect(separateurs(g)).toBe(2);
    expect(g.lastElementChild.classList.contains("final-answer")).toBe(true);
    expect(g.textContent).toContain("résultat Read");
  });

  it("un message de l'utilisateur entre deux → deux groupes, dans l'ordre du fil", () => {
    appendBlocks(fil, [user("Q1"), tour("R1a"), tour("R1b")]);
    appendBlocks(fil, [user("Q2"), tour("R2")]);
    const ordre = [...fil.children].map((el) => (el.classList.contains("turn-group") ? "modèle" : "vous"));
    expect(ordre).toEqual(["vous", "modèle", "vous", "modèle"]);
    expect(groupes().map(separateurs)).toEqual([1, 0]);
  });

  it("un tour qui arrive au poll suivant rejoint le groupe ouvert, avec sa fine ligne", () => {
    appendBlocks(fil, [user("Q"), tour("Premier tour")]);
    appendBlocks(fil, [tour("Deuxième tour")]);
    expect(groupes()).toHaveLength(1);
    expect(separateurs(groupes()[0])).toBe(1);
  });
});

describe("tour en cours de production", () => {
  it("le texte streamé s'écrit DANS le groupe courant, puis le bloc rendu prend sa place au même endroit", () => {
    appendBlocks(fil, [user("Q"), tour("Premier tour")]);
    renderStreamingPartial(fil, { phase: "text", text: "Je continue…" });
    const [g] = groupes();
    expect(g.querySelector(".streaming-turn .streaming-block").textContent).toBe("Je continue…");
    expect(enfants(fil, "streaming-block")).toHaveLength(0);

    appendBlocks(fil, [tour("Je continue… et c'est fait.")]);
    expect(groupes()).toEqual([g]);
    expect(fil.querySelector(".streaming-turn")).toBeNull();
    expect(separateurs(g)).toBe(1);
  });

  it("premier tour d'une réponse : le streaming ouvre le groupe, qui disparaît si rien n'arrive", () => {
    appendBlocks(fil, [user("Q")]);
    renderStreamingPartial(fil, { phase: "thinking", thinking: "Je réfléchis" });
    expect(groupes()).toHaveLength(1);
    renderStreamingPartial(fil, {});
    expect(groupes()).toHaveLength(0);
  });

  it("un message de l'utilisateur après un streaming purgé ne laisse pas de groupe vide avant lui", () => {
    appendBlocks(fil, [user("Q1"), tour("R1")]);
    renderStreamingPartial(fil, { phase: "text", text: "…" });
    appendBlocks(fil, [user("Q2")]);
    expect([...fil.children].map((el) => el.className.split(" ")[0])).toEqual(["block", "turn-group", "block"]);
  });
});

/** Faux serveur /blocks qui honore `after` et numérote les blocs (`idx`), comme routes/sessions/blocs.py.
 *  `etat()` rend la session du moment : {messages, state}. */
function serveur(etat) {
  global.fetch = vi.fn((url) => {
    let body = { phase: "text", text: "" };
    if (url.includes("/blocks")) {
      const { messages, state } = etat();
      const after = Number(new URL(url, "http://x").searchParams.get("after") || 0);
      body = { blocks: messages.slice(after).map((b, i) => ({ ...b, idx: after + i })), total: messages.length,
        status: { state } };
    }
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) });
  });
}

describe("échos des messages envoyés", () => {
  it("deux messages envoyés coup sur coup : leurs deux échos partent quand les deux blocs arrivent", () => {
    appendBlocks(fil, [user("Q"), tour("R")]);
    for (const t of ["Premier ajout", "Second ajout"]) {
      const el = document.createElement("div");
      el.className = "bz-echo optimistic-echo";
      el.innerHTML = `<div class="bz-echo__txt">${t}</div><span class="bz-echo__etat">envoyé</span>`;
      fil.appendChild(el);
    }
    appendBlocks(fil, [user("Premier ajout"), user("Second ajout"), tour("Vu.")]);
    expect(fil.querySelectorAll(".optimistic-echo")).toHaveLength(0);
    expect(enfants(fil, "user").map((el) => el.textContent)).toEqual(["Q", "Premier ajout", "Second ajout"]);
  });
});

describe("rafraîchissement du fil", () => {
  it("fil réécrit (tour interrompu retiré à la reprise) : le message qui prend sa place s'affiche quand même", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let session = { messages: [user("Rédige"), tour("Tour coupé…")], state: "running" };
    serveur(() => session);
    const run = startSessionThread({ key: "agent/a1", container: fil });
    await vi.advanceTimersByTimeAsync(0);
    expect(fil.textContent).toContain("Tour coupé");
    //  La reprise retire le message éphémère : « Et maintenant ? » prend l'index 1, la réponse le 2.
    session = { messages: [user("Rédige"), user("Et maintenant ?"), tour("Voici ma réponse")], state: "running" };
    await vi.advanceTimersByTimeAsync(1600);
    run.stop();
    expect(fil.textContent).not.toContain("Tour coupé");
    expect(enfants(fil, "user").map((el) => el.textContent)).toEqual(["Rédige", "Et maintenant ?"]);
    expect(fil.textContent).toContain("Voici ma réponse");
  });

  it("fil arrêté pendant une lecture (autre conversation ouverte) : rien de l'ancien fil ne s'insère", async () => {
    let relacher;
    global.fetch = vi.fn(() => new Promise((ok) => { relacher = () => ok({ ok: true, status: 200,
      text: () => Promise.resolve(JSON.stringify({ blocks: [{ ...user("Ancien fil"), idx: 0 }], total: 1,
        status: { state: "running" } })) }); }));
    const run = startSessionThread({ key: "agent/a1", container: fil });
    run.stop();
    relacher();
    await new Promise((r) => setTimeout(r, 0));
    expect(fil.textContent).not.toContain("Ancien fil");
  });

  it("un outil déplié reste déplié (même élément) quand de nouveaux blocs arrivent au poll suivant", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let lectures = 0;
    serveur(() => (lectures++ === 0
      ? { messages: [user("Q"), tour("Je regarde.", outils)], state: "running" }
      : { messages: [user("Q"), tour("Je regarde.", outils), tour("Suite.")], state: "finished" }));
    const run = startSessionThread({ key: "agent/a1", container: fil });
    await vi.advanceTimersByTimeAsync(0);
    const details = fil.querySelector("details.tools-group");
    details.open = true;
    await vi.advanceTimersByTimeAsync(1600);
    run.stop();
    expect(fil.querySelector("details.tools-group")).toBe(details);
    expect(details.open).toBe(true);
    expect(groupes()).toHaveLength(1);
    expect(separateurs(groupes()[0])).toBe(1);
  });
});
