# [desc] Deux libellés de tâche disent-ils le MÊME point ? Comparaison lexicale pure (mots significatifs, identifiants), réglée sur les doublons réels des suites de clôture. [/desc]
"""Rapprocher deux libellés de point ouvert sans modèle de langue.

Cas réel (essai du 2026-09-24/25, chantier « Portail des énigmes ») : trois clôtures ont
déclaré le même reste sous trois libellés — « Brancher d'autres sites sources que le
Kangourou », « Étendre le scraping à d'autres sites d'énigmes (après le Kangourou) »,
« Étendre le scraping à d'autres sites d'énigmes » — et deux décisions sur « Q25/Q26 » à une
minute d'écart. L'égalité de titres ne rapprochait rien.

Règles (fonction PURE, `meme_point`), sur les mots significatifs (accents, casse, mots vides
et pluriels retirés) :

1. **Inclusion** : les mots de l'un (au moins 3) sont tous dans l'autre.
2. **Identifiants communs** : au moins 2 identifiants partagés (« q25 », « 0f852f4d »,
   « 2024 » — un mot qui porte un chiffre), sans identifiant propre de part et d'autre.
3. **Recouvrement** : au moins 3 mots communs, soit 60 % des mots du plus court, et aucun
   identifiant qui les distingue (« Q23 » ≠ « Q25 »).

Réglage conservateur : deux libellés qui ne partagent que 2 mots (« Corriger les tests de
l'API » / « … du front ») restent distincts. Un rapprochement ne perd rien : l'appelant lie le
point à la tâche existante et lui ajoute le libellé en précision.
"""
from __future__ import annotations

import re
import unicodedata

MOTS_VIDES = frozenset("""
a au aux avec ce ces cet cette dans de des du elle en et est il ils je la le les leur lui ma
mais me mes moi mon ne ni nos notre nous on ou par pas pour qu que qui sa sans se ses si son
sur ta te tes toi ton tu un une vos votre vous y apres avant plus tout tous toute toutes
aujourd hui seulement puis entre chez vers sous
""".split())

_MOT = re.compile(r"[0-9a-z]+")


def _plat(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", str(texte or ""))
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn").casefold()


def _racine(mot: str) -> str:
    if len(mot) > 3 and mot[-1] in "sx" and not mot[-2].isdigit():
        return mot[:-1]
    return mot


def _identifiant(mot: str) -> bool:
    """Un mot qui désigne un objet précis : il porte un chiffre (q25, 0f852f4d) ou est une année."""
    chiffres = sum(c.isdigit() for c in mot)
    return chiffres > 0 and (chiffres < len(mot) or len(mot) >= 4)


def mots(texte: str) -> frozenset[str]:
    """Mots significatifs d'un libellé (forme comparable)."""
    retenus = set()
    for mot in _MOT.findall(_plat(texte)):
        if mot in MOTS_VIDES:
            continue
        if len(mot) < 3 and not _identifiant(mot):
            continue
        retenus.add(_racine(mot))
    return frozenset(retenus)


def meme_point(a: str, b: str) -> bool:
    """`a` et `b` désignent-ils le même point ouvert ? (symétrique)"""
    ma, mb = mots(a), mots(b)
    if not ma or not mb:
        return False
    if ma == mb:
        return len(ma) >= 2  # « Suite A » / « Suite B » : un seul mot commun ne prouve rien
    communs = ma & mb
    ids_a = {m for m in ma if _identifiant(m)}
    ids_b = {m for m in mb if _identifiant(m)}
    ids_distincts = bool(ids_a - ids_b) and bool(ids_b - ids_a)
    petit = min(ma, mb, key=len)
    if len(petit) >= 3 and communs == petit and not ids_distincts:
        return True
    if len(ids_a & ids_b) >= 2 and not ids_distincts:
        return True
    return len(communs) >= 3 and len(communs) >= 0.6 * len(petit) and not ids_distincts
