# [desc] Suivi des executions Rundeck par le watchdog : `suivre` a cadence bornee, `recuperer` a la fin, run clos (livre ou plante), signalement d'un echec. [/desc]
"""Appele par `wake.tick` sur les tickets qu'il reconcilie deja (aucune lecture de plus).

Pour chaque run remote ouvert : `bouzecode.remote.suivre(execution_id)` au plus une fois par
`CADENCE_S` et par execution (le tick tourne toutes les 8 s, Rundeck n'a pas a etre sonde a ce
rythme). Execution terminee : `recuperer` (resultats rapatries, branche `agent/<ticket>`
reimportee, job et share nettoyes), puis le run est clos. Le reveil du parent est celui de
tout enfant : `wake.process_wakes`, qui suit dans le meme tick, lit le run clos.

Issue LIVREE : la commande a tourne jusqu'au bout (code entier ; en mode agent, code 0 et
branches reimportees). Sinon ECHEC : ticket `stopped{crashed}` (transition de crash, qui
reveille le parent) + signalement visible de l'humain dans « A traiter ». Une fin d'agent
MAITRISEE sans livraison (refus du modele, fin forcee : `rapport.issue_de_l_agent`, donc
`close_reasons.issue_de_fin`) finit `idle_no_delivery`, sa raison pour code ; un refus porte
son propre signalement (`refus_modele` : reformuler ou relancer).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .. import refus_modele, signalements
from ..fsm import etats
from . import rapport, retour, runs

_log = logging.getLogger(__name__)

CADENCE_S = 30.0
#: Horloge du suivi (remplacable par un test : `monkeypatch.setattr(suivi, "HORLOGE", ...)`).
HORLOGE = time.monotonic
_dernier_suivi: dict[str, float] = {}


def _module_distant():
    from bouzecode import remote
    return remote


def _a_suivre(execution_id: str) -> bool:
    maintenant = HORLOGE()
    dernier = _dernier_suivi.get(execution_id)
    if dernier is not None and maintenant - dernier < CADENCE_S:
        return False
    _dernier_suivi[execution_id] = maintenant
    return True


def suivre_tickets(slug: str, rows: list[dict]) -> None:
    """Un pas de suivi pour chaque run remote ouvert de ces tickets. Resilient par run."""
    for ticket in rows:
        for run in runs.runs_ouverts(ticket) if isinstance(ticket, dict) else []:
            try:
                _suivre_un_run(slug, ticket, run)
            except Exception:  # noqa: BLE001 — un run illisible ne prive pas les autres du suivi
                _log.exception("distant.suivi: run %s du ticket %s", run.get("agent_id"), ticket.get("id"))


def _suivre_un_run(slug: str, ticket: dict, run: dict) -> None:
    execution_id = str(run.get("execution_id") or "")
    if not execution_id:
        _echouer(slug, ticket, run, "run remote sans execution_id")
        return
    if not _a_suivre(execution_id):
        return
    remote = _module_distant()
    etat = remote.suivre(execution_id)
    if not etat.get("ok"):
        if etat.get("code") == "execution_inconnue":
            _echouer(slug, ticket, run, etat.get("message") or "execution inconnue du registre local")
        else:  # acces Rundeck momentane : retente a la prochaine cadence
            _log.warning("distant.suivi: %s injoignable (%s)", execution_id, etat.get("message"))
        return
    if not etat.get("termine"):
        return
    _cloturer(slug, ticket, run, etat, remote.recuperer(execution_id))


def _cloturer(slug: str, ticket: dict, run: dict, etat: dict, resultat: dict) -> None:
    journal_fin = str(etat.get("journal_fin") or "")
    if not resultat.get("ok"):
        if resultat.get("code") == "en_cours":
            return
        _echouer(slug, ticket, run, f"recuperation impossible : {resultat.get('message')}", journal_fin)
        return
    dossier = Path(str(resultat.get("dossier_local") or ""))
    raison = rapport.raison_d_echec(run, etat, resultat)
    champs = {"statut_rundeck": str(resultat.get("statut") or ""), "code": resultat.get("code"),
              "branches": resultat.get("branches") or {}, "dossier_local": str(dossier),
              "journal_fin": journal_fin[-2000:],
              "close_reason": str(resultat.get("close_reason") or ""),
              "close_detail": str(resultat.get("close_detail") or ""),
              "final_answer": bool(resultat.get("final_answer")),
              "reponse_path": str(rapport.ecrire_reponse(run, resultat, dossier))}
    if raison:
        _echouer(slug, ticket, run, raison, journal_fin, champs)
        return
    # Worktree local de la branche rapatriee AVANT la cloture : le ticket livre porte deja le
    # `worktree` que `integrate` attend (sinon 409 pas_isole et merge a la main).
    worktrees_locaux = retour.preparer(slug, ticket, champs["branches"])
    champs["worktrees_locaux"] = {p: m.get("worktree") or m.get("error") for p, m in worktrees_locaux.items()}
    runs.terminer(slug, ticket, run["agent_id"], {**champs, "issue": runs.LIVRE})


def _echouer(slug: str, ticket: dict, run: dict, raison: str, journal_fin: str = "",
             champs: dict | None = None) -> None:
    """Run clos en ECHEC, signalement pour l'humain, ticket `crashed` (reveil du parent) — ou
    `idle_no_delivery` pour une fin d'agent maitrisee sans livraison (refus, fin forcee)."""
    champs = champs or {}
    runs.terminer(slug, ticket, run["agent_id"], {**champs, "issue": runs.ECHEC,
                                                  "raison": raison[:500],
                                                  "journal_fin": journal_fin[-2000:]})
    detail = f"{raison}\nExecution {run.get('execution_id')} : {run.get('url') or '-'}"
    if champs.get("close_reason") == refus_modele.REFUS_MODELE:
        refus_modele.signaler(slug, ticket, run["agent_id"], detail)
    else:
        signalements.creer(
            "alerte", f"Execution Rundeck en echec : {ticket.get('title') or ticket['id']}",
            detail=detail, action_attendue="Lire la raison, puis relancer la tache (en local ou sur Rundeck).",
            agent_id=run["agent_id"], parents=refus_modele.parents_de(ticket),
            ticket_slug=slug, ticket_id=ticket["id"])
    issue, code = rapport.issue_de_l_agent(champs)
    if issue == etats.IDLE_NO_DELIVERY:  # fin maitrisee sans livraison : pas un crash
        runs.finir(slug, ticket, run["agent_id"], etats.RUN_ENDED, delivered=False, code=code,
                   close_reason=champs["close_reason"], message=raison[:500])
        return
    runs.finir(slug, ticket, run["agent_id"], etats.CRASHED, code="crashed", message=raison[:500])


def oublier_cadence() -> None:
    """Isolation des tests : oublie la date du dernier suivi de chaque execution."""
    _dernier_suivi.clear()
