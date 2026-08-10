# [desc] Conversation tests: a Read that misses its symbol or its path still returns the code. [/desc]
"""Un `Read` qui vise le mauvais symbole ou le mauvais chemin ne coûte plus un tour."""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _read_call(file_path: str, symbol: str = "") -> str:
    sym = f'<param name="symbol">{symbol}</param>' if symbol else ""
    return (
        f'<tool_use name="Read" id="r1"><param name="file_path">{file_path}</param>'
        f"{sym}</tool_use>"
    )


def _tool_outputs(result) -> str:
    return "\n".join(
        str(m.get("content", "")) for m in result.messages if m.get("role") == "tool"
    )


def test_read_with_a_wrong_symbol_returns_the_file_instead_of_an_error(tmp_path):
    """Le modèle demande un symbole absent : il reçoit le fichier entier, pas un refus."""
    source = tmp_path / "temp_widget.py"
    source.write_text("def build():\n    return 1\n\n\ndef teardown():\n    return 2\n")

    result = bouzecode(
        ["lis le symbole render"],
        mock_llm=MockLLM([
            f'{METH}\n{_read_call(str(source), symbol="render")}',
            "voilà, j'ai le fichier.",
        ]),
    )

    output = _tool_outputs(result)
    assert "def build" in output and "def teardown" in output, (
        "le fichier entier doit être servi"
    )
    assert "Available symbols: build, teardown" in output
    assert "not found" in output, "l'absence du symbole doit rester dite, pas masquée"


def test_read_of_a_wrong_path_resolves_by_basename(tmp_path, monkeypatch):
    """Le modèle se trompe de dossier : le fichier unique portant ce nom est servi."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "temp_target.py").write_text("MARKER = 'found-by-basename'\n")
    monkeypatch.chdir(tmp_path)

    wrong = str(tmp_path / "elsewhere" / "temp_target.py")
    result = bouzecode(
        ["lis ce fichier"],
        mock_llm=MockLLM([f"{METH}\n{_read_call(wrong)}", "fichier lu."]),
    )

    assert "found-by-basename" in _tool_outputs(result)


def test_an_ambiguous_basename_lists_the_candidates_rather_than_guessing(tmp_path, monkeypatch):
    """Deux fichiers homonymes : on ne devine pas, on montre les deux chemins."""
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "temp_dup.py").write_text(f"WHERE = '{sub}'\n")
    monkeypatch.chdir(tmp_path)

    result = bouzecode(
        ["lis ce fichier"],
        mock_llm=MockLLM([
            f'{METH}\n{_read_call(str(tmp_path / "temp_dup.py"))}',
            "je choisirai le bon chemin.",
        ]),
    )

    output = _tool_outputs(result)
    assert "file not found" in output
    assert "a" in output and "b" in output
    assert "WHERE" not in output, "aucun contenu ne doit être servi quand c'est ambigu"
