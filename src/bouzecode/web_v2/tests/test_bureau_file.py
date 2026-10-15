"""bureau.md : la machine n'édite jamais une ligne humaine, et cède en cas de conflit.

C'est la RÈGLE D'OR du fichier. Ces tests écrivent un vrai fichier dans tmp_path — aucun
mock : la seule chose déplacée est le dossier du fichier.
"""
import pytest

from bouzecode.web_v2.services.work import bureau_file


@pytest.fixture(autouse=True)
def _bureau_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(bureau_file, "BUREAU_DIR", tmp_path / "bureau")


def _write(text: str) -> None:
    path = bureau_file.bureau_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SOURCE = """# En cours
- migrer l'ingestion demo_table vers le nouveau schéma
  > relance-le avec l'objection sur le COALESCE
- relire la note de Yann sur les JX [#7c02]

# Un jour
- refaire le décodeur TRAF
"""


def test_unanchored_ne_propose_que_les_lignes_sans_ancre():
    _write(SOURCE)

    assert bureau_file.unanchored(bureau_file.read_text()) == [
        "migrer l'ingestion demo_table vers le nouveau schéma",
        "refaire le décodeur TRAF",
    ]


def test_le_bloc_machine_n_est_jamais_reproposé_comme_ligne_humaine():
    _write(SOURCE)
    before = bureau_file.read_text()
    assert bureau_file.apply({}, ["7c02  à relire   livré il y a 2 h"], before)

    assert bureau_file.unanchored(bureau_file.read_text()) == [
        "migrer l'ingestion demo_table vers le nouveau schéma",
        "refaire le décodeur TRAF",
    ]


def test_ancrer_ajoute_l_id_sans_toucher_au_texte_humain():
    _write(SOURCE)
    before = bureau_file.read_text()

    assert bureau_file.apply({"refaire le décodeur TRAF": "3b1e"}, ["3b1e  à faire"], before)

    text = bureau_file.read_text()
    assert "- refaire le décodeur TRAF [#3b1e]" in text
    # Chaque ligne humaine d'origine est encore là, mot pour mot (à l'ancre près).
    for line in ["# En cours", "  > relance-le avec l'objection sur le COALESCE",
                 "- relire la note de Yann sur les JX [#7c02]", "# Un jour"]:
        assert line in text
    assert bureau_file.MARK_BEGIN in text and bureau_file.MARK_END in text


def test_le_bloc_machine_est_remplacé_et_non_empilé():
    _write(SOURCE)
    assert bureau_file.apply({}, ["vieux"], bureau_file.read_text())
    assert bureau_file.apply({}, ["neuf"], bureau_file.read_text())

    text = bureau_file.read_text()
    assert text.count(bureau_file.MARK_BEGIN) == 1
    assert "vieux" not in text and "neuf" in text


def test_fichier_modifié_pendant_la_préparation_abandonne_l_écriture():
    _write(SOURCE)
    lu_au_début = bureau_file.read_text()
    # L'humain tape une ligne pendant que la machine préparait son écriture.
    _write(SOURCE + "- une idée tapée entre-temps\n")
    entre_temps = bureau_file.read_text()

    abandonné = bureau_file.apply({"refaire le décodeur TRAF": "3b1e"}, ["3b1e  à faire"],
                                  lu_au_début)

    assert abandonné is False
    assert bureau_file.read_text() == entre_temps
    assert bureau_file.MARK_BEGIN not in bureau_file.read_text()


def test_premier_import_sur_un_fichier_absent():
    assert bureau_file.read_text() == ""

    assert bureau_file.apply({}, ["3b1e  à faire"], "")

    assert bureau_file.read_text() == bureau_file.render_block(["3b1e  à faire"])
