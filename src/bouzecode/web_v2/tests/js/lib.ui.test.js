import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Gateway UI partagé (static/js/lib/ui.js) : chaque helper tient une règle de SPEC.md §2.
// api() → R4 (erreur lisible, jamais de 200 {ok:false} pris pour un succès)
// busy()/lock() → R1 + R5 (signal immédiat, pas de double action)
// toast/confirm/failed/empty/skeleton/dirty/highlight/menu → R2, R3, R4, R6, R9, R10.

import {
  api, ApiError, errorMessage, busy, isBusy, lock, toast, confirm, dirty, skeleton, empty, failed,
  highlight, menu, relTime, escapeHtml, h,
} from "../../static/js/lib/ui.js";

function jsonResponse(status, body, { raw } = {}) {
  const text = raw !== undefined ? raw : (body === undefined ? "" : JSON.stringify(body));
  return Promise.resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(text) });
}

beforeEach(() => {
  document.body.innerHTML = "";
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("api()", () => {
  it("renvoie le JSON décodé et envoie le corps en JSON", async () => {
    global.fetch = vi.fn(() => jsonResponse(200, { ok: true, id: 7 }));
    const data = await api("post", "/api/x", { a: 1 });
    expect(data).toEqual({ ok: true, id: 7 });
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/x");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ a: 1 });
  });

  it("joint le jeton local de la page sur une mutation, jamais sur une lecture", async () => {
    document.head.innerHTML = '<meta name="bouzecode-token" content="jeton-123">';
    global.fetch = vi.fn(() => jsonResponse(200, {}));
    await api("POST", "/api/x", { a: 1 });
    await api("GET", "/api/x");
    expect(global.fetch.mock.calls[0][1].headers["X-Bouzecode-Token"]).toBe("jeton-123");
    expect(global.fetch.mock.calls[1][1].headers["X-Bouzecode-Token"]).toBeUndefined();
    document.head.innerHTML = "";
  });

  it("expose error.code de la forme unique {error:{code,message}}", async () => {
    global.fetch = vi.fn(() => jsonResponse(409, { error: { code: "running", message: "il tourne" } }));
    await expect(api("POST", "/api/x", {})).rejects.toMatchObject({ message: "il tourne", code: "running" });
  });

  it("lit {error:'…'} et {error:{message}} et expose status + data", async () => {
    global.fetch = vi.fn(() => jsonResponse(400, { error: "titre est obligatoire" }));
    await expect(api("POST", "/api/x", {})).rejects.toMatchObject({ message: "titre est obligatoire", status: 400 });
    global.fetch = vi.fn(() => jsonResponse(409, { error: { code: "running", message: "l'agent travaille" } }));
    const err = await api("POST", "/api/x", {}).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("l'agent travaille");
    expect(err.code).toBe("running");
    expect(err.data.error.code).toBe("running");
  });

  it("une page HTML d'erreur (proxy) donne un message lisible, pas un succès", async () => {
    global.fetch = vi.fn(() => jsonResponse(502, undefined, { raw: "<html><body>Bad gateway</body></html>" }));
    const err = await api("GET", "/api/x").catch((e) => e);
    expect(err.status).toBe(502);
    expect(err.message).toBe("Erreur du serveur (502).");
  });

  it("okField : un HTTP 200 {ok:false} est une ERREUR", async () => {
    global.fetch = vi.fn(() => jsonResponse(200, { ok: false, error: "dépôt demo inconnu" }));
    await expect(api("POST", "/api/x", {}, { okField: "ok" })).rejects.toMatchObject({ message: "dépôt demo inconnu", code: "not_ok" });
    global.fetch = vi.fn(() => jsonResponse(200, { ok: false }));
    await expect(api("POST", "/api/x", {}, { okField: true })).rejects.toMatchObject({ message: "L'opération a échoué." });
  });

  it("réseau coupé : ApiError status 0 et événement ui:net ok:false", async () => {
    const seen = [];
    const on = (e) => seen.push(e.detail.ok);
    window.addEventListener("ui:net", on);
    global.fetch = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));
    const err = await api("GET", "/api/x").catch((e) => e);
    expect(err.status).toBe(0);
    expect(err.code).toBe("network");
    expect(err.message).toMatch(/injoignable/);
    global.fetch = vi.fn(() => jsonResponse(200, {}));
    await api("GET", "/api/x");
    window.removeEventListener("ui:net", on);
    expect(seen).toEqual([false, true]);
  });

  it("délai dépassé : status -1", async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn((url, init) => new Promise((_, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    const p = api("GET", "/api/lent", undefined, { timeout: 1000 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1001);
    const err = await p;
    expect(err.status).toBe(-1);
    expect(err.message).toMatch(/pas répondu à temps/);
  });

  it("accepte les réponses simulées {ok, json} des anciens tests", async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ a: 1 }) }));
    expect(await api("GET", "/api/x")).toEqual({ a: 1 });
  });

  it("errorMessage couvre les formes usuelles", () => {
    expect(errorMessage({ message: "m" }, 400)).toBe("m");
    expect(errorMessage({ errors: ["a", "b"] }, 400)).toBe("a ; b");
    expect(errorMessage(null, 404)).toBe("Introuvable (404).");
    expect(errorMessage(null, 418)).toBe("Requête refusée (HTTP 418).");
  });
});

