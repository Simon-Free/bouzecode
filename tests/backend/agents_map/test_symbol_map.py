# [desc] The map cache: fresh serves free, a stale folder is patched, and the two artefacts stay decoupled. [/desc]
"""Une carte fraîche est servie sans appel LLM ; une carte périmée est corrigée, pas réécrite."""
from __future__ import annotations

from bouzecode.backend.tools.agents_map import manifest, regen, serve
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def _tool_output(result, name: str) -> str:
    msgs = [m for m in result.messages if m.get("role") == "tool" and m.get("name") == name]
    assert msgs, f"aucun résultat {name} dans la conversation"
    return str(msgs[0]["content"])


def test_the_model_can_call_symbol_map_and_receives_the_folder_map(
    pkg, tmp_path, fresh_map, monkeypatch,
):
    """La raison d'être du câblage : le modèle émet `SymbolMap(path=…)` et reçoit la carte.
    Tant que l'outil n'était pas enregistré, le même appel revenait « outil indisponible »."""
    monkeypatch.setenv("BOUZECODE_AGENTS_MAP_MODEL", "test-model")
    monkeypatch.chdir(tmp_path)
    fresh_map(pkg, "test-model")

    call = f'<tool_use name="SymbolMap" id="sm1"><param name="path">{pkg}</param></tool_use>'
    result = bouzecode(["oriente-toi dans pkg"], mock_llm=MockLLM([f"{METH}\n{call}", "vu."]))

    out = _tool_output(result, "SymbolMap")
    assert out.startswith("# pkg/"), f"la carte doit être servie, reçu : {out[:120]!r}"
    assert "| `alpha.py` | 2 |" in out, "le Module Reference arrive avec ses vraies tailles"
    assert "symbols_map:" not in out, "le frontmatter est de la machinerie, pas du contenu"


def test_symbol_map_given_a_file_maps_the_folder_that_holds_it(
    pkg, tmp_path, fresh_map, monkeypatch,
):
    """Le modèle nomme le fichier qui l'intéresse : on ne le renvoie pas corriger sa saisie,
    on lui donne la carte du dossier — c'est la réponse qu'il cherchait."""
    monkeypatch.setenv("BOUZECODE_AGENTS_MAP_MODEL", "test-model")
    monkeypatch.chdir(tmp_path)
    fresh_map(pkg, "test-model")

    target = pkg / "alpha.py"
    call = f'<tool_use name="SymbolMap" id="sm1"><param name="path">{target}</param></tool_use>'
    result = bouzecode(["oriente-toi"], mock_llm=MockLLM([f"{METH}\n{call}", "vu."]))

    assert _tool_output(result, "SymbolMap").startswith("# pkg/")



def test_a_fresh_map_is_served_without_calling_the_model(pkg, tmp_path, fake_llm, fresh_map):
    """Le hash correspond : on sert le fichier, zéro appel LLM."""
    fresh_map(pkg)
    llm = fake_llm()

    out = serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")

    assert llm.calls == [], "une carte fraîche ne doit rien coûter"
    assert out.startswith("# pkg/")
    assert "symbols_map:" not in out, "le frontmatter est de la machinerie, pas du contenu"


def test_editing_one_file_sends_only_that_file_in_full(pkg, tmp_path, fake_llm, fresh_map):
    """Sémantique de patch : le fichier changé part entier, l'autre juste par son nom."""
    fresh_map(pkg)
    (pkg / "beta.py").write_text("def beta():\n    return 42\n")
    llm = fake_llm()

    serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")

    assert len(llm.calls) == 1, "un seul appel, jamais de cascade"
    sent = llm.calls[0]
    changed = sent.split("## Changed / new files (full content)")[1].split("## Unchanged")[0]
    assert "return 42" in changed and "beta.py" in changed
    assert "alpha.py" not in changed, "le fichier inchangé ne doit pas repartir en entier"
    assert "alpha.py" in sent.split("## Unchanged files")[1].split("##")[0]


def test_a_regeneration_writes_the_new_hashes_so_the_next_read_is_free(pkg, tmp_path, fake_llm, fresh_map):
    """Après régénération la carte est fraîche : la lecture suivante ne rappelle pas."""
    fresh_map(pkg)
    (pkg / "beta.py").write_text("def beta():\n    return 42\n")
    llm = fake_llm()

    serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")
    serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")

    assert len(llm.calls) == 1


def test_deep_code_changes_never_invalidate_the_root_map(pkg, tmp_path, fake_llm, fresh_map):
    """Le découplage : modifier un fichier au fond de l'arbre ne périme pas la racine."""
    root_doc = tmp_path / manifest.AGENTS_DOC
    root_doc.write_text(
        regen.compose("# repo/\n\nRacine.\n\n## Folders\n\n| Folder | Purpose |\n|---|---|\n",
                      regen.agents_manifest(tmp_path, "test-model")),
        encoding="utf-8",
    )
    (pkg / "beta.py").write_text("def beta():\n    return 999\n")
    llm = fake_llm()

    serve.agents_map(tmp_path, client=llm, model="test-model")

    assert llm.calls == [], "un changement de code ne touche jamais la carte de structure"


def test_adding_a_folder_never_invalidates_a_neighbours_symbol_map(pkg, tmp_path, fake_llm, fresh_map):
    """Le découplage dans l'autre sens : un dossier qui apparaît ne périme aucun SYMBOLS.md."""
    fresh_map(pkg)
    newcomer = tmp_path / "other"
    newcomer.mkdir()
    (newcomer / "gamma.py").write_text("def gamma():\n    return 0\n")
    llm = fake_llm()

    serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")

    assert llm.calls == []


