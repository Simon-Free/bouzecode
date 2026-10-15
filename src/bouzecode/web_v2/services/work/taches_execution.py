# [desc] Execution d'une tache lancee : cible (local | rundeck), projets concernes et fichiers non suivis a transmettre — validee, persistee, injectee dans le prompt. [/desc]
"""Le champ `execution` d'un lancement de tache (contrat : docs/specs/assistant_execution.md).

    execution = {"cible": "local" | "rundeck",
                 "projets": [slug, ...],                        # le 1er = depot principal
                 "fichiers_non_suivis": {slug: [chemin relatif, ...]},
                 # rundeck seulement :
                 "mode": "agent" | "tests", "commande": str, "navigateur": bool}

`mode="tests"` : `commande` = les arguments de pytest (chemins, -m, -k) ; la VM joue
`uv run --extra test python -m pytest <commande> --junitxml=...` (captures Playwright si
`navigateur`, vrai par defaut en tests). `mode="agent"` (defaut) : un agent bouzecode headless.

* validee ici (cible connue, projets enregistres, chemins relatifs sans `..`) ;
* persistee sur la TACHE (table `micro_executions`, une relance la reprend) et sur le
  TICKET (`ticket["execution"]`) ;
* injectee dans le prompt de l'agent (section « Execution ») ;
* `cible="rundeck"` n'est PAS executee ici : on appelle le point d'entree
  `bouzecode.remote.lancer_sur_rundeck(ticket, execution)`, importe paresseusement. Module
  absent = refus explicite `cible_indisponible`, jamais un repli silencieux sur le local.
  Lancement accepte : le run `remote` est pose sur le ticket (`distant.runs.ajouter`), le
  watchdog le suit jusqu'a son issue et reveille le parent (`distant.suivi`).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path, PurePosixPath

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import _persistence, projects, tickets
from ._store_connection import transaction
from .distant import runs as runs_distants
from .taches_actions import Refus

CIBLES = ("local", "rundeck")
MODES_DISTANTS = ("agent", "tests")
MODULE_DISTANT = "bouzecode.remote"
POINT_D_ENTREE = "lancer_sur_rundeck"

_SCHEMA = ("CREATE TABLE IF NOT EXISTS micro_executions ("
           " micro_id TEXT PRIMARY KEY, data TEXT NOT NULL, at TEXT NOT NULL)")


def _tx():
    chemin = _persistence._db_path()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    return transaction(chemin)


def lire(micro_id: str) -> dict | None:
    with _tx() as conn:
        conn.execute(_SCHEMA)
        ligne = conn.execute("SELECT data FROM micro_executions WHERE micro_id = ?",
                             (micro_id,)).fetchone()
    return json.loads(ligne[0]) if ligne else None


def _enregistrer(micro_id: str, execution: dict) -> None:
    with _tx() as conn:
        conn.execute(_SCHEMA)
        conn.execute("INSERT OR REPLACE INTO micro_executions (micro_id, data, at)"
                     " VALUES (?, ?, ?)", (micro_id, json.dumps(execution, ensure_ascii=False),
                                           maintenant_iso()))


def _chemin_relatif_sur(chemin: str) -> bool:
    pur = PurePosixPath(str(chemin).replace("\\", "/"))
    return bool(str(chemin).strip()) and not pur.is_absolute() and ".." not in pur.parts \
        and ":" not in str(chemin)


def valider(execution: dict, slug: str) -> dict:
    """Le champ validé et normalisé (projet du lancement en tête) ; lève `Refus` (400)."""
    cible = str(execution.get("cible") or "local").strip().lower()
    if cible not in CIBLES:
        raise Refus("cible_inconnue", f"cible inconnue : {cible!r} (local ou rundeck)")
    projets = [str(p).strip() for p in execution.get("projets") or [] if str(p).strip()]
    projets = [slug] + [p for p in projets if p != slug]
    inconnus = [p for p in projets if projects.find(p) is None]
    if inconnus:
        raise Refus("depot_inconnu", f"Projet(s) non enregistre(s) : {', '.join(inconnus)}.")
    fichiers = execution.get("fichiers_non_suivis") or {}
    if not isinstance(fichiers, dict):
        raise Refus("fichiers_invalides", "fichiers_non_suivis attend {slug: [chemins]}.")
    propres: dict[str, list[str]] = {}
    for projet, chemins in fichiers.items():
        if projet not in projets:
            raise Refus("fichiers_invalides", f"« {projet} » n'est pas dans `projets`.")
        mauvais = [c for c in chemins or [] if not _chemin_relatif_sur(c)]
        if mauvais:
            raise Refus("fichiers_invalides", "Chemins relatifs au projet uniquement, sans "
                        f"`..` : {', '.join(map(str, mauvais))}.")
        propres[projet] = [str(c) for c in chemins or []]
    return {"cible": cible, "projets": projets, "fichiers_non_suivis": propres,
            **_options_distantes(execution, cible)}


def _options_distantes(execution: dict, cible: str) -> dict:
    """`mode`, `commande`, `navigateur` : n'existent que pour cible=rundeck."""
    mode = str(execution.get("mode") or "").strip().lower()
    commande = str(execution.get("commande") or "").strip()
    if not (mode or commande):
        return {}
    if cible != "rundeck":
        raise Refus("options_distantes", "`mode` et `commande` ne valent que pour cible=rundeck.")
    mode = mode or "agent"
    if mode not in MODES_DISTANTS:
        raise Refus("mode_inconnu", f"mode inconnu : {mode!r} (agent ou tests)")
    if mode == "tests" and not commande:
        raise Refus("commande_manquante", "mode tests : donne les arguments de pytest dans `commande`.")
    options = {"mode": mode, **({"commande": commande} if commande else {})}
    if mode == "tests":
        options["navigateur"] = bool(execution.get("navigateur", True))
    return options


