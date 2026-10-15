# [desc] Validates a human developer's task submission and records it as an agent-style delivery run. [/desc]
"""Un développeur sans IA rend une tâche comme le ferait un agent.

Le rendu est validé par les MÊMES fonctions que la clôture du modèle (`close_validator`), puis
matérialisé comme une livraison d'agent : un ticket, un run `kind="humain"` dont la session est
un JSON au format d'une session (dernier message assistant = appel `FinalAnswer`), et la
transition `RUN_ENDED` livrée → `DELIVERED`. La vue du Bureau lit donc ce rendu par
`recap_de_session`, exactement comme celui d'un agent ; aucun format parallèle."""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from bouzecode.backend.agent.close_validator import (
    missing_recap_fields, missing_recap_sections, missing_taches_fields,
)
from bouzecode.backend.agent.related_files import normaliser_related_files
from bouzecode.web_v2.services.erreurs import Refus

KIND = "humain"


def _dossier_rendus(micro_id: str) -> Path:
    from bouzecode.paths import data_dir
    return Path(data_dir()) / "web_v2" / "rendus" / str(micro_id)


def _chemin_depot(slug: str) -> str:
    """Chemin local du dépôt `slug` ('' si inconnu : commits non vérifiables)."""
    try:
        from bouzecode.web_v2.services.work import projects
        projet = projects.find(slug) or {}
    except Exception:  # noqa: BLE001 — registre indisponible : pas de vérification git
        return ""
    return str(projet.get("path") or "")


def _texte(valeur: object) -> str:
    return str(valeur or "").strip()


def _tests_en_texte(detail: dict) -> str:
    verts = "verts" if detail.get("verts") else "PAS verts"
    texte = f"{detail.get('nombre')} test(s) {detail.get('niveau')}, {verts}"
    return texte + (f" — {detail['chemin']}" if _texte(detail.get("chemin")) else "")


def normaliser(corps: dict) -> dict:
    """Valide le rendu saisi ; lève `Refus("rendu_incomplet", 400, manquants=[...])`."""
    corps = corps if isinstance(corps, dict) else {}
    manquants: list[str] = []
    answer = str(corps.get("answer") or "")
    if not answer.strip():
        manquants.append("answer")
    else:
        manquants += [f"answer {m}" for m in missing_recap_sections(answer)]
    detail = corps.get("tests_detail")
    if not isinstance(detail, dict):
        manquants.append("tests_detail")
        detail = {}
    else:
        nombre = detail.get("nombre")
        if isinstance(nombre, bool) or not isinstance(nombre, int) or nombre < 0:
            manquants.append("tests_detail.nombre")
        if not _texte(detail.get("niveau")):
            manquants.append("tests_detail.niveau")
        if not isinstance(detail.get("verts"), bool):
            manquants.append("tests_detail.verts")
    recap = dict(corps.get("recap") or {}) if isinstance(corps.get("recap"), dict) else {}
    if not _texte(recap.get("tests")) and not manquants_tests(manquants):
        recap["tests"] = _tests_en_texte(detail)
    manquants += missing_recap_fields(recap, coding=True)
    terminees, restantes = corps.get("taches_terminees"), corps.get("taches_restantes")
    manquants += missing_taches_fields(terminees, restantes)
    commits = corps.get("commits")
    if not isinstance(commits, list) or not commits:
        manquants.append("commits")
        commits = []
    for i, c in enumerate(commits):
        if not isinstance(c, dict) or not _texte(c.get("sha")):
            manquants.append(f"commits[{i}].sha")
    if manquants:
        raise Refus("rendu_incomplet", "Rendu incomplet : " + ", ".join(manquants), 400,
                    manquants=manquants)
    return {
        "answer": answer, "recap": recap, "taches_terminees": terminees,
        "taches_restantes": restantes, "tests_detail": detail,
        "related_files": normaliser_related_files(corps.get("related_files")),
        "commits": [{"sha": _texte(c["sha"]), "branche": _texte(c.get("branche"))}
                    for c in commits],
        "auteur": _texte(corps.get("auteur")) or os.environ.get("USERNAME")
        or os.environ.get("USER") or "humain",
    }


def manquants_tests(manquants: list[str]) -> bool:
    return any(m.startswith("tests_detail") for m in manquants)


