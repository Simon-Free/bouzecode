import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Test DÉTERMINISTE (sans navigateur) des critères CSS de la barre "nouvelle
// conversation" refondue. On lit le template conversations.html, on extrait le
// bloc <style> et on vérifie les règles clés :
//   - .conv-new-bar est en flex-direction:row (bouton à côté du textarea, pas dessous)
//   - le fond du textarea (#conv-new-input) diffère du fond de page (token --bg)
//   - le ratio de luminance zone/fond >= 1.3 (zone plus claire que le fond)
//   - aucune règle .conv-new-tab-btn ne subsiste (bouton "+" supprimé)
// Les critères de LAYOUT en pixels (y bouton < bas textarea, largeur >=95%) sont
// couverts par la capture Chrome DevTools sur la page live (pas de layout en jsdom).

const __dirname = dirname(fileURLToPath(import.meta.url));
const TEMPLATE = resolve(__dirname, "../../templates/conversations.html");
const APP_CSS = resolve(__dirname, "../../static/app.css");

function styleBlock() {
  const html = readFileSync(TEMPLATE, "utf8");
  const m = html.match(/<style[^>]*>([\s\S]*?)<\/style>/i);
  expect(m).not.toBeNull();
  return m[1];
}

// Les règles du gabarit ne portent AUCUN hex : `conversations.nohex.test.js` l'interdit, tout
// passe par les tokens du thème. Un critère de couleur se vérifie donc en deux temps —
// la règle nomme un token, `:root` (app.css) lui donne sa valeur. Même lecture que
// `conversations.ui3-bubble.test.js`.
function tokenValue(name) {
  const css = readFileSync(APP_CSS, "utf8");
  const m = css.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
  expect(m, `token ${name} introuvable dans :root`).not.toBeNull();
  return m[1];
}

// Résout `var(--panel2)` (ou un hex écrit en dur) vers un #rrggbb.
function colorOf(declaration) {
  const variable = declaration.match(/var\(\s*(--[\w-]+)/);
  if (variable) return tokenValue(variable[1]);
  return (declaration.match(/#[0-9a-f]{6}/i) || [])[0];
}

// Extrait le corps `{ ... }` de la PREMIÈRE règle dont le sélecteur contient `sel`.
function ruleBody(css, sel) {
  const idx = css.indexOf(sel);
  if (idx === -1) return null;
  const open = css.indexOf("{", idx);
  const close = css.indexOf("}", open);
  if (open === -1 || close === -1) return null;
  return css.slice(open + 1, close);
}

function declValue(body, prop) {
  const re = new RegExp(`(?:^|[;{\\s])${prop}\\s*:\\s*([^;]+)`, "i");
  const m = body.match(re);
  return m ? m[1].trim() : null;
}

// Luminance relative WCAG à partir d'un hex #rrggbb.
function relLuminance(hex) {
  const h = hex.replace("#", "");
  const rgb = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = rgb.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function contrastRatio(a, b) {
  const la = relLuminance(a);
  const lb = relLuminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

describe("conversations.html — CSS barre nouvelle conversation refondue", () => {
  it(".conv-new-bar est en flex row (bouton à côté du textarea, pas dessous)", () => {
    const body = ruleBody(styleBlock(), ".conv-new-bar {");
    expect(body).not.toBeNull();
    expect(declValue(body, "display")).toBe("flex");
    expect(declValue(body, "flex-direction")).toBe("row");
  });

  it("le textarea prend toute la largeur (flex:1) et la barre width:100%", () => {
    const css = styleBlock();
    const bar = ruleBody(css, ".conv-new-bar {");
    expect(declValue(bar, "width")).toBe("100%");
    const input = ruleBody(css, ".conv-new-input {");
    expect(declValue(input, "flex")).toBe("1");
  });

  it("le fond du textarea diffère du fond de page et est plus clair (ratio >= 1.3)", () => {
    const input = ruleBody(styleBlock(), ".conv-new-input {");
    const bg = declValue(input, "background");
    expect(bg).not.toBeNull();
    const hex = colorOf(bg);
    expect(hex).toBeTruthy();
    const pageBg = tokenValue("--bg"); // fond de page, lu au même endroit que le reste
    expect(hex.toLowerCase()).not.toBe(pageBg.toLowerCase());
    expect(relLuminance(hex)).toBeGreaterThan(relLuminance(pageBg));
    expect(contrastRatio(hex, pageBg)).toBeGreaterThanOrEqual(1.3);
  });

  it("aucune règle .conv-new-tab-btn ne subsiste (bouton + supprimé)", () => {
    expect(styleBlock()).not.toMatch(/\.conv-new-tab-btn/);
  });
});
