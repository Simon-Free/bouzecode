# [desc] turns.jsonl dit chaque appel : son modèle, s'il rejoue un refus avec le modèle de repli ou avec la note compactée (variante), et les tentatives facturées puis écartées avec leurs tokens. [/desc]
"""Session 9d81964e (2026-10-06) : 7 refus content_filter et 3 rejeux par claude-opus-5 étaient
indiscernables dans turns.jsonl — rejeu sous le même numéro de tour, tentatives refusées
fondues dans les compteurs du tour."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_harness import bouzecode  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

from bouzecode.backend.core.payload_view import read_records  # noqa: E402

PRODUCTIF = ('<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
             '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>')


def test_le_rejeu_a_note_compactee_est_marque_dans_le_journal(monkeypatch, tmp_path):
    """Le tour refusé puis rejoué avec la note compactée laisse deux appels au même numéro :
    le refusé, puis le rejeu marqué `variante: note_compactee`."""
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", tmp_path)
    session_id = f"compacte{uuid.uuid4().hex[:8]}"
    bouzecode(["fais le travail"],
         mock_llm=MockLLM([_productif(1), _productif(2), _productif(3), ("", "content_filter"),
                           _productif(4), "Fini."]),
         config_overrides={"model": "claude-opus-5-5", "refusal_fallback": "none",
                           "_session_id": session_id})
    appels = [r["appel"] for r in read_records(session_id, tmp_path / "debug_payloads" / session_id)
              if "token_counts" in r]
    assert [a.get("variante") for a in appels][:5] == [None, None, None, None, "note_compactee"]
    assert all(not a.get("repli_apres_refus") for a in appels)


def _productif(n: int) -> str:
    return (f'<tool_use name="Methodology" id="m{n}"><param name="content">etape {n} du '
            f'travail en cours</param></tool_use>'
            f'<tool_use name="Bash" id="b{n}"><param name="command">echo {n}</param></tool_use>')


def test_le_rejeu_du_repli_est_marque_dans_le_journal(monkeypatch, tmp_path):
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", tmp_path)
    session_id = f"repli{uuid.uuid4().hex[:8]}"
    bouzecode(["fais le travail"], mock_llm=MockLLM([("", "content_filter"), PRODUCTIF, "Fini."]),
              mock_tools=True, config_overrides={"model": "claude-opus-5-5",
                                                 "gateway_preprod_api_key": "cle-de-test",
                                                 "_session_id": session_id})
    appels = [r["appel"] for r in read_records(session_id, tmp_path / "debug_payloads" / session_id)
              if "token_counts" in r]
    assert [a["model"] for a in appels][:3] == ["claude-opus-5-5", "claude-sonnet-5-5",
                                                "claude-sonnet-5-5"]
    assert appels[1].get("repli_apres_refus") is True
    # Le tour 3 est servi par le repli collant, pas par un rejeu après refus.
    assert not appels[0].get("repli_apres_refus") and not appels[2].get("repli_apres_refus")
    assert appels[2].get("repli_collant") is True
