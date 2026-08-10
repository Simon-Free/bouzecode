import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Test DÉTERMINISTE (sans navigateur) des critères CSS de la barre "nouvelle
// conversation" refondue. On lit le template conversations.html, on extrait le
// bloc <style> et on vérifie les règles clés :
//   - .conv-new-bar est en flex-direction:row (bouton à côté du textarea, pas dessous)
//   - le fond du textarea (#conv-new-input) diffère du fond de page (--pui-bg #08080b)
//   - le ratio de luminance zone/fond >= 1.3 (zone plus claire que le fond)
//   - aucune règle .conv-new-tab-btn ne subsiste (bouton "+" supprimé)
// Les critères de LAYOUT en pixels (y bouton < bas textarea, largeur >=95%) sont
// couverts par la capture Chrome DevTools sur la page live (pas de layout en jsdom).

const __dirname = dirname(fileURLToPath(import.meta.url));
const TEMPLATE = resolve(__dirname, "../../templates/conversations.html");
const PAGE_BG = "#08080b"; // var(--pui-bg) : fond de page mesuré (rgb 8,8,11)

function styleBlock() {
  const html = readFileSync(TEMPLATE, "utf8");
  const m = html.match(/<style[^>]*>([\s\S]*?)<\/style>/i);
  expect(m).not.toBeNull();
  return m[1];
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
    // background peut être un simple hex ; on isole le token couleur.
    const hex = (bg.match(/#[0-9a-f]{6}/i) || [])[0];
    expect(hex).toBeTruthy();
    expect(hex.toLowerCase()).not.toBe(PAGE_BG);
    expect(relLuminance(hex)).toBeGreaterThan(relLuminance(PAGE_BG));
    expect(contrastRatio(hex, PAGE_BG)).toBeGreaterThanOrEqual(1.3);
  });

  it("aucune règle .conv-new-tab-btn ne subsiste (bouton + supprimé)", () => {
    expect(styleBlock()).not.toMatch(/\.conv-new-tab-btn/);
  });
});
