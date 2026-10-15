# [desc] Échecs d'un run comparés à la base (merge-base avec develop/master) : les ids en échec sont rejoués UNE fois dans un worktree jetable du commit de base, résultat mis en cache par SHA dans ~/.bouzecode/test_baselines ; sépare NEW et pre-existing. [/desc]
"""Un échec déjà présent sur develop n'est pas celui de l'agent.

Suite finale du 2026-10-13 : impossible de distinguer les échecs anciens des nouveaux, et
l'agent a « corrigé » un échec ancien en affaiblissant un test de sécurité. Après un run
`full=true` ou impacté, les ids en échec sont rejoués sur le commit de base :

- worktree détaché jetable du merge-base, retiré ensuite (la branche de base n'est jamais
  touchée) ; même interpréteur, `PYTHONPATH=<worktree de base>/src` ;
- seuls les ids en échec, filtrés par le plugin de sélection (un test NOUVEAU absent de la
  base ne fait pas échouer la session : il est « absent », donc NEW) ;
- cache `~/.bouzecode/test_baselines/<dépôt>/<sha>.json` : chaque commit de base n'est
  calculé qu'une fois par id, pour tous les agents.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from ...testd.common import sans_fenetre
from .git_base import base_de_la_branche, nom_du_depot, racine_git, worktree_jetable
from .selection_plugin import injecter_selection, lire_issues, nettoyer

MAX_IDS_MONTRES = 25
STATUTS_EN_ECHEC = ("failed", "error")


def chemin_du_cache(racine: Path, sha: str) -> Path:
    return Path.home() / ".bouzecode" / "test_baselines" / nom_du_depot(racine) / f"{sha}.json"


def _lire_cache(chemin: Path) -> dict[str, str]:
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else {}


def _ecrire_cache(chemin: Path, nouveaux: dict[str, str]) -> None:
    """Fusion avec ce qu'un autre agent a pu écrire entre-temps, remplacement atomique."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    contenu = {**_lire_cache(chemin), **nouveaux}
    descripteur, temporaire = tempfile.mkstemp(dir=chemin.parent, suffix=".tmp")
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        json.dump(contenu, fichier, indent=0, sort_keys=True)
    os.replace(temporaire, chemin)


def _rejouer_sur_la_base(racine: Path, sha: str, ids: list[str], python: str, env: dict,
                         args_communs: list[str], timeout: int) -> dict[str, str] | None:
    relatif = racine.resolve().relative_to(racine_git(racine).resolve())
    with worktree_jetable(racine, sha) as dossier:
        projet_base = dossier / relatif
        fichiers = sorted({i.split("::")[0] for i in ids
                           if (projet_base / i.split("::")[0]).is_file()})
        issues: dict[str, str] = {}
        if fichiers:
            #  Le `src` du worktree de base remplace celui de la branche ; le reste (plugins
            #  injectés) est gardé.
            autres = [s for s in env.get("PYTHONPATH", "").split(os.pathsep)
                      if s and Path(s) != racine / "src"]
            env_base = {**env, "PYTHONPATH": os.pathsep.join([str(projet_base / "src"), *autres])}
            commande = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args_communs,
                        "-o", "faulthandler_timeout=120", "-p", "no:rerunfailures", *fichiers]
            plugin, sortie = injecter_selection(env_base, commande, ids, fichiers)
            try:
                subprocess.run(commande, cwd=str(projet_base), env=env_base,
                               capture_output=True, timeout=timeout, **sans_fenetre())
                issues = lire_issues(sortie)
            except subprocess.TimeoutExpired:
                return None  # rien en cache : un run tronqué ne dit rien de la base
            finally:
                nettoyer(plugin)
    return {i: issues.get(i) or ("passed" if "::" not in i and i.split("::")[0] in fichiers
                                 else "absent") for i in ids}


def comparer_avec_la_base(racine: Path, echecs: list[str], python: str | None, env: dict,
                          args_communs: list[str], timeout: int) -> str:
    """Section « NEW failures / pre-existing on base » pour ces ids en échec ; '' sans échec."""
    if not echecs:
        return ""
    nom, sha = base_de_la_branche(racine)
    if not sha or not python:
        return ("comparaison avec la base impossible : "
                + ("ni develop ni master." if not sha else "interpréteur du run introuvable.") + "\n")
    cache = chemin_du_cache(racine, sha)
    connus = _lire_cache(cache)
    manquants = [i for i in echecs if i not in connus]
    if manquants:
        nouveaux = _rejouer_sur_la_base(racine, sha, manquants, python, env, args_communs, timeout)
        if nouveaux is None:
            return (f"comparaison avec {nom} interrompue : le rejeu sur la base a dépassé "
                    f"{timeout}s ({len(manquants)} ids).\n")
        _ecrire_cache(cache, nouveaux)
        connus.update(nouveaux)
    #  Une erreur de setup sur la base (environnement) est aussi ancienne qu'un échec.
    anciens = [i for i in echecs if connus.get(i) in STATUTS_EN_ECHEC]
    nouveaux_echecs = [i for i in echecs if connus.get(i) not in STATUTS_EN_ECHEC]
    lignes = [f"comparaison avec {nom} (merge-base {sha[:8]}, {len(manquants)} id(s) rejoués, "
              f"cache {cache}) :",
              f"NEW failures ({len(nouveaux_echecs)}) :", *_liste(nouveaux_echecs),
              f"pre-existing on base {nom} ({len(anciens)}) — pas les tiens, ne les « corrige » "
              f"pas en affaiblissant le test :", *_liste(anciens)]
    return "\n".join(lignes) + "\n"


def _liste(ids: list[str]) -> list[str]:
    reste = len(ids) - MAX_IDS_MONTRES
    return [f"  {i}" for i in ids[:MAX_IDS_MONTRES]] + ([f"  … (+{reste})"] if reste > 0 else [])