describe("busy() et lock()", () => {
  it("désactive, pose aria-busy et le libellé, puis restaure", async () => {
    const btn = h("button", { class: "btn" }, "Lancer");
    document.body.appendChild(btn);
    let resolve;
    const p = busy(btn, "Lancement…", () => new Promise((r) => { resolve = r; }));
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("aria-busy")).toBe("true");
    expect(btn.textContent).toBe("Lancement…");
    expect(isBusy(btn)).toBe(true);
    resolve(42);
    expect(await p).toBe(42);
    expect(btn.disabled).toBe(false);
    expect(btn.hasAttribute("aria-busy")).toBe(false);
    expect(btn.textContent).toBe("Lancer");
  });

  it("un second clic pendant l'action ne relance pas fn (anti double-clic)", async () => {
    const btn = h("button", {}, "Go");
    const fn = vi.fn(() => new Promise((r) => setTimeout(r, 10)));
    const a = busy(btn, null, fn);
    const b = busy(btn, null, fn);
    await Promise.all([a, b]);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("restaure le bouton même si fn lève, et propage l'erreur", async () => {
    const btn = h("button", {}, "Go");
    await expect(busy(btn, "…", () => { throw new Error("boom"); })).rejects.toThrow("boom");
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toBe("Go");
  });

  it("garde un bouton initialement désactivé désactivé", async () => {
    const btn = h("button", { disabled: true }, "Go");
    await busy(btn, "…", () => 1);
    expect(btn.disabled).toBe(true);
  });

  it("lock() passe le champ en lecture seule et ignore une seconde soumission", async () => {
    const input = h("input", {});
    const fn = vi.fn(() => new Promise((r) => setTimeout(r, 5)));
    const p1 = lock(input, fn);
    expect(input.readOnly).toBe(true);
    expect(input.getAttribute("aria-busy")).toBe("true");
    await lock(input, fn);
    await p1;
    expect(fn).toHaveBeenCalledTimes(1);
    expect(input.readOnly).toBe(false);
  });
});

describe("toast", () => {
  it("succès : role=status, disparaît après 4 s", async () => {
    vi.useFakeTimers();
    toast.ok("Tâche enregistrée.");
    const t = document.querySelector(".toast");
    expect(t.dataset.kind).toBe("ok");
    expect(t.getAttribute("role")).toBe("status");
    expect(t.textContent).toContain("Tâche enregistrée.");
    await vi.advanceTimersByTimeAsync(4300);
    expect(document.querySelector(".toast")).toBeNull();
  });

  it("erreur : role=alert, persistante, fermable", async () => {
    vi.useFakeTimers();
    toast.err(new Error("Refusé."));
    const t = document.querySelector(".toast");
    expect(t.getAttribute("role")).toBe("alert");
    expect(t.textContent).toContain("Refusé.");
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector(".toast")).not.toBeNull();
    t.querySelector(".toast__close").click();
    await vi.advanceTimersByTimeAsync(300);
    expect(document.querySelector(".toast")).toBeNull();
  });

  it("action (Annuler) : appelle fn et ferme ; durée par défaut 10 s", async () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    toast.ok("Classée Faite.", { action: { label: "Annuler", fn } });
    await vi.advanceTimersByTimeAsync(5000);
    const btn = document.querySelector(".toast__action");
    expect(btn.textContent).toBe("Annuler");
    btn.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("une action qui lève affiche un toast d'erreur", async () => {
    toast.info("x", { action: { label: "Réessayer", fn: () => { throw new Error("encore raté"); } } });
    document.querySelector(".toast__action").click();
    await new Promise((r) => setTimeout(r, 0));
    const errs = [...document.querySelectorAll('.toast[data-kind="err"]')];
    expect(errs.some((e) => e.textContent.includes("encore raté"))).toBe(true);
  });
});

describe("confirm()", () => {
  it("résout true sur confirmation, false sur annulation et Échap", async () => {
    let p = confirm({ title: "Supprimer ?", confirmLabel: "Supprimer", danger: true });
    let dlg = document.querySelector("dialog.ui-dialog");
    expect(dlg.textContent).toContain("Supprimer ?");
    // danger → le focus initial est sur Annuler (le geste sûr)
    expect(document.activeElement.dataset.role).toBe("cancel");
    dlg.querySelector('[data-role="confirm"]').click();
    expect(await p).toBe(true);
    expect(document.querySelector("dialog.ui-dialog")).toBeNull();

    p = confirm({ title: "Ok ?" });
    document.querySelector('[data-role="cancel"]').click();
    expect(await p).toBe(false);

    p = confirm({ title: "Ok ?" });
    dlg = document.querySelector("dialog.ui-dialog");
    dlg.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(await p).toBe(false);
  });

  it("piège le focus avec Tab", async () => {
    const p = confirm({ title: "Ok ?" });
    const dlg = document.querySelector("dialog.ui-dialog");
    expect(document.activeElement.dataset.role).toBe("confirm");
    dlg.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    expect(document.activeElement.dataset.role).toBe("cancel");
    dlg.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    expect(document.activeElement.dataset.role).toBe("confirm");
    document.querySelector('[data-role="cancel"]').click();
    await p;
  });
});

describe("dirty()", () => {
  it("signale « • modifié », revient propre après markClean", () => {
    const form = h("form", {}, h("textarea", { name: "b" }), h("input", { type: "checkbox" }));
    const flag = h("span", {});
    document.body.append(form, flag);
    const onChange = vi.fn();
    const d = dirty(form, { flag, onChange });
    expect(d.isDirty()).toBe(false);
    const ta = form.querySelector("textarea");
    ta.value = "nouveau";
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    expect(d.isDirty()).toBe(true);
    expect(flag.textContent).toBe("• modifié");
    expect(form.dataset.dirty).toBe("true");
    expect(onChange).toHaveBeenLastCalledWith(true);
    // Revenir à la valeur d'origine = plus modifié
    ta.value = "";
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    expect(d.isDirty()).toBe(false);
    ta.value = "x";
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    d.markClean();
    expect(d.isDirty()).toBe(false);
    expect(flag.textContent).toBe("");
    d.destroy();
  });

  it("guard() : true sans modification, sinon demande confirmation", async () => {
    const ta = h("textarea", {});
    document.body.appendChild(ta);
    const d = dirty(ta);
    expect(await d.guard()).toBe(true);
    ta.value = "x";
    ta.dispatchEvent(new Event("input"));
    const p = d.guard();
    document.querySelector('[data-role="confirm"]').click();
    expect(await p).toBe(true);
    d.destroy();
  });
});

describe("états de zone", () => {
  it("skeleton pose aria-busy et des lignes", () => {
    const el = h("div", {});
    skeleton(el, 4);
    expect(el.getAttribute("aria-busy")).toBe("true");
    expect(el.querySelectorAll(".skeleton__line").length).toBe(4);
  });

  it("empty rend titre, texte et action (occupée pendant fn)", async () => {
    const el = h("div", {});
    let resolve;
    empty(el, { title: "Rien ne t'attend.", text: "…", action: { label: "Créer", fn: () => new Promise((r) => { resolve = r; }) } });
    expect(el.querySelector(".empty__title").textContent).toBe("Rien ne t'attend.");
    const b = el.querySelector("button");
    b.click();
    expect(b.getAttribute("aria-busy")).toBe("true");
    resolve();
  });

  it("failed rend le message et Réessayer appelle retryFn", async () => {
    const el = h("div", {});
    const retry = vi.fn(async () => { el.textContent = "ok"; });
    failed(el, new Error("Serveur injoignable"), retry);
    expect(el.querySelector('[role="alert"]').textContent).toContain("Serveur injoignable");
    el.querySelector("button").click();
    await new Promise((r) => setTimeout(r, 0));
    expect(retry).toHaveBeenCalledTimes(1);
    expect(el.textContent).toBe("ok");
  });

  it("highlight pose puis retire la classe", async () => {
    vi.useFakeTimers();
    const el = h("div", {});
    document.body.appendChild(el);
    el.scrollIntoView = vi.fn();
    highlight(el);
    expect(el.classList.contains("is-highlighted")).toBe(true);
    expect(el.scrollIntoView).toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2100);
    expect(el.classList.contains("is-highlighted")).toBe(false);
  });
});

