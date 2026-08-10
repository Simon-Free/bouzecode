# [desc] Reprise auto au boot : quels sous-agents crashés repartent seuls, et lesquels jamais. [/desc]
"""Ce que le serveur reprend TOUT SEUL au prochain boot, et ce qu'il ne reprend jamais.

VRAI store de tickets SQLite (isolé sous tmp par la fixture autouse) et VRAIS
enregistrements d'agent sur disque. Seule la relance elle-même est injectée
(`resume_fn`) : aucun process n'est lancé.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import _persistence, auto_resume, tickets


@pytest.fixture()
def agents(tmp_path, monkeypatch):
    """Redirige les enregistrements d'agent vers tmp (les tickets le sont déjà par l'autouse)."""
    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    runner._list_agents_cache.clear()
    runner._agent_file_cache.clear()
    return agents_dir


def _agent_mort(agents_dir, agent_id: str) -> None:
    """Un agent dont le process est MORT sans aucune clôture propre : pas de close_reason,
    pas de FinalAnswer, pas de verdict — ce que laisse un serveur tué en plein travail."""
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "p", "model": "", "cwd": "", "pid": 0,
        "started_at": "2026-07-27T10:00:00", "returncode": -1,
        "session_path": "", "ipc_dir": "",
    }), encoding="utf-8")


def _ticket_avec_runs(runs: list[dict], parent: str = "", **extra) -> None:
    """Sème un ticket OUVERT avec les runs donnés. Ordre du store : `add_run` insérant
    chaque run EN TÊTE, runs[0] est le PLUS RÉCENT et runs[-1] le plus ancien."""
    _persistence._save("proj", [{
        "id": "T1", "title": "T", "prompt": "p", "parent": parent,
        "comments": [], "runs": runs, **extra,
    }])


def _ticket_avec_run_mort(agents_dir, *, kind: str, parent: str = "", **extra) -> None:
    """Sème un ticket OUVERT dont l'unique run (agent 'sub-1') est mort en vol."""
    _ticket_avec_runs([{"agent_id": "sub-1", "kind": kind, "verdict": None}], parent, **extra)
    _agent_mort(agents_dir, "sub-1")


def _refuse_toute_reprise(agent_id: str, prompt: str) -> str:
    raise AssertionError(f"reprise INTERDITE, pourtant tentée sur {agent_id}")


def _run_persiste() -> dict:
    return tickets.get_ticket("proj", "T1")["runs"][0]


def _commentaires() -> list[str]:
    return [c["text"] for c in tickets.get_ticket("proj", "T1")["comments"]]


def test_un_sous_agent_crashe_est_repris_automatiquement(agents):
    """Un validateur mort sur un ticket encore ouvert repart seul, et le ticket le dit."""
    _ticket_avec_run_mort(agents, kind="validate_tests")
    reprises = []

    def reprend(agent_id: str, prompt: str) -> str:
        reprises.append((agent_id, prompt))
        return "new-1"

    attempts = auto_resume.resume_subagents(resume_fn=reprend)

    assert reprises == [("sub-1", auto_resume.DEFAULT_RESUME_PROMPT)]
    assert [(a["agent_id"], a["kind"], a["ok"]) for a in attempts] == [
        ("sub-1", "validate_tests", True)]
    assert _run_persiste()["auto_resumed"]  # flag PERSISTANT posé sur le run
    assert "reprise automatique" in _commentaires()[0]


def test_un_work_dispatche_par_un_manager_est_un_sous_agent_repris(agents):
    """Un run 'work' dont le ticket a été dispatché par un manager est de la machinerie :
    il repart seul, contrairement au même run lancé par l'utilisateur."""
    _ticket_avec_run_mort(agents, kind="work", parent="mgr-42")

    attempts = auto_resume.resume_subagents(resume_fn=lambda agent_id, prompt: "new-1")

    assert [a["ok"] for a in attempts] == [True]


