# [desc] Repli collant : après un refus du principal servi par le repli, les tours suivants partent directement sur le repli, jusqu'à /clear, compaction de la note, changement de modèle ou ressonde. [/desc]
"""Session 4b47c33d (2026-10-08) : claude-opus-5-5 a refusé 15 tours sur 15 à partir du tour
25 ; chaque tour le retentait avant de rejouer sur claude-opus-5 (82 s, 253 k tokens perdus)."""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_harness import bouzecode  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

from bouzecode.backend.agent.repli_collant import RESSONDE_TOUS_LES_N_TOURS, repli_a_servir  # noqa: E402
from bouzecode.backend.agent.state import AgentState  # noqa: E402
from bouzecode.backend.commands.core.basic import cmd_clear  # noqa: E402
from bouzecode.backend.core.payload_view import read_records  # noqa: E402

PRODUCTIF = ('<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
             '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>')
REFUSE = ("", "content_filter")
OPUS_5_5 = {"model": "claude-opus-5-5", "gateway_preprod_api_key": "cle-de-test"}


@pytest.fixture(autouse=True)
def _dossiers_du_test(monkeypatch, tmp_path):
    """Dumps turns.jsonl et session enregistrée par /clear : sous tmp_path, jamais le HOME."""
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("bouzecode.backend.core.config.DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr("bouzecode.backend.core.config.SESSION_HIST_FILE", tmp_path / "history.json")


def _modeles(mock: MockLLM) -> list[str]:
    return [appel["model"] for appel in mock.recorded_calls]


def _vider(state, config) -> None:
    cmd_clear("", state, config)


def test_le_tour_suivant_un_repli_ne_retente_pas_le_principal_jusqu_au_clear(capsys):
    mock = MockLLM([REFUSE, PRODUCTIF, "Fini.", "Bonjour."])

    result = bouzecode(["fais le travail", _vider, "salut"], mock_llm=mock, mock_tools=True,
                  config_overrides=dict(OPUS_5_5))

    # Tour 1 : refus + rejeu ; tour 2 : directement le repli ; après /clear : le principal.
    assert _modeles(mock) == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5",
                              "claude-opus-5-5"]
    assert not result.state.repli_collant
    assert "la suite de la session passe sur claude-sonnet-5-5" in capsys.readouterr().err


def test_le_tour_colle_est_marque_dans_le_journal(tmp_path):
    session_id = f"colle{uuid.uuid4().hex[:8]}"
    result = bouzecode(["fais le travail"], mock_llm=MockLLM([REFUSE, PRODUCTIF, "Fini."]),
                  mock_tools=True, config_overrides={**OPUS_5_5, "_session_id": session_id})

    appels = [r["appel"] for r in read_records(session_id, tmp_path / "debug_payloads" / session_id)
              if "token_counts" in r]
    assert [a["model"] for a in appels] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5"]
    assert appels[1].get("repli_apres_refus") and not appels[1].get("repli_collant")
    assert appels[2].get("repli_collant") and not appels[2].get("repli_apres_refus")
    tour_deux = [e for e in result.state.compaction_log
                 if e.get("event") == "llm_call" and e.get("turn") == 2]
    assert tour_deux[0]["model"] == "claude-sonnet-5-5"
    assert any(e.get("event") == "repli_collant_arme" for e in result.state.compaction_log)


def test_un_refus_du_repli_colle_glisse_sur_la_marche_suivante_sans_retenter_le_principal():
    """Tour 2 servi par sonnet-5-5 colle, qui refuse : opus-5-5 n'est pas retente, le tour
    est rejoue sur claude-opus-5, ou le collage se deplace."""
    mock = MockLLM([REFUSE, PRODUCTIF, REFUSE, PRODUCTIF, "Fini."])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                  config_overrides={**OPUS_5_5, "anthropic_api_key": "cle-de-test"})

    assert _modeles(mock) == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5",
                              "claude-opus-5", "claude-opus-5"]
    assert result.state.close_reason != "content_refusal"
    assert result.state.repli_collant["repli"] == "claude-opus-5"


def _etat_colle() -> AgentState:
    state = AgentState(turn_count=5)
    state.repli_collant.update({"principal": "claude-opus-5-5", "repli": "claude-sonnet-5-5",
                                "depuis_tour": 5, "allegements": 0})
    return state


def test_le_collage_tient_tant_que_rien_ne_change():
    state = _etat_colle()
    state.turn_count = 5 + RESSONDE_TOUS_LES_N_TOURS - 1
    assert repli_a_servir(state, {"model": "claude-opus-5-5"}) == "claude-sonnet-5-5"


def test_un_changement_de_modele_leve_le_collage():
    state = _etat_colle()
    assert repli_a_servir(state, {"model": "claude-opus-4-8"}) is None
    assert not state.repli_collant
    assert state.compaction_log[-1]["raison"] == "changement de modele"


def test_une_compaction_de_la_note_leve_le_collage():
    state = _etat_colle()
    state.context_state.allegements += 1
    assert repli_a_servir(state, {"model": "claude-opus-5-5"}) is None
    assert state.compaction_log[-1]["raison"] == "contexte allege"


def test_le_principal_est_ressonde_au_bout_de_n_tours():
    state = _etat_colle()
    state.turn_count = 5 + RESSONDE_TOUS_LES_N_TOURS
    assert repli_a_servir(state, {"model": "claude-opus-5-5"}) is None
    assert not state.repli_collant


def test_la_compaction_de_la_note_compte_un_allegement(monkeypatch):
    from bouzecode.backend.context_manager import compact_methodology
    from bouzecode.backend.context_manager.state import ContextState
    monkeypatch.setattr(compact_methodology, "should_compact", lambda *a: True)
    monkeypatch.setattr(compact_methodology, "_passes", lambda text, *a, **k: text[:10])
    context_state = ContextState(notes={"methodology": "x" * 100})

    assert compact_methodology.maybe_compact(context_state, "methodology", {}) == 90
    assert context_state.allegements == 1