describe("menu()", () => {
  it("ouvre au clic, navigue aux flèches, exécute et se ferme", async () => {
    const anchor = h("button", {}, "⋯");
    document.body.appendChild(anchor);
    const a = vi.fn();
    const b = vi.fn();
    menu(anchor, [{ label: "Renommer", fn: a }, "sep", { label: "Supprimer", fn: b, danger: true }, { label: "Grisé", fn: vi.fn(), disabled: true }]);
    expect(anchor.parentElement.classList.contains("menu")).toBe(true);
    anchor.click();
    const list = document.querySelector(".menu__list");
    expect(list.getAttribute("role")).toBe("menu");
    expect(anchor.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement.textContent).toBe("Renommer");
    list.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expect(document.activeElement.textContent).toBe("Supprimer");
    document.activeElement.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(b).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".menu__list")).toBeNull();
    expect(anchor.getAttribute("aria-expanded")).toBe("false");
  });

  it("Échap ferme et rend le focus à l'ancre", () => {
    const anchor = h("button", {}, "⋯");
    document.body.appendChild(anchor);
    menu(anchor, () => [{ label: "X", fn: () => {} }]);
    anchor.click();
    document.querySelector(".menu__list").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(document.querySelector(".menu__list")).toBeNull();
    expect(document.activeElement).toBe(anchor);
  });
});

