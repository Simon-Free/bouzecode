"""Un chemin qui n'existe pas n'est pas « aucun résultat ».

Constat sur 70 sessions réelles (poste Windows) : presque chaque session cherchait
`...\\PycharmProjects\\bouzecode` alors que le dépôt vit dans `...\\PycharmProjects\\demo\\bouzecode`.
Grep et Glob répondaient « No matches found » / « No files matched » sur ce chemin INEXISTANT,
et l'agent perdait 2 à 5 tours à reformuler son motif au lieu de corriger son chemin.
"""
from bouzecode.backend.tools.ops.grep_glob import _glob, _grep
from bouzecode.backend.tools.ops.file_ops import _read
from bouzecode.backend.tools.ops.path_hints import missing_path_message


def _arbre(tmp_path):
    """PycharmProjects/demo/bouzecode/src/bouzecode/web_v2/lignes.js, comme sur le poste."""
    web = tmp_path / "PycharmProjects" / "demo" / "bouzecode" / "src" / "bouzecode" / "web_v2"
    web.mkdir(parents=True)
    (web / "lignes.js").write_text("elt('summary', null, \"Ce que l'agent recevra\")\n",
                                   encoding="utf-8")
    (tmp_path / "PycharmProjects" / "bouzecode-claude").mkdir()
    return tmp_path / "PycharmProjects"


def test_grep_sur_un_chemin_inexistant_le_dit_et_propose_le_vrai(tmp_path):
    projets = _arbre(tmp_path)
    faux = projets / "bouzecode" / "src" / "bouzecode" / "web_v2"
    out = _grep("recevra", str(faux))
    assert "chemin inexistant" in out
    assert "No matches found" not in out
    vrai = projets / "demo" / "bouzecode" / "src" / "bouzecode" / "web_v2"
    assert str(vrai) in out


def test_glob_sur_un_chemin_inexistant_le_dit(tmp_path):
    projets = _arbre(tmp_path)
    out = _glob("*.js", str(projets / "bouzecode"))
    assert "chemin inexistant" in out
    assert "No files matched" not in out
    assert str(projets / "demo" / "bouzecode") in out


def test_grep_sur_un_chemin_existant_sans_resultat_reste_un_non_resultat(tmp_path):
    projets = _arbre(tmp_path)
    out = _grep("introuvable_xyz", str(projets / "demo"))
    assert "chemin inexistant" not in out


def test_read_dun_fichier_sous_un_dossier_inexistant_propose_le_vrai_dossier(tmp_path, monkeypatch):
    projets = _arbre(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ailleurs").mkdir()
    monkeypatch.chdir(tmp_path / "ailleurs")
    out = _read(str(projets / "bouzecode" / "src" / "bouzecode" / "web_v2" / "absent.js"))
    assert "Error" in out
    assert str(projets / "demo" / "bouzecode") in out


def test_message_propose_aussi_les_voisins_au_nom_proche(tmp_path):
    projets = _arbre(tmp_path)
    msg = missing_path_message(str(projets / "bouzecode-claud"))
    assert "chemin inexistant" in msg
    assert "bouzecode-claude" in msg


def test_message_sans_aucun_candidat_nomme_le_dernier_dossier_existant(tmp_path):
    msg = missing_path_message(str(tmp_path / "zzz_rien" / "qqq"))
    assert "chemin inexistant" in msg
    assert str(tmp_path) in msg
