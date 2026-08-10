# [desc] Signature de périmètre d'un prompt : ancres de code + mots distinctifs, et leur similarité. [/desc]
"""Réduire un prompt de ticket à CE QU'IL DÉSIGNE, pour comparer deux périmètres.

Deux rédactions différentes du même livrable partagent les mêmes ANCRES — la table
`docs.article_views`, la route `/api/file`, le module `src/apps/wiki/`. C'est le signal
fort : un nom de table ne se retrouve pas par hasard dans deux tickets. Les mots ordinaires
ne servent que d'appoint, et le texte de service (« règles projet », « verdict », « uv
run ») est retiré : il est IDENTIQUE dans tous les prompts du dépôt et noierait le signal.
"""
from __future__ import annotations

import re
import unicodedata

# `docs.article_views`, `chat.conversations` — un schéma/table ou un module pointé.
_ANCRE_POINTEE = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]{2,})+\b")
# `/api/file`, `src/apps/wiki/` — une route ou un chemin de module.
_ANCRE_CHEMIN = re.compile(r"\b[a-z0-9_.-]*(?:/[a-z0-9_.-]+)+/?")
_MOT = re.compile(r"[a-z][a-z0-9_]*")

# Texte de SERVICE : présent dans quasi tous les prompts du dépôt (bloc « règles projet »,
# protocole de verdict, vocabulaire de mission). Il ne dit rien du périmètre.
_SERVICE = frozenset("""
regles regle projet projets stricte strictes ticket tickets mission missions agent agents
verdict termine terminer livrable livrables objectif objectifs contexte cadrage decision
suite repo depot branche worktree prompt consigne consignes tache taches faire fais
tests test tester correctif poetry magicmock unittest mock patch fichier fichiers lignes
ligne dossier dossiers readme deploie deploiement azure install pip logger except
exemple explicitement clairement notamment ensuite avant apres pendant chaque toute toutes
tous cette celui ceux leur leurs elle elles dans avec sans pour donc mais aussi comme
quand alors etre sont doit dois faut peux plus moins meme autre autres deja encore
users home repos workspace application
""".split())

_MIN_LONGUEUR_MOT = 5
# Une ancre partagée pèse autant que 4 mots partagés : nommer la même table est un aveu de
# périmètre, partager du vocabulaire ne l'est pas.
_POIDS_ANCRE = 4.0


def _plier(text: str) -> str:
    """Minuscules sans accents : `MESURE DIRECTE` et `mesure directe` sont le même mot."""
    decompose = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def anchors(text: str) -> set[str]:
    """Les identifiants concrets désignés par le prompt (tables, routes, chemins)."""
    plie = _plier(text).replace("\\", "/")
    trouves = set(_ANCRE_POINTEE.findall(plie))
    for chemin in _ANCRE_CHEMIN.findall(plie):
        normalise = chemin.strip("/")
        # Un chemin absolu de dépôt (/home/dev/demo_app) est commun à tous les
        # tickets du projet : seuls ses derniers segments distinguent un périmètre.
        segments = [s for s in normalise.split("/") if s and s not in _SERVICE]
        if segments:
            trouves.add("/".join(segments[-3:]))
    return {a for a in trouves if len(a) >= 6}


def keywords(text: str) -> set[str]:
    """Les mots porteurs de sens, hors texte de service et hors mots trop courts."""
    plie = _plier(text)
    return {m for m in _MOT.findall(plie)
            if len(m) >= _MIN_LONGUEUR_MOT and m not in _SERVICE}


def scope_signature(text: str) -> set[str]:
    """Le périmètre d'un prompt : ses ancres (préfixées, pour ne jamais collisionner avec
    un mot) et ses mots distinctifs."""
    return {f"@{a}" for a in anchors(text)} | keywords(text)


def similarity(gauche: set[str], droite: set[str]) -> float:
    """Jaccard pondéré : une ancre partagée pèse `_POIDS_ANCRE` mots partagés.

    Sans pondération, les trois rédactions de la « mesure directe » ne se distinguaient pas
    assez des deux moitiés du sujet : elles partagent beaucoup de prose de contexte. Ce qui
    les rend VRAIMENT identiques, c'est de nommer la même table et la même route.
    """
    if not gauche or not droite:
        return 0.0
    return _poids(gauche & droite) / _poids(gauche | droite)


def _poids(mots: set[str]) -> float:
    return sum(_POIDS_ANCRE if m.startswith("@") else 1.0 for m in mots)
