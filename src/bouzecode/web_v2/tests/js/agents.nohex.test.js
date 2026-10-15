import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Garde : la page Agents n'a AUCUNE couleur en dur. Tout passe par les tokens de ds.css
// (thème clair/sombre, contraste AA). Parcourt le dossier : un module ajouté est couvert d'office.
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

function files(dir, ext) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = resolve(dir, e.name);
    if (e.isDirectory()) return files(full, ext);
    return e.name.endsWith(ext) ? [full] : [];
  });
}

const HEX = /#[0-9a-fA-F]{3,8}\b/g;

describe("page Agents : aucune couleur en dur", () => {
  const targets = [
    resolve(ROOT, "static/css/agents.css"),
    resolve(ROOT, "templates/conversations.html"),
    resolve(ROOT, "static/js/conversations.js"),
    resolve(ROOT, "static/js/projects_admin.js"),
    ...files(resolve(ROOT, "static/js/conversations"), ".js"),
  ];
  for (const f of targets) {
    it(f.replace(ROOT, ""), () => {
      const src = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
      const hits = (src.match(HEX) || []).filter((h) => !/^#[0-9]+$/.test(h) || h.length > 4);
      expect(hits, "utilise un token de ds.css").toEqual([]);
    });
  }
});