describe("utilitaires", () => {
  it("relTime parle français", () => {
    const now = new Date(2026, 8, 23, 15, 0, 0);
    expect(relTime(new Date(2026, 8, 23, 14, 59, 50), now)).toBe("à l'instant");
    expect(relTime(new Date(2026, 8, 23, 14, 55, 0), now)).toBe("il y a 5 min");
    expect(relTime(new Date(2026, 8, 23, 12, 0, 0), now)).toBe("il y a 3 h");
    expect(relTime(new Date(2026, 8, 22, 9, 5, 0), now)).toBe("hier 09:05");
    expect(relTime(new Date(2026, 8, 12, 9, 5, 0), now)).toBe("12/09 09:05");
    expect(relTime("pas une date", now)).toBe("");
    expect(relTime("", now)).toBe("");
  });

  it("escapeHtml et h()", () => {
    expect(escapeHtml(`<a href="x">'&'</a>`)).toBe("&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
    const click = vi.fn();
    const el = h("button", { class: "btn", dataset: { id: "3" }, onclick: click, hidden: false, "aria-label": "Go" }, "Go", null, [h("span", {}, "!")]);
    expect(el.className).toBe("btn");
    expect(el.dataset.id).toBe("3");
    expect(el.getAttribute("aria-label")).toBe("Go");
    expect(el.hasAttribute("hidden")).toBe(false);
    expect(el.textContent).toBe("Go!");
    el.click();
    expect(click).toHaveBeenCalled();
  });

  it("expose window.ui", () => {
    expect(window.ui && typeof window.ui.api).toBe("function");
  });
});
