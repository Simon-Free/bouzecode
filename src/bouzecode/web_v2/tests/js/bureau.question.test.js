import { describe, it, expect, vi, beforeEach } from "vitest";

// Bloc « question d'agent » du Bureau (static/js/bureau/question.js) — SPEC R1, R3, R4, R5 :
// verrouillage au premier clic, écho « Réponse envoyée », erreur inline qui déverrouille et
// garde le texte, une option n'écrase jamais le brouillon libre.

import { blocQuestion } from "../../static/js/bureau/question.js";

const Q = { texte: "Quelle base ?", options: [{ label: "PostgreSQL", description: "prod" }, { label: "SQLite" }],
  allow_freetext: true };

function monter(q, repondre) {
  document.body.innerHTML = "";
  const el = blocQuestion(q, repondre);
  document.body.appendChild(el);
  return el;
}

function differe() {
  let resoudre;
  let rejeter;
  const p = new Promise((res, rej) => { resoudre = res; rejeter = rej; });
  return { p, resoudre, rejeter };
}

beforeEach(() => { document.body.innerHTML = ""; });

describe("blocQuestion", () => {
  it("affiche la question, les options (avec leur description en infobulle) et un champ libre", () => {
    const el = monter(Q, vi.fn());
    expect(el.querySelector(".bz-q__texte").textContent).toBe("Quelle base ?");
    const opts = [...el.querySelectorAll(".bz-q__opt")];
    expect(opts.map((b) => b.textContent)).toEqual(["PostgreSQL", "SQLite"]);
    expect(opts[0].title).toBe("prod");
    expect(el.querySelector(".bz-q__libre")).not.toBeNull();
  });

  it("verrouille tout le bloc dès le premier clic, puis confirme la réponse envoyée", async () => {
    const d = differe();
    const repondre = vi.fn(() => d.p);
    const el = monter(Q, repondre);
    const [pg, lite] = el.querySelectorAll(".bz-q__opt");
    pg.click();
    expect(repondre).toHaveBeenCalledWith("PostgreSQL");
    expect(pg.getAttribute("aria-busy")).toBe("true");
    expect(lite.disabled).toBe(true);
    expect(el.querySelector(".bz-q__libre").readOnly).toBe(true);
    lite.click();
    expect(repondre).toHaveBeenCalledTimes(1);
    d.resoudre({ ok: true });
    await vi.waitFor(() => expect(el.dataset.done).toBe("true"));
    expect(el.textContent).toContain("Réponse envoyée");
    expect(el.textContent).toContain("« PostgreSQL »");
  });

  it("une option n'écrase pas le brouillon libre ; un échec déverrouille et garde le texte", async () => {
    const repondre = vi.fn(() => Promise.reject(new Error("Serveur injoignable")));
    const el = monter(Q, repondre);
    const libre = el.querySelector(".bz-q__libre");
    libre.value = "ma réponse à moi";
    el.querySelector(".bz-q__opt").click();
    await vi.waitFor(() => expect(el.querySelector(".bz-q__erreur").textContent).toContain("Réponse non transmise"));
    expect(libre.value).toBe("ma réponse à moi");
    expect(libre.readOnly).toBe(false);
    expect([...el.querySelectorAll("button")].every((b) => !b.disabled)).toBe(true);
    expect(el.dataset.locked).toBe("false");
  });

  it("Entrée dans le champ libre envoie le texte ; vide = rien", () => {
    const repondre = vi.fn(() => new Promise(() => {}));
    const el = monter(Q, repondre);
    const libre = el.querySelector(".bz-q__libre");
    libre.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(repondre).not.toHaveBeenCalled();
    libre.value = "  SQLite en local  ";
    libre.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(repondre).toHaveBeenCalledWith("SQLite en local");
  });

  it("sans réponse libre autorisée, seules les options sont proposées", () => {
    const el = monter({ ...Q, allow_freetext: false }, vi.fn());
    expect(el.querySelector(".bz-q__libre")).toBeNull();
  });

});
