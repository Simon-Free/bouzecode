# [desc] Correspondance PURE des anciens drapeaux d'un ticket (done, crashed, launching, worktree.state…) vers l'état unique `state` + `state_reason`. [/desc]
"""Ce qu'un ticket écrit avant le lot L2 veut dire dans la machine à états.

PURE (aucune I/O) : sert à la migration du store au boot (`fsm.migration`) et, à la lecture,
aux lignes pas encore migrées. L'ordre reprend la priorité de l'ancien libellé
(`derive_status`) : un fait accompli (merge) d'abord, puis ce qui exige une action et primait
sur `done` (planté, merge bloqué, clôture bloquée, livraison non commitée, lancement échoué),
puis la décision humaine (`done`), puis le reste. La première règle qui s'applique gagne —
table recopiée dans `services/work/README.md` :

| Ancien drapeau                                   | state             | state_reason.code      |
|--------------------------------------------------|-------------------|------------------------|
| `worktree.state` integrated / cleaned            | closed            | integre                |
| `ephemeral` + `reaped`                           | closed            | ephemere               |
| `crashed`                                        | stopped           | crashed                |
| `worktree.state == needs_attention` (non clos)   | delivered         | merge_bloque           |
| `closure_blocked`                                | delivered         | cloture_bloquee        |
| `uncommitted` / `recolte_bloquee`                | delivered         | livraison_non_commitee |
| `launch_failed` « arrêté pendant la préparation »| stopped           | arret_preparation      |
| `launch_failed`                                  | launch_failed     | lancement_echoue       |
| `done` + `closed.outcome == "abandoned"`         | abandoned         | abandonne              |
| `done` (clos à la main, ou manager finalisé)     | closed            | accepte                |
| `launching` sans run (récent / > 30 min)         | provisioning / launch_failed | — / lancement_interrompu |
| `worktree.state` conflict / conflict_resolved    | conflict          | conflit / conflit_resolu |
| aucun run                                        | created           | —                      |
| `awaiting_reply` (enfant ré-instruit)            | running           | —                      |
| run `remote` en cours / en échec / livré         | running / stopped{crashed} / delivered | |
| dernier run `completed` (ou run `validate*`)     | delivered         | —                      |
| dernier run ouvert                               | running           | —                      |

« running » pour un run ouvert est une hypothèse : la migration de boot la confirme sur le vrai
process (`migrations._affiner_par_le_process`), et le watchdog la corrige au premier tick.
`archived`, `closure_forced`, `arret_demande`, `reaped` ne sont pas des états : `archived_at`
reste un attribut, les autres deviennent un événement du journal ou `worktree.retire_at`."""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import age_s

from . import etats

_LANCEMENT_FIGE_S = 1800  # même borne que l'ancien filtre `_launching_is_stale`
_ARRET_PREPARATION = "arrêté à ta demande pendant la préparation"

Etat = tuple[str, dict | None]


def _raison(code: str, message: str = "", **details) -> dict:
    raison = {"code": code, "message": message}
    if details:
        raison["details"] = details
    return raison


def _lancement_fige(ticket: dict) -> bool:
    age = age_s(ticket.get("created_at"))
    return age is not None and age > _LANCEMENT_FIGE_S


def _meta(ticket: dict) -> dict:
    return ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}


def _integre(ticket: dict) -> Etat | None:
    if _meta(ticket).get("state") in ("integrated", "cleaned"):
        return etats.CLOSED, _raison("integre")
    if ticket.get("ephemeral") and ticket.get("reaped"):
        return etats.CLOSED, _raison("ephemere")
    return None


def _bloquant(ticket: dict) -> Etat | None:
    """Ce qui exigeait une action et primait sur `done` dans l'ancien libellé."""
    if ticket.get("crashed"):
        return etats.STOPPED, _raison("crashed")
    if _meta(ticket).get("state") == "needs_attention" and not ticket.get("closed"):
        return etats.DELIVERED, _raison("merge_bloque", str(_meta(ticket).get("integrate_error") or ""))
    if ticket.get("closure_blocked"):
        return etats.DELIVERED, _raison("cloture_bloquee", "", enfants=str(ticket["closure_blocked"]))
    if ticket.get("uncommitted") or ticket.get("recolte_bloquee"):
        return etats.DELIVERED, _raison("livraison_non_commitee",
                                        str(ticket.get("recolte_bloquee") or ""),
                                        files=list(ticket.get("uncommitted") or []))
    echec = ticket.get("launch_failed")
    if echec:
        erreur = str((echec.get("error") if isinstance(echec, dict) else "") or "")
        if _ARRET_PREPARATION in erreur:
            return etats.STOPPED, _raison("arret_preparation", erreur)
        return etats.LAUNCH_FAILED, _raison("lancement_echoue", erreur)
    return None


def _decide(ticket: dict) -> Etat | None:
    decision = ticket.get("closed") if isinstance(ticket.get("closed"), dict) else {}
    if ticket.get("done") and decision.get("outcome") == "abandoned":
        return etats.ABANDONED, _raison("abandonne", str(decision.get("reason") or ""))
    if ticket.get("done"):
        return etats.CLOSED, _raison("accepte", str(decision.get("reason") or ""))
    return None


def _en_preparation_ou_en_conflit(ticket: dict, runs: list) -> Etat | None:
    if ticket.get("launching") and not runs:
        if _lancement_fige(ticket):
            return etats.LAUNCH_FAILED, _raison("lancement_interrompu",
                                                "serveur arrêté pendant la préparation")
        return etats.PROVISIONING, None
    if _meta(ticket).get("state") == "conflict":
        return etats.CONFLICT, _raison("conflit", files=list(_meta(ticket).get("conflict_files") or []))
    if _meta(ticket).get("state") == "conflict_resolved":
        return etats.CONFLICT, _raison("conflit_resolu", "conflit résolu, prêt à intégrer")
    return None


def _par_les_runs(runs: list) -> Etat:
    travail = next((r for r in runs if str(r.get("kind") or "") in ("work", "remote", "merge")),
                   runs[0])
    if str(travail.get("kind") or "") == "remote":
        if not travail.get("termine"):
            return etats.RUNNING, None
        if travail.get("issue") != "livre":
            return etats.STOPPED, _raison("crashed", str(travail.get("raison") or ""))
        return etats.DELIVERED, None
    if travail.get("completed") or str(travail.get("kind") or "").startswith("validate"):
        return etats.DELIVERED, None
    return etats.RUNNING, None


def etat_initial(ticket: dict) -> Etat:
    """(state, state_reason) d'un ticket ancien, d'après ses drapeaux et ses runs."""
    runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict)] \
        if isinstance(ticket.get("runs"), list) else []
    for regle in (_integre, _bloquant, _decide, lambda t: _en_preparation_ou_en_conflit(t, runs)):
        trouve = regle(ticket)
        if trouve is not None:
            return trouve
    if not runs:
        return etats.CREATED, None
    if ticket.get("awaiting_reply"):
        return etats.RUNNING, None
    return _par_les_runs(runs)
