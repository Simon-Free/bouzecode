import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

// GARDE (SPEC §7) : hors de static/js/lib/, aucun code ne doit
//   - appeler fetch( directement            → passer par lib/ui.js::api (erreurs lisibles, R4)
//   - utiliser alert( / confirm( natifs     → ui.toast / ui.confirm (R4, R6)
//   - avaler une erreur dans un catch vide  → dire l'erreur (R4)
// Elle couvre tout static/js : les trois pages sont migrées, il n'y a plus d'exception.

const ROOT = path.resolve(__dirname, "../../static/js");

function walk(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else if (e.name.endsWith(".js")) out.push(p);
  }
  return out;
}

// Retire commentaires et chaînes pour ne pas déclencher sur « fetch( » cité dans un commentaire.
function stripCommentsAndStrings(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:\\])\/\/.*$/gm, "$1")
    .replace(/`(?:\\[\s\S]|[^`\\])*`/g, "``")
    .replace(/"(?:\\.|[^"\\\n])*"/g, '""')
    .replace(/'(?:\\.|[^'\\\n])*'/g, "''");
}

const RULES = [
  { name: "fetch( brut (utiliser ui.api)", re: /(^|[^.\w])fetch\s*\(|window\.fetch\s*\(/ },
  { name: "alert( natif (utiliser ui.toast)", re: /(^|[^.\w])alert\s*\(|window\.alert\s*\(/ },
  { name: "confirm( natif (utiliser ui.confirm)", re: /(^|[^.\w])confirm\s*\(|window\.confirm\s*\(/ },
  { name: "catch vide (dire l'erreur)", re: /catch\s*(\(\s*[\w$]*\s*\))?\s*\{\s*\}/ },
];

export function violations(src) {
  const code = stripCommentsAndStrings(src);
  return RULES.filter((r) => r.re.test(code)).map((r) => r.name);
}

const files = walk(ROOT)
  .map((abs) => path.relative(ROOT, abs).split(path.sep).join("/"))
  .filter((rel) => !rel.startsWith("lib/"));

describe("garde : pas de fetch/alert/confirm bruts ni de catch vide hors lib/", () => {
  it("la garde détecte bien ce qu'elle interdit", () => {
    expect(violations("const r = await fetch('/api/x');")).toContain("fetch( brut (utiliser ui.api)");
    expect(violations("window.alert('x')")).toContain("alert( natif (utiliser ui.toast)");
    expect(violations("if (confirm('sûr ?')) go();")).toContain("confirm( natif (utiliser ui.confirm)");
    expect(violations("try { x() } catch (_) {}")).toContain("catch vide (dire l'erreur)");
    expect(violations("await ui.confirm({}); ui.api('GET', u); // fetch( en commentaire")).toEqual([]);
    expect(violations("try { x() } catch (e) { toast.err(e) }")).toEqual([]);
  });

  for (const rel of files) {
    it(`${rel}`, () => {
      const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
      expect(violations(src), `${rel} viole la garde`).toEqual([]);
    });
  }

});
