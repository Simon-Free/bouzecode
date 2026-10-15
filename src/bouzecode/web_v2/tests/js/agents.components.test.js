import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Page Agents — composants avec fetch simulé : champ de message (file d'attente, jamais
// d'interruption implicite, texte jamais perdu), question (options verrouillées, brouillon
// intact), barre de lancement (aucun dépôt deviné). SPEC.md §2 (R1-R5) et §5.

import { createComposer } from "../../static/js/conversations/panel/composer.js";
import { createQuestion } from "../../static/js/conversations/panel/question.js";

function res(status, body) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) });
}
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  document.body.innerHTML = "<div id='conv'></div>";
  try { localStorage.clear(); } catch (e) { console.warn(e); }
});
afterEach(() => { vi.restoreAllMocks(); });

function makeComposer(key = "agent/abc") {
  const conv = document.getElementById("conv");
  const kick = vi.fn();
  const c = createComposer({ key }, { conv: () => conv, scrollToEnd: () => {}, kick });
  document.body.appendChild(c.el);
  return { c, conv, kick };
}

describe("champ de message", () => {
  it("agent qui travaille : POST messages en mode queue, message affiché en file, JAMAIS d'interruption", async () => {
    global.fetch = vi.fn((url, init) => {
      if (url.endsWith("/messages")) return res(202, { ok: true, queued: true, queue_id: "q1", position: 1 });
      return res(200, {});
    });
    const { c } = makeComposer();
    c.update("running", []);
    c.input.value = "précise la partie SQL";
    c.el.dispatchEvent(new Event("submit", { cancelable: true }));
    await flush(); await flush(); await flush();
    const calls = global.fetch.mock.calls.map(([u]) => u);
    expect(calls).toEqual(["/api/agents/abc/messages"]);
    expect(calls.some((u) => u.includes("interrupt"))).toBe(false);
    expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toEqual({ text: "précise la partie SQL", mode: "queue" });
    expect(c.el.querySelector(".ag-queue").hidden).toBe(false);
    expect(c.el.querySelector(".ag-queue__text").textContent).toBe("précise la partie SQL");
    expect(c.input.value).toBe("");
  });

  it("409 « running » en envoi direct : on repasse en file au lieu d'interrompre", async () => {
    let n = 0;
    global.fetch = vi.fn((url, init) => {
      n += 1;
      const body = JSON.parse(init.body);
      if (body.mode !== "queue") return res(409, { error: { code: "running", message: "l'agent tourne encore" } });
      return res(202, { ok: true, queued: true, queue_id: "q2", position: 1 });
    });
    const { c } = makeComposer();
    c.update("idle", []);
    c.input.value = "et ensuite ?";
    c.el.dispatchEvent(new Event("submit", { cancelable: true }));
    for (let i = 0; i < 6; i++) await flush();
    expect(n).toBe(2);
    expect(global.fetch.mock.calls.every(([u]) => !u.includes("interrupt"))).toBe(true);
    expect(c.el.querySelector(".ag-queue__text").textContent).toBe("et ensuite ?");
  });

  it("échec d'envoi : le texte REVIENT dans le champ et l'erreur est dite", async () => {
    global.fetch = vi.fn(() => res(404, { error: { code: "agent_missing", message: "agent abc introuvable" } }));
    const { c, conv } = makeComposer();
    c.update("idle", []);
    c.input.value = "bonjour";
    c.el.dispatchEvent(new Event("submit", { cancelable: true }));
    for (let i = 0; i < 6; i++) await flush();
    expect(c.input.value).toBe("bonjour");
    expect(c.el.querySelector(".ag-composer__error").textContent).toMatch(/fiche de cet agent a disparu/);
    expect(conv.querySelector(".optimistic-echo")).toBeNull();
  });

  it("succès direct : écho immédiat du message, thread relancé", async () => {
    let resolve;
    global.fetch = vi.fn(() => new Promise((r) => { resolve = r; }));
    const { c, conv, kick } = makeComposer();
    c.update("awaiting_input", []);
    c.input.value = "ISO";
    c.el.dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    // Signal immédiat : écho « envoi… » et bouton occupé AVANT la réponse serveur.
    expect(conv.querySelector(".optimistic-echo").textContent).toMatch(/ISO/);
    expect(c.el.querySelector("button[type=submit]").getAttribute("aria-busy")).toBe("true");
    // Le champ est vidé AU MÊME INSTANT que l'écho, pas au retour du serveur (TODO 2026-09-25 §1).
    expect(c.input.value).toBe("");
    resolve({ ok: true, status: 200, text: () => Promise.resolve('{"ok":true}') });
    for (let i = 0; i < 6; i++) await flush();
    expect(kick).toHaveBeenCalled();
    expect(conv.querySelector(".ag-echo__state").textContent).toMatch(/envoyé/);
  });

  it("Entrée pendant une composition IME n'envoie pas", async () => {
    global.fetch = vi.fn(() => res(200, { ok: true }));
    const { c } = makeComposer();
    c.update("idle", []);
    c.input.value = "かな";
    c.input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true }));
    await flush();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("agent introuvable : champ désactivé avec explication", () => {
    const { c } = makeComposer();
    c.update("missing", []);
    expect(c.input.disabled).toBe(true);
    expect(c.input.placeholder).toMatch(/n'existe plus/);
  });

  it("file servie par le serveur : Annuler retire le message (DELETE)", async () => {
    global.fetch = vi.fn(() => res(200, { ok: true }));
    const { c } = makeComposer();
    c.update("running", [{ id: "q9", text: "attends", created_at: new Date().toISOString() }]);
    const cancel = [...c.el.querySelectorAll(".ag-queue__item button")].find((b) => b.textContent === "Annuler");
    cancel.click();
    for (let i = 0; i < 6; i++) await flush();
    expect(global.fetch.mock.calls[0][0]).toBe("/api/agents/abc/queue/q9");
    expect(global.fetch.mock.calls[0][1].method).toBe("DELETE");
    expect(c.el.querySelector(".ag-queue").hidden).toBe(true);
  });
});

