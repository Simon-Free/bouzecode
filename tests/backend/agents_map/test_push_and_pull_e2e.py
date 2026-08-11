# [desc] Conversation test: writing code marks the folder self-authored, so the agent is not billed for its own churn. [/desc]
"""Un agent qui écrit du code n'est pas facturé pour régénérer la carte qu'il vient de périmer."""
from __future__ import annotations

from bouzecode.backend.tools.agents_map import serve
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def test_writing_code_records_the_folder_as_self_authored(tmp_path, monkeypatch):
    """Le hook d'édition (push) n'annonce plus « périmé » — il dit « c'est moi »."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "temp_module.py"

    write = (
        f'<tool_use name="Write" id="w1"><param name="file_path">{target}</param>'
        f'<param name="content">def temp_fn():\n    return 1\n</param></tool_use>'
    )
    bouzecode(["écris ce module"], mock_llm=MockLLM([f"{METH}\n{write}", "écrit."]))

    assert serve._is_self_authored(tmp_path), (
        "le dossier écrit doit être attribué à l'agent courant"
    )


def test_a_non_code_file_never_claims_a_folder(tmp_path, monkeypatch):
    """Écrire un .txt ne concerne aucune carte de symboles."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "temp_notes.txt"

    write = (
        f'<tool_use name="Write" id="w1"><param name="file_path">{target}</param>'
        f'<param name="content">rien de compilable</param></tool_use>'
    )
    bouzecode(["écris ces notes"], mock_llm=MockLLM([f"{METH}\n{write}", "écrit."]))

    assert not serve._is_self_authored(tmp_path)
