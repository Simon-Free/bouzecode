import { describe, expect, it } from "vitest";
import {
  formatEventTime,
  formatEventTimeTooltip,
  parseInstant,
} from "../../static/js/time_format.js";
import { relTime } from "../../static/js/lib/ui.js";
import { dateCourte } from "../../static/js/bureau/classement.js";

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

  it("hier → 'hier HH:MM'", () => {
    expect(formatEventTime(localIso(2026, 6, 6, 23, 41), now)).toBe("hier 23:41");
    expect(formatEventTime(localIso(2026, 6, 6, 0, 0), now)).toBe("hier 00:00");
  });

  it("autre jour → 'JJ/MM HH:MM'", () => {
    expect(formatEventTime(localIso(2026, 6, 5, 9, 3), now)).toBe("05/07 09:03");
    expect(formatEventTime(localIso(2026, 0, 2, 18, 7), now)).toBe("02/01 18:07");
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

// Les deux formes que sert le serveur (services/horodatage.py) : UTC explicite (forme
// écrite) et l'héritage du store, ISO NAÏF en heure LOCALE. Le même instant doit
// s'afficher pareil sous toutes ses formes.
function formesDuMemeInstant(local) {
  const p = (n, w = 2) => String(n).padStart(w, "0");
  const naif = `${local.getFullYear()}-${p(local.getMonth() + 1)}-${p(local.getDate())}`
    + `T${p(local.getHours())}:${p(local.getMinutes())}:${p(local.getSeconds())}`;
  const utc = local.toISOString(); // "…Z", millisecondes
  return [
    naif,                                         // héritage : local naïf
    naif.replace("T", " "),                       // `saved_at` du harnais
    `${naif}.123456`,                             // local naïf à la microseconde
    utc,                                          // ancien runner
    utc.replace(".000Z", "+00:00"),               // forme écrite désormais
    utc.replace(".000Z", ".000000+00:00"),        // forme écrite, microsecondes
    utc.replace(".000Z", "+0000"),                // décalage sans deux-points
  ];
}

describe("parseInstant", () => {
  const local = new Date(2026, 9, 5, 14, 2, 11); // 5 oct. 2026 14:02:11 local

  it("lit le même instant sous toutes les formes servies", () => {
    for (const forme of formesDuMemeInstant(local)) {
      const d = parseInstant(forme);
      expect(d, forme).not.toBeNull();
      expect(Math.abs(d.getTime() - local.getTime()), forme).toBeLessThan(1000);
    }
  });

  it("une forme naïve est une heure LOCALE, pas de l'UTC", () => {
    expect(parseInstant("2026-10-05T14:02:11").getHours()).toBe(14);
    expect(parseInstant("2026-10-05 14:02:11").getHours()).toBe(14);
  });

  it("vide / illisible → null ; une Date passe telle quelle", () => {
    expect(parseInstant("")).toBeNull();
    expect(parseInstant(null)).toBeNull();
    expect(parseInstant("pas-une-date")).toBeNull();
    expect(parseInstant(local)).toBe(local);
  });
});

describe("formatEventTime sur les deux formes du serveur", () => {
  it("même rendu en heure locale, forme héritée ou UTC", () => {
    const now = new Date(2026, 9, 5, 18, 0);
    const rendus = formesDuMemeInstant(new Date(2026, 9, 5, 14, 2, 11))
      .map((forme) => formatEventTime(forme, now));
    expect(new Set(rendus)).toEqual(new Set(["14:02"]));
  });

  it("relTime et dateCourte lisent aussi les deux formes", () => {
    const now = new Date(2026, 9, 5, 18, 0);
    for (const forme of formesDuMemeInstant(new Date(2026, 9, 5, 17, 30))) {
      expect(relTime(forme, now), forme).toBe("il y a 30 min");
    }
    for (const forme of formesDuMemeInstant(new Date(2026, 8, 25, 3, 12))) {
      expect(dateCourte(forme), forme).toBe("25/09 03:12");
    }
  });
});