describe("message en file : la file servie fait foi (TODO 2026-09-25 §2)", () => {
  //  Le serveur ne retire un message de la file qu'une fois LU, et marque `non_livre` celui
  //  qu'un agent arrêté ne lira jamais. Un message sorti de la file est donc lu : l'UI ne doit
  //  plus le déclarer « pas lu » sur la foi d'un minuteur, même si l'agent a fini son tour
  //  entre deux lectures et que la bulle rendue (markdown) ne reprend pas le texte brut.
  it("sorti de la file sans statut non_livre : lu, jamais signalé perdu, même 15 s après", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const { c, conv } = makeComposer();
    c.update("running", [{ id: "q1", text: "et ajoute\nun test", statut: "en_livraison", boite: true,
      created_at: new Date().toISOString() }]);
    // Même lecture : l'agent a relevé le message, l'a traité ET fini son tour. La bulle est
    // rendue en markdown (le saut de ligne devient <br>) : son texte n'est pas le texte brut.
    conv.insertAdjacentHTML("beforeend", '<div class="block user"><p>et ajoute<br>un test</p></div>');
    conv.insertAdjacentHTML("beforeend", '<div class="block assistant"><p>fait</p></div>');
    c.update("idle", []);
    c.reconcile(conv, "idle");
    vi.setSystemTime(Date.now() + 16000);
    c.update("finished", []);
    c.reconcile(conv, "finished");
    expect(c.el.querySelector(".ag-queue__lost")).toBeNull();
    expect(c.pending()).toBe(false);
    vi.useRealTimers();
  });

  it("apparu dans le fil : considéré livré, rien n'est signalé", () => {
    const { c, conv } = makeComposer();
    c.update("running", [{ id: "q2", text: "précise X", created_at: new Date().toISOString() }]);
    c.update("idle", []);
    conv.insertAdjacentHTML("beforeend", '<div class="block user"><p>précise X</p></div>');
    c.reconcile(conv, "idle");
    expect(c.pending()).toBe(false);
    expect(c.el.querySelector(".ag-queue__lost")).toBeNull();
  });

  it("lecture PARTIE avant l'accusé 202 : sa file (sans le message) ne le fait pas sortir de l'attente", async () => {
    global.fetch = vi.fn(() => res(202, { ok: true, queued: true, queue_id: "q5", position: 1, en_tour: true }));
    const { c } = makeComposer();
    c.update("running", []);
    const avantEnvoi = Date.now() - 50;           // lecture de /blocks lancée avant l'envoi…
    c.input.value = "et la doc ?";
    c.el.dispatchEvent(new Event("submit", { cancelable: true }));
    for (let i = 0; i < 6; i++) await flush();
    c.update("running", [], avantEnvoi);          // … et rendue après l'accusé : file périmée
    expect(c.el.querySelector(".ag-queue__head")).not.toBeNull();
    expect(c.el.querySelector(".ag-queue__list").textContent).toContain("et la doc ?");
  });
});

