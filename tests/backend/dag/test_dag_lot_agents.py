# [desc] Un lot de plusieurs Agent dans un même message part d'un coup (dispatcher DAG), sans perdre l'ordre vis-à-vis des autres outils séquentiels. [/desc]
"""TODO §4 (2026-09-25) : les sous-agents partaient UN PAR UN.

`Agent` est `concurrent_safe=False` (il écrit : ticket, note Methodology, fenêtre de
terminal) : le dispatcher DAG le rangeait donc avec `Bash`/`Write` dans la file
séquentielle. Un lot de N `Agent` en mode par défaut (le parent attend chaque enfant)
attendait l'enfant 1 avant même de LANCER l'enfant 2 — mesuré : 4 dispatchs à 14:59,
15:11, 15:17, 15:27. On passe ici par le VRAI registre (le drapeau de l'outil est ce
qu'on teste) ; seul `execute_tool` est remplacé par un faux qui note ses horaires.
"""
from __future__ import annotations

import threading
import time

import pytest

import bouzecode.backend.multi_agent.tools  # noqa: F401 — enregistre Agent dans le registre
from bouzecode.backend.agent.dag import _execute_level

_journal: list[dict] = []
_verrou = threading.Lock()


def _faux_execute_tool(tool_name, params, permission_mode=None, _extra=None, config=None):
    debut = time.monotonic()
    time.sleep(0.15)
    with _verrou:
        _journal.append({"id": params["_tc_id"], "debut": debut, "fin": time.monotonic()})
    return f"ok:{tool_name}"


@pytest.fixture(autouse=True)
def _outils_chronometres(monkeypatch):
    monkeypatch.setattr("bouzecode.backend.agent.dag.execute_tool", _faux_execute_tool)
    _journal.clear()
    yield
    _journal.clear()


def _appel(tc_id: str, nom: str) -> dict:
    return {"id": tc_id, "name": nom, "input": {"_tc_id": tc_id, "prompt": "x"}}


def _par_id() -> dict[str, dict]:
    return {e["id"]: e for e in _journal}


def test_un_lot_de_trois_agent_demarre_d_un_coup():
    level = [_appel(f"a{i}", "Agent") for i in range(3)]
    results, durations = {}, {}
    _execute_level(level, results, durations, config={})

    assert set(results) == {"a0", "a1", "a2"}
    journal = _par_id()
    # Tous LANCÉS avant que le premier n'ait fini : aucun n'attend son frère pour partir.
    premiere_fin = min(e["fin"] for e in journal.values())
    assert all(e["debut"] < premiere_fin for e in journal.values()), journal


def test_le_lot_d_agent_garde_sa_place_parmi_les_outils_sequentiels():
    """`git commit` PUIS deux Agent PUIS un Bash : le lot part après le commit (l'enfant
    branche sur l'état commité) et le Bash qui suit attend le lot entier."""
    level = [_appel("b1", "Bash"), _appel("a1", "Agent"), _appel("a2", "Agent"),
             _appel("b2", "Bash")]
    results, durations = {}, {}
    _execute_level(level, results, durations, config={})

    j = _par_id()
    assert j["b1"]["fin"] <= min(j["a1"]["debut"], j["a2"]["debut"])
    assert j["a1"]["debut"] < j["a2"]["fin"] and j["a2"]["debut"] < j["a1"]["fin"]
    assert max(j["a1"]["fin"], j["a2"]["fin"]) <= j["b2"]["debut"]


def test_deux_bash_restent_sequentiels():
    level = [_appel("b1", "Bash"), _appel("b2", "Bash")]
    _execute_level(level, {}, {}, config={})
    j = _par_id()
    assert j["b1"]["fin"] <= j["b2"]["debut"]


def test_interruption_avant_le_lot_ne_lance_aucun_agent():
    appels = {"n": 0}

    def peek():
        appels["n"] += 1
        return appels["n"] > 2  # tête de niveau et départ du Bash passent, la suite est annulée

    level = [_appel("b1", "Bash"), _appel("a1", "Agent"), _appel("a2", "Agent")]
    results, durations = {}, {}
    _execute_level(level, results, durations, config={"_cancel_peek": peek})
    assert set(_par_id()) == {"b1"}
    assert results["a1"].startswith("Cancelled") and results["a2"].startswith("Cancelled")
