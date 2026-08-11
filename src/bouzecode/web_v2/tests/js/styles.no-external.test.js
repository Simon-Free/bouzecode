import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, relative, resolve } from "node:path";

// Garde-fou : les feuilles de style de BouzéqUI ne référencent AUCUNE ressource externe.
//
// app.css importait une webfont Google Fonts. Cela contredisait le parti pris du projet
// (Monaco est vendorisé précisément « aucun CDN », cf. SPEC.md) et, derrière un proxy
// restrictif, la requête part dans le vide : le navigateur attend, le premier rendu
// traîne, et la police annoncée n'arrive jamais. Les piles système la remplacent — elles
// ne coûtent aucune requête et rendent sur Windows, macOS et Linux.
//
// La garde balaie le dossier plutôt que d'énumérer les fichiers : une feuille ajoutée
// demain est couverte sans qu'on y pense, sinon la règle s'érode en silence.

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = resolve(__dirname, "../../static");
// Monaco est une copie figée d'un paquet tiers, déjà servie depuis le disque : on ne la
// réécrit pas. Ce sont NOS feuilles que cette garde surveille.
const VENDOR_DIR = resolve(STATIC_DIR, "vendor");

function stylesheetsUnder(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(dir, entry.name);
    if (full === VENDOR_DIR) return [];
    if (entry.isDirectory()) return stylesheetsUnder(full);
    return entry.name.endsWith(".css") ? [full] : [];
  });
}

// Toute origine distante, quelle que soit sa forme : `https://…`, `http://…`, et le
// protocol-relative `//host.tld/…` qu'un copier-coller de CDN laisse traîner.
const REMOTE_ORIGIN = /(?:https?:)?\/\/[a-z0-9-]+(?:\.[a-z0-9-]+)+/gi;
// Un @import, même local, sérialise le chargement : la feuille suivante n'est découverte
// qu'une fois la première parsée. Le projet n'en a aucun besoin.
const IMPORT_RULE = /@import\b[^;]*/g;

// Ce qui compte est ce que le NAVIGATEUR va chercher : un commentaire qui cite une URL
// ou explique pourquoi il n'y a plus de @import ne déclenche aucune requête.
function withoutComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, " ");
}

const STYLESHEETS = stylesheetsUnder(STATIC_DIR);

describe("feuilles de style — aucune ressource externe", () => {
  it("le dossier static contient bien des feuilles à surveiller", () => {
    expect(STYLESHEETS.length).toBeGreaterThan(0);
  });

  for (const file of STYLESHEETS) {
    const name = relative(STATIC_DIR, file).replace(/\\/g, "/");
    const rules = withoutComments(readFileSync(file, "utf8"));

    it(`${name} ne référence aucune origine distante`, () => {
      expect(rules.match(REMOTE_ORIGIN) || []).toEqual([]);
    });

    it(`${name} n'@importe aucune autre feuille`, () => {
      expect(rules.match(IMPORT_RULE) || []).toEqual([]);
    });
  }
});
