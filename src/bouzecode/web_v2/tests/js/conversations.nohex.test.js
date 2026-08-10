import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Garde-fou : aucune couleur hex EN DUR (nue) ne doit apparaître dans le template
// conversations.html ni dans le JS de la page. Tout passe par les variables CSS.
// Toléré : les fallbacks légitimes `var(--x, #hex)` (deuxième argument d'un var()).
// Non toléré : un `#rrggbb` / `#rgb` posé directement comme valeur de propriété.

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");

// Le JS de la page vit dans conversations.js (point d'entrée) ET dans les modules de
// static/js/conversations/. Le dossier est parcouru plutôt qu'énuméré : un module ajouté
// demain est couvert sans qu'on ait à y penser — sinon la garde s'érode en silence.
function jsModulesUnder(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) return jsModulesUnder(full);
    return entry.name.endsWith(".js") ? [full] : [];
  });
}

const TARGETS = [
  resolve(ROOT, "templates/conversations.html"),
  resolve(ROOT, "static/js/conversations.js"),
  ...jsModulesUnder(resolve(ROOT, "static/js/conversations")),
];

// Retire les fallbacks var(--x, #hex) AVANT de chercher un hex nu, pour ne pas
// pénaliser un fallback légitime tout en attrapant tout autre #hex posé en dur.
function stripVarFallbacks(text) {
  return text.replace(/var\(\s*--[\w-]+\s*,\s*#[0-9a-fA-F]{3,8}\s*\)/g, "var(--_)");
}

const HEX_RE = /#[0-9a-fA-F]{3,8}\b/g;

describe("conversations — zéro couleur hex en dur (hors fallback var())", () => {
  for (const file of TARGETS) {
    it(`${file.split(/[\\/]/).pop()} n'a aucun hex nu`, () => {
      const raw = readFileSync(file, "utf8");
      const cleaned = stripVarFallbacks(raw);
      const matches = cleaned.match(HEX_RE) || [];
      expect(matches).toEqual([]);
    });
  }
});