describe("envoi direct : l'accusé arrive APRÈS la consommation (TODO 2026-09-25 §2)", () => {
  it("l'agent a lu et répondu pendant le POST : rien n'est signalé perdu", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    let resolve;
    global.fetch = vi.fn(() => new Promise((r) => { resolve = r; }));
    const { c, conv } = makeComposer();
    c.update("finished", []);
    c.input.value = "corrige\nle test";
    c.el.dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    // Relance à froid : pendant le POST, les lectures de /blocks montrent déjà le message
    // (rendu markdown) et la réponse de l'agent, qui a fini son tour.
    conv.insertAdjacentHTML("beforeend", '<div class="block user"><p>corrige<br>le test</p></div>');
    conv.insertAdjacentHTML("beforeend", '<div class="block assistant"><p>corrigé</p></div>');
    resolve({ ok: true, status: 200, text: () => Promise.resolve('{"ok":true}') });
    for (let i = 0; i < 6; i++) await flush();
    c.update("finished", []);
    c.reconcile(conv, "finished");
    vi.setSystemTime(Date.now() + 16000);
    c.reconcile(conv, "finished");
    expect(c.el.querySelector(".ag-queue__lost")).toBeNull();
    expect(c.pending()).toBe(false);
    vi.useRealTimers();
  });

  it("process mort sans jamais lire : signalé après 15 s, avec Renvoyer", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    global.fetch = vi.fn(() => res(200, { ok: true }));
    const { c, conv } = makeComposer();
    c.update("idle", []);
    c.input.value = "et ajoute un test";
    c.el.dispatchEvent(new Event("submit", { cancelable: true }));
    for (let i = 0; i < 6; i++) await flush();
    c.reconcile(conv, "idle");
    expect(c.el.querySelector(".ag-queue__lost")).toBeNull();
    vi.setSystemTime(Date.now() + 16000);
    c.reconcile(conv, "finished");
    expect(c.el.querySelector(".ag-queue__lost").textContent).toMatch(/n'a pas été lu/);
    expect([...c.el.querySelectorAll(".ag-queue__lost button")].map((b) => b.textContent)).toEqual(["Renvoyer", "Ignorer"]);
    vi.useRealTimers();
  });
});

describe("question de l'agent", () => {
  const status = { state: "awaiting_input", question: "Quelle base ?", options: [{ label: "PostgreSQL" }, { label: "SQLite" }] };

  it("n'est reconstruite que si elle change (les clics ne se perdent pas)", () => {
    const q = createQuestion({ answer: vi.fn() });
    document.body.appendChild(q.el);
    q.update(status, document.getElementById("conv"));
    const first = q.el.querySelector(".ag-question__option");
    q.update({ ...status }, document.getElementById("conv"));
    expect(q.el.querySelector(".ag-question__option")).toBe(first);
  });

  it("un clic verrouille TOUTES les options ; un échec les déverrouille avec un message", async () => {
    let finish;
    const answer = vi.fn(() => new Promise((r) => { finish = r; }));
    const q = createQuestion({ answer });
    document.body.appendChild(q.el);
    q.update(status, document.getElementById("conv"));
    const [a, b] = q.el.querySelectorAll(".ag-question__option");
    a.click();
    b.click();
    expect(answer).toHaveBeenCalledTimes(1);
    expect(a.disabled && b.disabled).toBe(true);
    finish(false);
    await flush();
    expect(a.disabled || b.disabled).toBe(false);
    expect(q.el.textContent).toMatch(/n'est pas partie/);
  });

  it("disparaît quand l'agent n'attend plus", () => {
    const q = createQuestion({ answer: vi.fn() });
    q.update(status, document.getElementById("conv"));
    expect(q.el.hidden).toBe(false);
    q.update({ state: "running" }, document.getElementById("conv"));
    expect(q.el.hidden).toBe(true);
  });
});

describe("message que le serveur déclare non livré", () => {
  it("statut non_livre : signalé tout de suite avec Renvoyer / Ignorer ; Ignorer le retire du serveur", async () => {
    global.fetch = vi.fn(() => res(200, { ok: true }));
    const { c } = makeComposer();
    c.update("finished", [{ id: "q7", text: "garde la compat", statut: "non_livre", created_at: new Date().toISOString() }]);
    const lost = c.el.querySelector(".ag-queue__lost");
    expect(lost).not.toBeNull();
    expect(lost.textContent).toContain("garde la compat");
    expect(c.el.querySelector(".ag-queue__head")).toBeNull();   // rien n'« attend la fin du tour »
    const ignorer = [...lost.querySelectorAll("button")].find((b) => b.textContent === "Ignorer");
    ignorer.click();
    for (let i = 0; i < 6; i++) await flush();
    expect(global.fetch.mock.calls[0][0]).toBe("/api/agents/abc/queue/q7");
    expect(global.fetch.mock.calls[0][1].method).toBe("DELETE");
    expect(c.el.querySelector(".ag-queue").hidden).toBe(true);
  });

  it("statut en_livraison : ni « en attente » ni perdu tant que l'agent peut encore le lire", () => {
    const { c } = makeComposer();
    c.update("idle", [{ id: "q8", text: "pense au README", statut: "en_livraison", created_at: new Date().toISOString() }]);
    expect(c.el.querySelector(".ag-queue__head")).toBeNull();
    expect(c.el.querySelector(".ag-queue__lost")).toBeNull();
  });

  it("déposé dans la boîte pendant le tour : reste « en attente », lu à sa prochaine étape, annulable", () => {
    const { c } = makeComposer();
    c.update("running", [{ id: "q9", text: "et le cas vide ?", statut: "en_livraison", boite: true,
      created_at: new Date().toISOString() }]);
    expect(c.el.querySelector(".ag-queue__head").textContent).toContain("lu à sa prochaine étape");
    expect(c.el.querySelector(".ag-queue__list").textContent).toContain("et le cas vide ?");
    expect([...c.el.querySelectorAll(".ag-queue__item button")].map((b) => b.textContent)).toContain("Annuler");
  });
});
