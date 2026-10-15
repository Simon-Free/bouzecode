"""Repli de modele sur refus : un tour refuse (content_filter) est rejoue sur la marche
suivante de la chaine de repli (test_chaine_de_repli.py), qui sert ensuite les tours
suivants (repli collant, test_repli_collant.py).

Mesure a l'origine (2026-10-06, session b2feb0ff, payload exact rejoue) : claude-opus-5-5
12/12 refus, claude-opus-5 0/6. Un refus est deterministe pour un modele, pas pour tous.
Remesure 2026-10-08 (session 4b47c33d, tour 25, 12 rejeux) : opus-5-5 2 a 9/12,
sonnet-5-5 0/12, opus-5 0/12 -> opus-5-5 se replie sur sonnet-5-5.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_harness import bouzecode  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

PRODUCTIVE_TURN = (
    '<tool_use name="Methodology" id="m1"><param name="content">j\'avance</param></tool_use>'
    '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
)
REFUSED = ("", "content_filter")
# Une cle factice : le repli n'est retenu que si son fournisseur a une cle.
OPUS_5_5 = {"model": "claude-opus-5-5", "gateway_preprod_api_key": "cle-de-test"}


@pytest.fixture(autouse=True)
def _dumps_sous_tmp_path(monkeypatch, tmp_path):
    """Les dumps turns.jsonl de chaque appel : sous tmp_path, jamais le HOME du worker."""
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", tmp_path)


def _models(mock: MockLLM) -> list[str]:
    return [call["model"] for call in mock.recorded_calls]


def test_un_refus_est_rejoue_une_fois_avec_le_modele_de_repli(capsys):
    mock = MockLLM([REFUSED, PRODUCTIVE_TURN, "Travail termine."])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides=dict(OPUS_5_5))

    assert _models(mock)[:3] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5"]
    # Meme tour rejoue : meme historique et meme system envoyes au repli.
    refused_call, fallback_call = mock.recorded_calls[:2]
    assert fallback_call["messages"] == refused_call["messages"]
    assert fallback_call["system"] == refused_call["system"]
    assert result.state.close_reason != "content_refusal"
    # Le resultat du repli est utilise : son appel d'outil a ete execute.
    assert any(m.get("tool_calls") and m["tool_calls"][0]["name"] == "Methodology"
               for m in result.state.messages if m.get("role") == "assistant")
    events = [e for e in result.state.compaction_log if e.get("event") == "refusal_fallback"]
    assert events and events[0]["model"] == "claude-opus-5-5"
    assert events[0]["fallback"] == "claude-sonnet-5-5" and events[0]["fallback_refused"] is False
    # Les deux appels du tour 1 (refuse + repli) sont comptes, le repli sous son modele.
    turn_one = [e for e in result.state.compaction_log
                if e.get("event") == "llm_call" and e.get("turn") == 1]
    assert len(turn_one) == 2 and turn_one[1]["model"] == "claude-sonnet-5-5"
    assert "refus de claude-opus-5-5 (content_filter)" in capsys.readouterr().err


def test_un_refus_du_repli_sans_marche_suivante_ferme_en_content_refusal(monkeypatch):
    """Chaine reduite a une marche (sonnet-5-5) : son refus ferme le run.

    La chaine est fixee explicitement : compter sur l'absence de cle d'opus-5 rendait le
    test dependant du poste (bouzecode relit les cles de l'environnement utilisateur)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock = MockLLM([REFUSED, REFUSED, *([""] * 5)])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides={**OPUS_5_5, "refusal_fallback": "claude-sonnet-5-5"})

    assert result.state.close_reason == "content_refusal"
    assert _models(mock) == ["claude-opus-5-5", "claude-sonnet-5-5"]
    events = [e for e in result.state.compaction_log if e.get("event") == "refusal_fallback"]
    assert events[0]["fallback_refused"] is True


def test_un_refus_de_sonnet_5_5_en_repli_glisse_sur_opus_5_dans_le_meme_tour():
    """Session 28738fd0 : opus-5-5 -> sonnet-5-5 -> claude-opus-5, dans le meme tour."""
    mock = MockLLM([REFUSED, REFUSED, PRODUCTIVE_TURN, "Travail termine."])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                  config_overrides={**OPUS_5_5, "anthropic_api_key": "cle-de-test"})

    assert _models(mock)[:3] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5"]
    assert result.state.close_reason != "content_refusal"
    events = [(e["model"], e["fallback"], e["fallback_refused"])
              for e in result.state.compaction_log if e.get("event") == "refusal_fallback"]
    assert events == [("claude-opus-5-5", "claude-sonnet-5-5", True),
                      ("claude-sonnet-5-5", "claude-opus-5", False)]
    tour_un = [e["model"] for e in result.state.compaction_log
               if e.get("event") == "llm_call" and e.get("turn") == 1]
    assert tour_un == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5"]


def test_sonnet_5_5_principal_se_replie_toujours_sur_opus_5():
    mock = MockLLM([REFUSED, PRODUCTIVE_TURN, "Travail termine."])

    bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
         config_overrides={"model": "claude-sonnet-5-5", "anthropic_api_key": "cle-de-test"})

    assert _models(mock)[:2] == ["claude-sonnet-5-5", "claude-opus-5"]


def test_un_modele_sans_repli_ferme_comme_avant():
    mock = MockLLM([REFUSED, *([""] * 5)])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides={"model": "claude-opus-4-8"})

    assert result.state.close_reason == "content_refusal"
    assert mock.call_count == 1


def test_le_repli_desactive_par_l_environnement(monkeypatch):
    monkeypatch.setenv("BOUZECODE_REFUSAL_FALLBACK", "none")
    mock = MockLLM([REFUSED, *([""] * 5)])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides=dict(OPUS_5_5))

    assert result.state.close_reason == "content_refusal"
    assert mock.call_count == 1


def test_le_repli_choisi_par_l_environnement(monkeypatch):
    monkeypatch.setenv("BOUZECODE_REFUSAL_FALLBACK", "claude-opus-4-8")
    mock = MockLLM([REFUSED, REFUSED, *([""] * 5)])

    # claude-opus-4-8 est servi par le fournisseur anthropic : il lui faut sa cle.
    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                  config_overrides={**OPUS_5_5, "anthropic_api_key": "cle-de-test"})

    assert _models(mock) == ["claude-opus-5-5", "claude-opus-4-8"]
    assert result.state.close_reason == "content_refusal"
