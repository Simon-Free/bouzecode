import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// UI-3 : fond de bulle assistant lisible sur /conversations.
// Constat : `.conv-messages .block.assistant` avait `background:none`
// (rgba(0,0,0,0)) sur un fond de page --bg #08080b → texte flottant,
// aucune séparation entre deux messages assistant consécutifs.
// Spec : bulle assistant = fond dédié #26263a (rgb(38,38,58)), bordure 1px
// subtile, coins arrondis cohérents avec la bulle user ; distinct du user
// #2a2a3a (rgb(42,42,58)) ; ratio luminance bulle/fond >= 1.3.

const __dirname = dirname(fileURLToPath(import.meta.url));
const CSS_PATH = resolve(__dirname, "../../static/app.css");
const css = readFileSync(CSS_PATH, "utf8");

// Extrait le corps d'une règle CSS par son sélecteur exact.
function ruleBody(selector) {
  const idx = css.indexOf(selector);
  expect(idx, `règle ${selector} introuvable`).toBeGreaterThanOrEqual(0);
  const open = css.indexOf("{", idx);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
}

// Normalise un hex #rrggbb -> "rgb(r, g, b)".
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return { r, g, b, css: `rgb(${r}, ${g}, ${b})` };
}

// Luminance relative WCAG.
function hexToLum(hex) {
  const { r, g, b } = hexToRgb(hex);
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

// Contrast ratio WCAG : (Lmax + 0.05) / (Lmin + 0.05).
function contrastRatio(a, b) {
  const la = hexToLum(a);
  const lb = hexToLum(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

// Résout une variable CSS --name définie en :root vers son hex #rrggbb.
// Les fonds de bulles ne sont plus en dur dans la règle : ils pointent sur
// var(--bubble-*) ; la valeur réelle vit dans :root (objectif zéro-hex dans
// les règles de layout). On lit donc la définition de la variable.
function resolveVar(name) {
  const m = css.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
  expect(m, `variable ${name} introuvable dans :root`).not.toBeNull();
  return m[1];
}

const ASSISTANT = resolveVar("--bubble-assistant"); // rgb(38, 38, 58)
const USER = resolveVar("--bubble-user"); // rgb(42, 42, 58)
const PAGE = "#08080b"; // rgb(8, 8, 11)
const TEXT = "#f4f4f6"; // rgb(244, 244, 246)

describe("UI-3 : fond bulle assistant /conversations", () => {
  const assistant = ruleBody(".conv-messages .block.assistant");
  const user = ruleBody(".conv-messages .block.user");

  it("bulle assistant a un fond non transparent via var(--bubble-assistant) = rgb(38, 38, 58)", () => {
    // Objectif zéro-hex dans les règles : le fond pointe sur la variable dédiée.
    expect(assistant).toMatch(/background:\s*var\(--bubble-assistant\)/i);
    // Le fond ne doit PLUS être transparent.
    expect(assistant).not.toMatch(/background:\s*none/i);
    expect(hexToRgb(ASSISTANT).css).toBe("rgb(38, 38, 58)");
    expect(hexToRgb(ASSISTANT).css).not.toBe("rgba(0, 0, 0, 0)");
  });

  it("bulle assistant a une bordure 1px subtile et des coins arrondis", () => {
    expect(assistant).toMatch(/border:\s*1px solid/i);
    expect(assistant).toMatch(/border-radius:/i);
    // Ne conserve plus border:none.
    expect(assistant).not.toMatch(/border:\s*none/i);
  });

  it("assistant rgb(38, 38, 58) est distinct du user rgb(42, 42, 58)", () => {
    // La règle user pointe sur var(--bubble-user) (valeur #2a2a3a en :root).
    expect(user).toMatch(/background:\s*var\(--bubble-user\)/i);
    expect(hexToRgb(USER).css).toBe("rgb(42, 42, 58)");
    // Les deux fonds sont littéralement différents.
    expect(hexToRgb(ASSISTANT).css).not.toBe(hexToRgb(USER).css);
  });

  it("ratio de luminance bulle/fond >= 1.3 et texte/bulle >= 4.5 (lisibilité)", () => {
    // Critère spec : bulle assistant nettement plus claire que la page.
    expect(contrastRatio(ASSISTANT, PAGE)).toBeGreaterThanOrEqual(1.3);
    // Blocs internes (réflexion, tool panels) lisibles : texte sur bulle.
    expect(contrastRatio(TEXT, ASSISTANT)).toBeGreaterThanOrEqual(4.5);
  });
});
