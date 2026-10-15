# [desc] Titre court et lisible d'un ticket / agent, tiré de ce qu'on lui DEMANDE (objectif du brief, texte enveloppé par un gabarit) et non de la 1re ligne de contexte d'un prompt. Pur. [/desc]
"""« Tu travailles dans le dépôt git… », « Dans le chantier « X », crée et lance une tâche dont le
brief est exactement le texte suivant : » : la 1re ligne d'un prompt dit souvent OÙ travailler ou
COMMENT transmettre la demande, jamais la demande. Relevé sur l'essai du 2026-09-24/25 : 9 agents
sur 17 portaient un tel titre dans la liste des agents.

`titre_lisible(prompt)`, dans l'ordre :

1. un GABARIT qui enveloppe une demande (« … dont le brief est … : », « … le texte suivant : »)
   → le titre de la demande enveloppée ;
2. une 1re ligne qui n'est ni du contexte ni une étiquette → elle, telle quelle (une tâche du
   Bureau commence par son titre, une demande humaine par sa phrase) ;
3. sinon la ligne qui ANNONCE l'objectif (« OBJECTIF : … », « MISSION — … », « ## Ta mission :
   … », « # Objectif (…) » suivi de la ligne d'après) ;
4. sinon la 1re ligne qui n'est pas du contexte.

Puis : markdown retiré, 1re phrase, coupé au mot sous `TITRE_MAX`. Le brief complet n'est jamais
modifié (il reste dans `prompt` / `title_full`).
"""
from __future__ import annotations

import re

TITRE_MAX = 80

_GABARIT = re.compile(r"(dont le brief est|le texte suivant|la demande suivante)[^\n]*:\s*$", re.I)
_CONTEXTE = re.compile(r"^(tu (travailles|es|te trouves|interviens) (dans|sur)\b|chantier\s*:"
                       r"|contexte\b|d[ée]p[ôo]t\s*/|p[ée]rim[èe]tre\b)", re.I)
_ETIQUETTE = re.compile(r"^(?:(?:ta|ton|votre|ma|la|le)\s+)?(objectif|mission|but|livrable)s?\b\s*(?P<suite>.*)$",
                        re.I)
_TITRE_MD = re.compile(r"^#{1,6}\s*")
_PUCE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)")
_PARENTHESES = re.compile(r"\([^)]*\)")


def _nu(ligne: str) -> str:
    """Ligne sans markdown de tête (titre, puce, gras) ni espaces superflus."""
    ligne = _PUCE.sub("", _TITRE_MD.sub("", ligne.strip()))
    return " ".join(ligne.replace("**", "").replace("__", "").split())


def _contexte(ligne: str) -> bool:
    return bool(_CONTEXTE.match(_nu(ligne)))


def _suite_d_etiquette(ligne: str) -> str | None:
    """`None` si la ligne n'annonce pas l'objectif ; sinon ce qui suit l'étiquette (`""` si rien
    de substantiel : « ## OBJECTIF (vérifiable) » annonce la ligne suivante)."""
    trouve = _ETIQUETTE.match(_nu(ligne))
    if not trouve:
        return None
    suite = trouve.group("suite").lstrip(" :—–-").strip()
    return suite if len(_PARENTHESES.sub("", suite).split()) >= 2 else ""


def _premiere_phrase(texte: str) -> str:
    coupe = re.search(r"[.!?](?=\s+[A-ZÀ-ÖØ-Þ«\"])", texte)
    phrase = texte[:coupe.start()] if coupe else texte
    return phrase.rstrip(" .;:")


def _court(texte: str) -> str:
    texte = _premiere_phrase(texte)
    if len(texte) <= TITRE_MAX:
        return texte
    coupe = texte[:TITRE_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    return coupe + "…"


def _par_etiquette(lignes: list[str]) -> str:
    for i, ligne in enumerate(lignes):
        suite = _suite_d_etiquette(ligne)
        if suite:  # « OBJECTIF : corriger… » → « Corriger… »
            return suite[0].upper() + suite[1:]
        if suite == "" and i + 1 < len(lignes):
            return _nu(lignes[i + 1])
    return ""


def titre_lisible(prompt: str) -> str:
    """Titre court de ce qu'on demande dans `prompt` (`""` pour un prompt vide)."""
    lignes = [l for l in str(prompt or "").splitlines() if l.strip()]
    if not lignes:
        return ""
    for i, ligne in enumerate(lignes[:3]):
        if _GABARIT.search(ligne) and i + 1 < len(lignes):
            return titre_lisible("\n".join(lignes[i + 1:]))
    premiere = lignes[0]
    if not _contexte(premiere) and _suite_d_etiquette(premiere) is None:
        return _court(_nu(premiere))
    choisie = _par_etiquette(lignes) or next((_nu(l) for l in lignes if not _contexte(l)), _nu(premiere))
    return _court(choisie)
