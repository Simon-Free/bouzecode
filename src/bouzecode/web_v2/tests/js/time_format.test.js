import { describe, expect, it } from "vitest";
import {
  formatEventTime,
  formatEventTimeTooltip,
} from "../../static/js/time_format.js";
import { setLang } from "../../static/js/i18n/index.js";

// On raisonne en heure LOCALE du runner. Pour rendre le test déterministe quel
// que soit le fuseau CI, on construit les instants de référence via `new Date(y,
// mo, d, h, mi)` (constructeur LOCAL) et on passe un `now` explicite. Le helper
// convertit l'ISO en local ; en construisant l'ISO à partir d'un Date local on
// obtient l'aller-retour attendu.
function localIso(y, mo, d, h, mi) {
  return new Date(y, mo, d, h, mi).toISOString();
}

describe("formatEventTime", () => {
  const now = new Date(2026, 6, 7, 14, 30); // 7 juil. 2026 14:30 local

  it("aujourd'hui → HH:MM", () => {
    expect(formatEventTime(localIso(2026, 6, 7, 23, 41), now)).toBe("23:41");
    expect(formatEventTime(localIso(2026, 6, 7, 1, 5), now)).toBe("01:05");
  });

  it("hier → 'yesterday HH:MM' dans la langue par défaut", () => {
    expect(formatEventTime(localIso(2026, 6, 6, 23, 41), now)).toBe("yesterday 23:41");
    expect(formatEventTime(localIso(2026, 6, 6, 0, 0), now)).toBe("yesterday 00:00");
  });

  it("autre jour → 'MM/JJ HH:MM' : l'ordre suit la langue, pas le serveur", () => {
    expect(formatEventTime(localIso(2026, 6, 5, 9, 3), now)).toBe("07/05 09:03");
    expect(formatEventTime(localIso(2026, 0, 2, 18, 7), now)).toBe("01/02 18:07");
  });

  it("en français, le mot ET l'ordre jour-mois redeviennent ceux d'avant", () => {
    setLang("fr");
    expect(formatEventTime(localIso(2026, 6, 6, 23, 41), now)).toBe("hier 23:41");
    expect(formatEventTime(localIso(2026, 6, 5, 9, 3), now)).toBe("05/07 09:03");
    setLang("en");
  });

  it("iso vide/invalide → chaîne vide", () => {
    expect(formatEventTime("", now)).toBe("");
    expect(formatEventTime(null, now)).toBe("");
    expect(formatEventTime("pas-une-date", now)).toBe("");
  });

  it("même événement, même heure quel que soit le point d'affichage (déterminisme)", () => {
    // Le CRITÈRE du ticket : un unique instant → un unique rendu. On formate le
    // même ISO deux fois (comme sidebar puis marqueur inline) → identique.
    const iso = localIso(2026, 6, 7, 23, 41);
    expect(formatEventTime(iso, now)).toBe(formatEventTime(iso, now));
  });
});

describe("formatEventTimeTooltip", () => {
  it("rend un instant complet non vide pour un ISO valide", () => {
    const t = formatEventTimeTooltip("2026-07-06T23:41:00Z");
    expect(t).toBeTruthy();
    expect(t).not.toBe("");
  });

  it("iso vide → chaîne vide", () => {
    expect(formatEventTimeTooltip("")).toBe("");
  });
});
