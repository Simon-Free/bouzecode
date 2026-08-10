"""Le profil du run est ÉCRIT dans le fichier de session (attribution non heuristique).

Sans ce champ, toute analyse « quel profil batche mal » devait deviner l'origine d'une
session à partir de son prompt. On persiste donc `profile` (profil effectif du run) et
`run_kind` (work / validation / merge : deux runs `coder` n'ont pas le même métier).

Ajout ADDITIF : une session écrite AVANT l'existence du champ doit continuer à se
relire (history.json, /resume) et à être scannée par le dashboard de coûts.
Conversations réelles via le harnais + vrais writers de session. Aucun unittest.mock.
"""
from __future__ import annotations

import json

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.session import _build_session_data, save_latest, save_progressive
from bouzecode.backend.commands.session.session_pick import format_session_label, restore_state
from bouzecode.backend.core import config as config_mod
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _run_as(profile: str, monkeypatch, run_kind: str = "work"):
    """Une conversation courte menée sous le profil donné."""
    monkeypatch.setenv("BOUZECODE_RUN_KIND", run_kind)
    return bouzecode(["fais le travail"],
                     mock_llm=MockLLM([METH, "C'est fait."]),
                     config_overrides={"_task_classification_result": profile})


def _redirect_session_dirs(monkeypatch, tmp_path):
    """Aucune écriture dans le vrai ~/.bouzecode pendant les tests."""
    monkeypatch.setattr(config_mod, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(config_mod, "MR_SESSION_DIR", tmp_path / "mr")
    monkeypatch.setattr(config_mod, "SESSION_HIST_FILE", tmp_path / "history.json")


def test_la_session_sauvee_porte_le_profil_du_run(monkeypatch):
    """Un agent lancé sous `coder` produit une session estampillée `coder`."""
    result = _run_as("coder", monkeypatch)
    data = _build_session_data(result.state, session_id="p1")
    assert data["profile"] == "coder"


def test_la_session_distingue_un_validateur_d_un_codeur(monkeypatch):
    """Même profil `coder`, métier différent : le run_kind lève l'ambiguïté."""
    codeur = _build_session_data(_run_as("coder", monkeypatch).state)
    valideur = _build_session_data(_run_as("coder", monkeypatch, run_kind="validation").state)
    assert codeur["run_kind"] == "work"
    assert valideur["run_kind"] == "validation"
    assert codeur["profile"] == valideur["profile"] == "coder"


def test_le_fichier_de_session_sur_disque_contient_le_profil(monkeypatch, tmp_path):
    """Le champ traverse le VRAI writer, pas seulement le dict en mémoire."""
    _redirect_session_dirs(monkeypatch, tmp_path)
    result = _run_as("manager", monkeypatch)
    path = tmp_path / "session.json"

    save_progressive(result.state, {"_session_path": str(path), "model": "opus-test"})

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["profile"] == "manager"
    assert written["run_kind"] == "work"


def test_une_session_ancienne_sans_le_champ_se_relit_toujours():
    """Rétro-compat : un JSON écrit avant l'ajout du champ se restaure sans erreur."""
    ancienne = {
        "session_id": "vieux", "saved_at": "2026-01-01 10:00:00", "model": "opus-old",
        "first_message": "une vieille session", "messages": [{"role": "user", "content": "hi"}],
        "turn_count": 3, "total_input_tokens": 10, "total_output_tokens": 5,
    }
    state = AgentState()
    restore_state(state, ancienne)

    assert state.turn_count == 3
    assert state.profile == ""   # champ absent → défaut, jamais un KeyError
    assert state.run_kind == ""


def test_history_json_melange_anciennes_et_nouvelles_sessions(monkeypatch, tmp_path):
    """history.json contenant une session sans `profile` accepte l'ajout d'une
    session qui en porte un : les deux se relisent."""
    _redirect_session_dirs(monkeypatch, tmp_path)
    hist_file = tmp_path / "history.json"
    hist_file.write_text(json.dumps({
        "total_turns": 3,
        "sessions": [{"session_id": "vieux", "turn_count": 3, "saved_at": "2026-01-01 10:00:00"}],
    }), encoding="utf-8")

    result = _run_as("coder", monkeypatch)
    save_latest("", result.state,
                {"_session_path": str(tmp_path / "s.json"), "model": "opus-test"})

    hist = json.loads(hist_file.read_text(encoding="utf-8"))
    assert len(hist["sessions"]) == 2
    assert "profile" not in hist["sessions"][0]      # ancienne intacte
    assert hist["sessions"][1]["profile"] == "coder"  # nouvelle estampillée


def test_le_selecteur_de_session_affiche_une_ancienne_session(tmp_path):
    """L'étiquette du picker /resume ne dépend pas du nouveau champ."""
    path = tmp_path / "session_101010_vieux.json"
    path.write_text(json.dumps({
        "session_id": "vieux", "saved_at": "2026-01-01 10:00:00",
        "turn_count": 7, "first_message": "une vieille session", "messages": [],
    }), encoding="utf-8")

    label = format_session_label(path)
    assert "vieux" in label and "turns:7" in label