def _git(depot: str, *args: str) -> bool:
    try:
        return subprocess.run(["git", "-C", depot, *args], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def verifier_commits(slug: str, commits: list[dict]) -> list[dict]:
    """Vérifie chaque commit (et sa branche) avec git si le dépôt est local. Refus 400 sinon."""
    depot = _chemin_depot(slug)
    if not depot or not Path(depot, ".git").exists():
        return [{**c, "verifie": False} for c in commits]
    faux: list[str] = []
    for c in commits:
        if not _git(depot, "cat-file", "-e", f"{c['sha']}^{{commit}}"):
            faux.append(f"commit {c['sha']} introuvable")
        elif c["branche"] and not _git(depot, "merge-base", "--is-ancestor", c["sha"], c["branche"]):
            faux.append(f"commit {c['sha']} absent de la branche {c['branche']}")
    if faux:
        raise Refus("commit_inconnu", "; ".join(faux), 400, manquants=faux)
    return [{**c, "verifie": True} for c in commits]


def _session(rendu: dict, micro_id: str, ticket_id: str, session_id: str) -> dict:
    """Une session au format d'un agent : dernier message assistant = appel FinalAnswer."""
    entree = {k: rendu[k] for k in ("answer", "recap", "taches_terminees", "taches_restantes")}
    entree["related_files"] = rendu.get("related_files") or []
    return {
        "session_id": session_id, "auteur": {"type": KIND, "nom": rendu["auteur"]},
        "micro_id": micro_id, "ticket_id": ticket_id,
        "final_answer": rendu["answer"], "recap": rendu["recap"],
        "taches_terminees": rendu["taches_terminees"],
        "taches_restantes": rendu["taches_restantes"], "taches_declarees": True,
        "related_files": rendu.get("related_files") or [],
        "rendu": rendu,
        "messages": [{"role": "assistant", "content": "",
                      "tool_calls": [{"id": f"rendu_{session_id}", "name": "FinalAnswer",
                                      "input": entree}]}],
    }


def enregistrer(micro_id: str, corps: dict) -> dict:
    """Valide puis livre le rendu ; renvoie {ticket_id, slug, session_path, suites}."""
    from . import _persistence, ticket_fsm
    from .cloture_micros import ouvrir_micros_de_cloture
    from .fsm import etats
    from .micros import lier_ticket, marquer_etat
    from .runs_ticket import add_run, mark_run_completed
    from .taches_actions import VERROU_LANCEMENT, _micro_ou_refus, resoudre_depot
    from .tickets import create_ticket

    micro = _micro_ou_refus(micro_id)
    rendu = normaliser(corps)
    with VERROU_LANCEMENT:
        slug = resoudre_depot(micro, _texte((corps or {}).get("projet_slug")))
        rendu["commits"] = verifier_commits(slug, rendu["commits"])
        rendu["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        titre = _texte(micro.get("titre")) or f"Tâche {micro_id}"
        ticket = create_ticket(slug, titre, _texte(micro.get("corps")) or titre)
        tid = str(ticket["id"])
        session_id = f"humain_{uuid.uuid4().hex[:8]}"
        agent_id = session_id
        chemin = _dossier_rendus(micro_id) / f"{tid}.json"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(_session(rendu, micro_id, tid, session_id),
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        add_run(slug, ticket, agent_id, KIND, KIND, extra={
            "session_path": str(chemin), "auteur": rendu["auteur"],
            "commits": rendu["commits"]}, actor=rendu["auteur"])
        mark_run_completed(slug, _persistence._load_one(slug, tid) or ticket, agent_id)
        ticket_fsm.appliquer(slug, tid, etats.RUN_ENDED, rendu["auteur"], agent_id=agent_id,
                             delivered=True, final_answer=True, close_reason="final_answer")
        lier_ticket(micro_id, slug, tid)
        marquer_etat(micro_id, "lancee")
    suites = ouvrir_micros_de_cloture(rendu["taches_restantes"], tid, slug, session_id)
    return {"ticket_id": tid, "slug": slug, "session_path": str(chemin),
            "suites": len(suites or [])}


def dernier(micro_id: str) -> dict | None:
    """Le dernier rendu humain enregistré pour la micro (relecture du formulaire)."""
    dossier = _dossier_rendus(micro_id)
    if not dossier.is_dir():
        return None
    fichiers = sorted(dossier.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for chemin in reversed(fichiers):
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return {**(data.get("rendu") or {}), "ticket_id": data.get("ticket_id")}
    return None
