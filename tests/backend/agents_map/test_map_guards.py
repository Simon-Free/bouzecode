# [desc] The guards: never write a false map, never bill an agent for its own churn, never pay a regeneration twice. [/desc]
"""Ce qui protège la carte : conformité avant écriture, attribution des écritures, verrou."""
from __future__ import annotations

from bouzecode.backend.tools.agents_map import manifest, serve



def test_a_map_that_breaks_the_contract_is_never_written(pkg, tmp_path, fake_llm, fresh_map):
    """Ne jamais écrire du faux : une sortie non conforme laisse l'ancienne carte en place."""
    fresh_map(pkg)
    (pkg / "beta.py").write_text("def beta():\n    return 42\n")
    before = (pkg / manifest.SYMBOLS_DOC).read_text(encoding="utf-8")

    out = serve.symbol_map(
        pkg, tmp_path, model="test-model",
        client=fake_llm("# pkg/\n\nRésumé.\n\n## Subfolders\n\n| a | b |\n"),
    )

    assert (pkg / manifest.SYMBOLS_DOC).read_text(encoding="utf-8") == before
    assert "stale" in out


def test_a_folder_the_agent_just_edited_is_not_regenerated_on_its_own_churn(pkg, tmp_path, fake_llm, fresh_map):
    """Un agent qui refactore n'est pas facturé pour périmer sa propre carte à chaque Write."""
    fresh_map(pkg)
    (pkg / "beta.py").write_text("def beta():\n    return 42\n")
    serve.mark_self_authored(pkg)
    llm = fake_llm()

    out = serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")

    assert llm.calls == []
    assert "you edited this folder yourself" in out


def test_a_held_lock_serves_the_stale_map_instead_of_paying_twice(pkg, tmp_path, fake_llm, fresh_map):
    """Deux agents, un dossier périmé : le second sert le périmé, il ne rappelle pas le modèle."""
    fresh_map(pkg)
    (pkg / "beta.py").write_text("def beta():\n    return 42\n")
    doc = pkg / manifest.SYMBOLS_DOC
    doc.with_suffix(doc.suffix + ".lock").write_text("held")
    llm = fake_llm()

    out = serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")

    assert llm.calls == []
    assert "another agent is regenerating it" in out


def test_an_invented_call_edge_is_caught_and_the_model_is_told_which_one(
    pkg, tmp_path, fake_llm, fresh_map, bad_nesting_map, good_map,
):
    """Le graphe prétend que beta() appelle alpha() : l'AST le dément, on le renvoie au modèle."""
    fresh_map(pkg)
    (pkg / "beta.py").write_text("def beta():\n    return 42\n")
    llm = fake_llm(bad_nesting_map, good_map)

    out = serve.symbol_map(pkg, tmp_path, client=llm, model="test-model")

    assert len(llm.calls) == 2, f"une seule reprise, jamais une boucle — servi : {out!r}"
    assert "beta() is shown calling alpha()" in llm.calls[1], (
        "la reprise doit citer l'arête exacte que l'AST dément"
    )
    assert "└── beta()" in out, "la seconde sortie, conforme, est celle qui est servie"


def test_a_provider_outage_serves_the_stale_map_rather_than_losing_the_turn(
    pkg, tmp_path, fresh_map,
):
    """La passerelle rend des 503 passagers : une carte est une aide, jamais une raison d'échouer."""
    fresh_map(pkg)
    (pkg / "beta.py").write_text("def beta():\n    return 42\n")

    class Exploding:
        messages = property(lambda self: self)

        def create(self, **kwargs):
            raise RuntimeError("Bedrock is unable to process your request")

    out = serve.symbol_map(pkg, tmp_path, client=Exploding(), model="test-model")

    assert "regeneration failed (RuntimeError)" in out
    assert "# pkg/" in out, "la carte précédente reste servie"


def test_a_folder_with_no_code_gets_no_symbol_map(tmp_path, fake_llm):
    """L'activation est mécanique : pas de fichier de code, pas de SYMBOLS.md."""
    empty = tmp_path / "container"
    (empty / "child").mkdir(parents=True)

    out = serve.symbol_map(empty, tmp_path, client=fake_llm(), model="test-model")

    assert "no SYMBOLS.md by design" in out
    assert not (empty / manifest.SYMBOLS_DOC).exists()


_ROOT_MAP_HEAD = "# repo/\n\nRacine.\n\n## Folders\n\n| Folder | Purpose |\n|---|---|\n"


def _root_map(*folders: str, purpose: str = "Fait des choses.") -> str:
    rows = "".join(f"| [{f}]({f}SYMBOLS.md) | {purpose} |\n" for f in folders)
    return _ROOT_MAP_HEAD + rows


def test_a_root_map_cut_off_mid_row_is_never_written(pkg, tmp_path, fake_llm):
    """Une réponse coupée à `max_tokens` finit au milieu d'une ligne et perd tout ce qui
    suivait, sans le dire. Elle ne doit pas atteindre le disque : elle se lirait comme
    complète, et un lecteur conclurait que les dossiers absents n'existent pas."""
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "gamma.py").write_text("def gamma(): return 0\n")
    truncated = _ROOT_MAP_HEAD + "| [pkg/](pkg/SYM"

    out = serve.agents_map(tmp_path, client=fake_llm(truncated), model="test-model")

    assert not (tmp_path / manifest.AGENTS_DOC).exists(), "rien de tronqué sur le disque"
    assert "ends mid-row" in out


def test_a_root_map_missing_folders_is_sent_back_with_the_ones_it_forgot(pkg, tmp_path, fake_llm):
    """Le modèle oublie un dossier : on le lui nomme, et la reprise conforme est servie."""
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "gamma.py").write_text("def gamma(): return 0\n")
    llm = fake_llm(_root_map("pkg/"), _root_map("other/", "pkg/"))

    out = serve.agents_map(tmp_path, client=llm, model="test-model")

    assert len(llm.calls) == 2, "une seule reprise, jamais une boucle"
    assert "other/" in llm.calls[1], "la reprise doit nommer le dossier manquant"
    assert "other/" in out and "pkg/" in out
    assert (tmp_path / manifest.AGENTS_DOC).exists()


def test_a_root_map_that_writes_paragraphs_instead_of_a_sentence_is_sent_back(
    pkg, tmp_path, fake_llm,
):
    """La carte racine se lit une fois par session : une colonne Purpose qui déborde
    systématiquement du plafond la fait payer 3× son budget. Une ligne longue passe,
    la verbosité systématique non."""
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "gamma.py").write_text("def gamma(): return 0\n")
    bavard = "Ce dossier " + "fait beaucoup de choses très intéressantes, " * 5
    llm = fake_llm(_root_map("other/", "pkg/", purpose=bavard), _root_map("other/", "pkg/"))

    out = serve.agents_map(tmp_path, client=llm, model="test-model")

    assert len(llm.calls) == 2
    assert "exceed the 110-character cap" in llm.calls[1]
    assert bavard not in out, "la version conforme est celle qui est servie"