@pytest.mark.parametrize("parent", ["", "dispatcher:manual"])
def test_un_meta_agent_n_est_jamais_repris(agents, parent):
    """Un run 'work' issu d'une demande UTILISATEUR attend une relance MANUELLE
    (bandeau /api/interrupted) : la reprise auto ne le touche pas, même crashé."""
    _ticket_avec_run_mort(agents, kind="work", parent=parent)

    attempts = auto_resume.resume_subagents(resume_fn=_refuse_toute_reprise)

    assert attempts == []
    assert "auto_resumed" not in _run_persiste()
    assert _commentaires() == []


def test_le_flag_persistant_empeche_une_seconde_tentative_au_boot_suivant(agents):
    """Deux boots d'affilée ne relancent le même sous-agent qu'UNE fois."""
    _ticket_avec_run_mort(agents, kind="merge")
    appels = []

    def reprend(agent_id: str, prompt: str) -> str:
        appels.append(agent_id)
        return "new-1"

    premier = auto_resume.resume_subagents(resume_fn=reprend)
    second = auto_resume.resume_subagents(resume_fn=reprend)  # boot suivant

    assert appels == ["sub-1"]
    assert (len(premier), len(second)) == (1, 0)
    assert len(_commentaires()) == 1  # une seule trace, pas une par boot


def test_un_ticket_reape_est_refuse_avec_la_raison_tracee(agents):
    """Un ticket mergé/reapé a vu son worktree nettoyé : le relancer ferait renaître
    l'agent dans un dossier fantôme. La reprise est REFUSÉE, sans appeler la relance,
    et la raison est écrite sur le run (ce qui le fait réapparaître dans le bandeau)."""
    _ticket_avec_run_mort(agents, kind="validate_tests", reaped=True)

    attempts = auto_resume.resume_subagents(resume_fn=_refuse_toute_reprise)

    assert [a["ok"] for a in attempts] == [False]
    assert "mergé/reapé" in attempts[0]["error"]
    assert "mergé/reapé" in _run_persiste()["auto_resume_error"]
    assert _run_persiste()["auto_resumed"]  # jamais retenté au boot suivant non plus
    assert "REFUSÉE" in _commentaires()[0]


def test_un_echec_de_reprise_est_trace_sur_le_run(agents):
    """Quand la relance échoue, la raison est posée sur le run : c'est `auto_resume_error`
    qui fait RESSORTIR le sous-agent dans le bandeau des interrompus."""
    _ticket_avec_run_mort(agents, kind="validate_tests")

    def echoue(agent_id: str, prompt: str) -> None:
        raise RuntimeError("worktree introuvable")

    attempts = auto_resume.resume_subagents(resume_fn=echoue)

    assert [a["ok"] for a in attempts] == [False]
    assert "worktree introuvable" in _run_persiste()["auto_resume_error"]


def test_la_reprise_ne_reecrase_pas_une_ecriture_concurrente(agents):
    """Pendant la reprise, un autre écrivain commente le ticket : son commentaire SURVIT.

    La reprise persiste run par run via `_mutate` (relecture de la version fraîche), et non
    en réécrivant l'instantané chargé au début du boot — c'est le lost-update du 2026-07-27."""
    _ticket_avec_run_mort(agents, kind="validate_tests")

    def reprend_pendant_qu_un_tiers_ecrit(agent_id: str, prompt: str) -> str:
        tickets.add_comment("proj", tickets.get_ticket("proj", "T1"), "écrit par un tiers", False)
        return "new-1"

    auto_resume.resume_subagents(resume_fn=reprend_pendant_qu_un_tiers_ecrit)

    assert "écrit par un tiers" in _commentaires()


def test_un_ticket_termine_n_est_pas_repris(agents):
    """Un ticket done/archivé n'a plus rien à reprendre, même avec un run mort."""
    _ticket_avec_run_mort(agents, kind="validate_tests", done=True)

    assert auto_resume.resume_subagents(resume_fn=_refuse_toute_reprise) == []
