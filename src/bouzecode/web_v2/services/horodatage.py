# [desc] Horodatages du store web_v2 et de l'API : UNE forme écrite (UTC, suffixe `+00:00`), deux formes lues (UTC explicite, ou naïve héritée = heure LOCALE). [/desc]
"""Seul point d'entrée des dates persistées ou servies par web_v2 et `remote`.

Écriture : `maintenant_iso()` — UTC, décalage TOUJOURS explicite (`2026-10-06T08:12:34+00:00`).
Lecture : `lire_instant()` — rend un instant UTC conscient, quelle que soit la forme lue :
  - ISO avec décalage ou `Z` : pris tel quel ;
  - ISO NAÏF (sans fuseau) : héritage d'avant l'unification (`datetime.now().isoformat()`),
    donc heure LOCALE de la machine. Le lire comme UTC décalerait de 1 à 2 h — c'est
    exactement ce qui a fait accuser le mauvais process d'une écriture.

Toute comparaison, tout âge, tout tri passe par un instant lu ici : jamais de soustraction
entre un `datetime.now()` naïf et une date du store (TypeError dès qu'une valeur est consciente).
"""
from __future__ import annotations

from datetime import datetime, timezone


def maintenant() -> datetime:
    """L'instant courant, UTC conscient."""
    return datetime.now(timezone.utc)


def maintenant_iso(timespec: str = "seconds") -> str:
    """L'instant courant dans la forme écrite unique : ISO UTC suffixé `+00:00`."""
    return maintenant().isoformat(timespec=timespec)


def en_iso(valeur, timespec: str = "seconds") -> str:
    """Ramène une date quelconque (lisible par `lire_instant`) à la forme écrite ; "" sinon."""
    instant = lire_instant(valeur)
    return instant.isoformat(timespec=timespec) if instant is not None else ""


def lire_instant(valeur) -> datetime | None:
    """Un instant UTC conscient, ou None si la valeur est absente ou illisible.

    Accepte un `datetime` (naïf = local), un epoch en secondes (> 0) ou une chaîne ISO-8601
    (suffixe `Z` ou décalage, séparateur `T` ou espace ; naïve = heure locale)."""
    if isinstance(valeur, datetime):
        instant = valeur
    elif isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        return datetime.fromtimestamp(valeur, tz=timezone.utc) if valeur > 0 else None
    else:
        texte = str(valeur or "").strip()
        if not texte:
            return None
        if texte.endswith(("Z", "z")):
            texte = texte[:-1] + "+00:00"
        try:
            instant = datetime.fromisoformat(texte)
        except ValueError:
            return None
    if instant.tzinfo is None:
        instant = instant.astimezone()  # naïf = heure locale de la machine
    return instant.astimezone(timezone.utc)


def age_s(valeur, reference=None) -> float | None:
    """Secondes écoulées depuis `valeur` jusqu'à `reference` (défaut : maintenant). None si illisible."""
    instant = lire_instant(valeur)
    if instant is None:
        return None
    fin = lire_instant(reference) if reference is not None else maintenant()
    return (fin - instant).total_seconds()


def cle_chrono(valeur) -> float:
    """Clé de tri chronologique (epoch) ; une date illisible ou absente trie en PREMIER (0.0).

    Trier les chaînes brutes mélange les formes : `10:00` local et `08:30+00:00` ne se
    comparent pas lexicalement."""
    instant = lire_instant(valeur)
    return instant.timestamp() if instant is not None else 0.0


def heure_locale(valeur, format_: str) -> str:
    """Affichage humain dans l'heure LOCALE de la machine ; "" si la date est illisible."""
    instant = lire_instant(valeur)
    return instant.astimezone().strftime(format_) if instant is not None else ""
