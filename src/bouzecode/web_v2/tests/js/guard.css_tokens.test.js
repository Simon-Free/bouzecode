import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

// GARDE (SPEC §3, design system) : une seule source de couleurs, les tokens de static/ds.css.
// Aucune autre feuille de style ni aucun gabarit ne pose de couleur littérale (#hex, rgb(),
// rgba()) : sinon le thème clair et le contraste AA se cassent en silence.

const STATIC = path.resolve(__dirname, "../../static");
const TEMPLATES = path.resolve(__dirname, "../../templates");
const COULEUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(/g;

function feuilles(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory() && e.name !== "vendor") out.push(...feuilles(p));
    else if (e.name.endsWith(".css") && e.name !== "ds.css") out.push(p);
  }
  return out;
}

export function couleursLitterales(css) {
  return (css.replace(/\/\*[\s\S]*?\*\//g, "").match(COULEUR) || []);
}

function stylesDesGabarits(html) {
  const blocs = [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]);
  const attributs = [...html.matchAll(/style="([^"]*)"/g)].map((m) => m[1]);
  return blocs.concat(attributs).join("\n");
}

describe("garde : aucune couleur littérale hors des tokens de ds.css", () => {
  it("la garde détecte bien ce qu'elle interdit", () => {
    expect(couleursLitterales(".a { color: #fff; background: rgba(0,0,0,.2) }")).toHaveLength(2);
    expect(couleursLitterales("/* ancien #2b3a55 */ .a { color: var(--text) }")).toEqual([]);
  });

  for (const abs of feuilles(STATIC)) {
    const rel = path.relative(STATIC, abs).split(path.sep).join("/");
    it(`static/${rel}`, () => {
      expect(couleursLitterales(fs.readFileSync(abs, "utf8")), `static/${rel}`).toEqual([]);
    });
  }

  for (const nom of fs.readdirSync(TEMPLATES).filter((n) => n.endsWith(".html"))) {
    it(`templates/${nom}`, () => {
      const html = fs.readFileSync(path.join(TEMPLATES, nom), "utf8");
      expect(couleursLitterales(stylesDesGabarits(html)), `templates/${nom}`).toEqual([]);
    });
  }
});
