# [desc] Caps a Grep files_with_matches/count result and prints its paths relative to the agent's folder. [/desc]
"""Plafond — pas un garde-fou — pour les listes de chemins que rend `Grep`.

Mesuré le 2026-10-07 (session d407d73d, opus-5-5) : un `Grep(output_mode=
"files_with_matches")` sans `path` ni `glob`, lancé depuis la racine du monorepo
demo, a rendu 149 chemins absolus = 18 895 caractères = 12 261 tokens d'entrée,
20 % de l'input frais de toute la session, pour 2 fichiers utiles. Le résumé de
débordement existant ne couvrait que le mode `content`, et le `max_output` global
du registre (120 000 car.) ne mord jamais à cette échelle.

Deux leviers, cumulés :
- les chemins sous le dossier de l'agent sont écrits RELATIFS à lui : le préfixe
  `C:\\Users\\...\\demo\\` (42 car.) répété sur chaque ligne tokenise très mal ;
  un chemin relatif se relit tel quel par `Read`, qui résout depuis ce même dossier ;
- au-delà de `GREP_FILES_CAP` fichiers, on affiche une tête répartie à tour de rôle
  entre les dossiers de premier niveau (chaque zone a ses représentants, au lieu
  des 30 premiers chemins d'un seul dossier d'archives), le total réel, et le
  décompte des fichiers par dossier pour que l'agent restreigne `path`/`glob`.

L'appel ne refuse jamais : un garde-fou coûte un aller-retour et n'apprend rien.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict

GREP_FILES_CAP = 30
_TOP_DIRS = 10
_SCRATCH = "[scratch] "
_SEPARATEURS = re.compile(r"[\\/]")


def relativiser(sortie: str, dossier_agent: str) -> str:
    """Retire `dossier_agent` + séparateur en tête de chaque ligne (indentation gardée)."""
    prefixe = os.path.join(os.path.normpath(dossier_agent), "")
    return re.sub(r"(?m)^(\s*)" + re.escape(prefixe), r"\1", sortie)


def chemin_affiche(chemin: str, dossier_agent: str) -> str:
    """`chemin` tel que `relativiser` l'écrit : relatif s'il est sous le dossier, `.` s'il l'est."""
    if os.path.normpath(chemin) == os.path.normpath(dossier_agent):
        return "."
    return relativiser(os.path.normpath(chemin), dossier_agent)


def _chemin_de_ligne(ligne: str, mode: str) -> str:
    """Le chemin d'une ligne `-l` (`chemin`) ou `-c` (`chemin:N`)."""
    return ligne.rsplit(":", 1)[0] if mode == "count" else ligne


def _dossier_de_tete(chemin: str, racine: str) -> str:
    """Dossier de premier niveau SOUS la racine cherchée, écrit comme un `path=` réutilisable."""
    if chemin.startswith(_SCRATCH):
        return _SCRATCH.strip()
    dedans = chemin
    if racine != "." and chemin.startswith(os.path.join(racine, "")):
        dedans = chemin[len(os.path.join(racine, "")):]
    elif os.path.isabs(chemin):
        return os.path.dirname(chemin)
    morceaux = _SEPARATEURS.split(dedans, maxsplit=1)
    if len(morceaux) == 1:
        return racine
    return morceaux[0] if racine == "." else os.path.join(racine, morceaux[0])


def _tete_repartie(lignes: list[str], groupes: dict[str, str]) -> list[str]:
    """Les `GREP_FILES_CAP` premières lignes, prises à tour de rôle dans chaque dossier."""
    par_dossier = defaultdict(list)
    for ligne in sorted(lignes):
        par_dossier[groupes[ligne]].append(ligne)
    rang = {ligne: i for paquet in par_dossier.values() for i, ligne in enumerate(paquet)}
    return sorted(sorted(lignes, key=lambda l: (rang[l], l))[:GREP_FILES_CAP])


def plafonner_fichiers(sortie: str, mode: str, racine: str) -> str:
    """Sortie `files_with_matches`/`count` plafonnée ; intacte sous le plafond.

    `racine` est le dossier cherché tel qu'il apparaît dans `sortie` (relatif ou `.`).
    """
    lignes = [l for l in sortie.splitlines() if l.strip()]
    if len(lignes) <= GREP_FILES_CAP:
        return sortie
    groupes = {l: _dossier_de_tete(_chemin_de_ligne(l, mode), racine) for l in lignes}
    par_dossier = Counter(groupes.values())
    rendu = _tete_repartie(lignes, groupes)
    resume = [
        "",
        f"[Grep : {len(lignes)} fichiers correspondent, {len(rendu)} affichés "
        "(répartis entre les dossiers). Plafond d'affichage, rien n'est filtré. "
        "Recherche trop large : restreins avec path= (un des dossiers ci-dessous) "
        "ou glob= (ex. \"*.py\").]",
        "Fichiers par dossier :",
    ]
    for dossier, nombre in par_dossier.most_common(_TOP_DIRS):
        resume.append(f"  {dossier}  ({nombre})")
    if len(par_dossier) > _TOP_DIRS:
        resume.append(f"  (+{len(par_dossier) - _TOP_DIRS} autres dossiers)")
    return "\n".join(rendu + resume)