def preparer(micro_id: str, execution: dict | None, slug: str) -> dict | None:
    """L'execution de CE lancement : celle demandee (validee puis memorisee sur la tache), sinon
    celle memorisee par un lancement precedent. None = lancement ordinaire, comme avant."""
    if execution:
        propre = valider(execution, slug)
        _enregistrer(micro_id, propre)
        return propre
    memorisee = lire(micro_id)
    return valider(memorisee, slug) if memorisee else None


def section_prompt(execution: dict | None) -> str:
    """Ce que l'agent lance doit savoir : ou il tourne, sur quels depots, quels fichiers non
    suivis lui sont transmis (absents de l'etat commite d'un worktree ou d'une machine distante)."""
    if not execution:
        return ""
    distant = execution["cible"] == "rundeck"
    lignes = ["## Execution", f"Cible : {execution['cible']}."]
    if distant:
        # Sur la VM les depots sont des clones frais, freres dans le dossier de travail, et
        # l'agent demarre dans le principal : les chemins du poste n'y existent pas.
        lignes.append("Tu tournes sur une VM Linux (Rundeck rec) : chaque depot est un clone frais, "
                      "le repertoire courant est le depot principal, les autres sont ses voisins (../<projet>).")
    lignes.append("Projets concernes :")
    for rang, slug in enumerate(execution["projets"]):
        chemin = _chemin_du_projet(slug, rang, distant)
        lignes.append(f"- {slug} : {chemin}" + (" (depot principal)" if rang == 0 else ""))
    fichiers = execution.get("fichiers_non_suivis") or {}
    if any(fichiers.values()):
        lignes.append("Fichiers NON SUIVIS transmis (hors git : lis-les a ce chemin, ne les "
                      "commite pas sans raison) :")
        for slug, chemins in fichiers.items():
            racine = _chemin_du_projet(slug, execution["projets"].index(slug), distant)
            lignes += [f"- {PurePosixPath(racine) / chemin if distant else Path(racine) / chemin}"
                       for chemin in chemins]
    return "\n\n" + "\n".join(lignes)


def _chemin_du_projet(slug: str, rang: int, distant: bool) -> str:
    if distant:
        return "." if rang == 0 else f"../{slug}"
    return (projects.find(slug) or {}).get("path", "")


def poser_sur_ticket(slug: str, ticket_id: str, execution: dict | None) -> None:
    ticket = tickets.get_ticket(slug, ticket_id) if execution else None
    if ticket is not None:
        tickets.poser(slug, ticket, execution=execution)


def point_d_entree_distant():
    """`bouzecode.remote.lancer_sur_rundeck`, ou `Refus("cible_indisponible")`."""
    if importlib.util.find_spec(MODULE_DISTANT) is None:
        raise Refus("cible_indisponible", "L'execution sur rundeck n'est pas disponible sur ce "
                    f"serveur (module {MODULE_DISTANT} absent). Lance la tache en local ou "
                    "attends l'integration du lanceur distant.", 501)
    fonction = getattr(importlib.import_module(MODULE_DISTANT), POINT_D_ENTREE, None)
    if fonction is None:
        raise Refus("cible_indisponible", f"{MODULE_DISTANT} n'expose pas {POINT_D_ENTREE}.", 501)
    return fonction


def lancer_distant(micro: dict, prompt: str, slug: str, execution: dict, parent: str) -> dict:
    """Cree le ticket du passage (sans agent local) puis le confie au lanceur distant. `micro` ne
    sert qu'au titre (`{"titre": ...}` pour un ticket cree hors du Bureau).
    Rend un verdict de la meme forme que la creation de ticket vue par l outil Agent (`routed`, `ticket_id`)."""
    lanceur = point_d_entree_distant()
    from . import dispatch
    ticket = tickets.create_ticket(slug, str(micro.get("titre") or "tache"), prompt)
    tickets.poser(slug, ticket, parent=parent or "dispatcher:manual", execution=execution)
    tickets.set_launching(slug, ticket)  # → provisioning le temps de la soumission
    resultat = lanceur({**ticket, "slug": slug}, pour_le_lanceur(execution)) or {}
    if not resultat.get("ok", False):
        motif = str(resultat.get("message") or resultat.get("erreur") or "?")
        dispatch.record_launch_failure(slug, ticket, f"Lancement rundeck refuse : {motif}")
        raise Refus("lancement_impossible", f"Lancement rundeck refuse : {motif}", 502,
                    code_distant=str(resultat.get("code") or ""))
    runs_distants.ajouter(slug, ticket, resultat, execution.get("mode") or "agent")
    #  Ce que le Bureau et la CLI montrent du lancement : le lien et les fichiers NON transmis.
    tickets.poser(slug, ticket, distant={cle: resultat.get(cle) for cle in (
        "execution_id", "url", "statut", "fichiers_refuses") if resultat.get(cle) is not None})
    return {"routed": True, "ticket_id": ticket["id"], "distant": resultat}


def pour_le_lanceur(execution: dict) -> dict:
    """En mode tests, `commande` (arguments pytest) devient la commande complete jouee sur la VM."""
    if execution.get("mode") != "tests":
        return execution
    from bouzecode.remote.tests_distants import commande_pytest_distante
    navigateur = bool(execution.get("navigateur", True))
    return dict(execution, commande=commande_pytest_distante(execution["commande"],
                                                             navigateur=navigateur))
