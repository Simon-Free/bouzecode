# [desc] Tests export_wire rendering of turns.jsonl payload dumps to markdown with headings and edge cases [/desc]
"""export_wire reads a turns.jsonl payload dump and renders system_blocks +
messages per turn. No LLM/DB: we hand-build a synthetic dump."""
import json
from pathlib import Path

from bouzecode.backend.commands.misc.wire_export import export_wire


def _write_dump(payloads_dir: Path):
    records = [
        {
            "turn": 1,
            "timestamp": 1.0,
            "system_blocks": [
                {"type": "text", "text": "FOCUS SYSTEM PROMPT", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "<tools>...</tools>"},
            ],
            "messages": [
                {"role": "user", "content": "taux occ ouigo"},
                {"role": "assistant", "content": "ok",
                 "tool_calls": [{"id": "q1", "name": "execute_sql", "input": {"sql": "SELECT 1"}}]},
            ],
            "context_state": {"notes": {"methodology": "..."}},
            "token_counts": {"in_tokens": 10, "out_tokens": 5,
                             "cache_read_tokens": 0, "cache_creation_tokens": 0},
            "response": {
                "text": "Je vais exécuter la requête.",
                "thinking": "the param is probably sql",
                "tool_calls": [{"id": "q1", "name": "execute_sql", "input": {"sql": "SELECT 1"}}],
                "stop_reason": "tool_use", "interrupted": False, "partial": False,
                "thinking_overflow": False,
            },
        },
        {
            "turn": 2,
            "timestamp": 2.0,
            "system_blocks": [{"type": "text", "text": "FOCUS SYSTEM PROMPT"}],
            "messages": [
                {"role": "tool", "tool_call_id": "q1", "name": "execute_sql",
                 "content": "Erreur : fournis query ou queries."},
            ],
            "context_state": {"notes": {}},
            "response": {
                "text": "réponse coupée", "thinking": "", "tool_calls": [],
                "stop_reason": None, "interrupted": True, "partial": True,
                "thinking_overflow": False,
            },
        },
    ]
    (payloads_dir / "turns.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8",
    )


def test_export_all_turns(tmp_path):
    _write_dump(tmp_path)
    out, n = export_wire("sess", turn=None,
                         out_path=tmp_path / "wire.md", payloads_dir=tmp_path)
    assert n == 2
    md = Path(out).read_text(encoding="utf-8")
    assert "## TURN 1" in md
    assert "## TURN 2" in md
    assert "### REQUEST 1" in md and "### RESPONSE 1" in md
    assert "FOCUS SYSTEM PROMPT" in md          # system block rendered (request)
    assert "execute_sql" in md and "sql" in md  # the offending tool_call surfaced (response)
    assert "fournis query ou queries" in md     # tool_result rendered (request)
    assert "INTERROMPU" in md                   # turn 2 interruption flagged


def test_export_single_turn(tmp_path):
    _write_dump(tmp_path)
    out, n = export_wire("sess", turn=1,
                         out_path=tmp_path / "wire1.md", payloads_dir=tmp_path)
    assert n == 1
    md = Path(out).read_text(encoding="utf-8")
    assert "## TURN 1" in md
    assert "## TURN 2" not in md


def test_missing_turn_returns_reason(tmp_path):
    _write_dump(tmp_path)
    out, reason = export_wire("sess", turn=99, payloads_dir=tmp_path)
    assert out is None
    assert "99" in reason


def test_no_dump_returns_reason(tmp_path):
    out, reason = export_wire("sess", payloads_dir=tmp_path)
    assert out is None
    assert "aucun dump" in reason
