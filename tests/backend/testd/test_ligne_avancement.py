# [desc] testd : la ligne d'avancement cite le test le plus long en court (fichier::test, ~60 car.) et seulement à partir de 10 s, par paliers [/desc]
"""La ligne d'avancement d'un run par le démon reste courte et ne change pas à chaque seconde."""
from bouzecode.backend.testd.rendu import ligne_avancement

LONG = ("src/bouzecode/web_v2/tests/test_brouillons_de_fusion_archives.py::"
        "test_integrer_la_branche_archive_le_brouillon_qui_la_vise_avec_une_trace")


def _ligne(elapsed_s, node_id=LONG):
    return ligne_avancement({"state": "running", "total": 23, "done": 4, "passed": 4, "failed": 0,
                             "skipped": 0, "workers": 2,
                             "longest": {"id": node_id, "elapsed_s": elapsed_s}})


def test_longest_test_hidden_under_ten_seconds():
    """Un test qui tourne depuis 9 s n'est pas cité : seuls les comptes s'affichent."""
    assert _ligne(9.7) == "pytest: 4/23 , ✅4 ❌0 ⏭0 · -n 2"


def test_longest_test_shows_file_basename_and_name_cut_to_sixty_chars():
    """Le chemin du fichier disparaît, le nom est coupé avec une ellipse."""
    cite = _ligne(12).split(" · le plus long : ", 1)[1]
    nom = cite.rsplit(" (", 1)[0]
    assert nom.startswith("test_brouillons_de_fusion_archives.py::test_integrer")
    assert "src/" not in nom and len(nom) == 60 and nom.endswith("…")


def test_short_node_id_kept_whole_even_with_windows_separators():
    assert "le plus long : test_x.py::test_y (10 s)" in _ligne(10, r"tests\ui\test_x.py::test_y")


def test_elapsed_time_moves_in_coarse_steps():
    """10 s, 20 s, 30 s… puis 1 min, 2 min : 12 s et 19 s donnent la même ligne."""
    assert _ligne(12) == _ligne(19.9)
    assert "(10 s)" in _ligne(12) and "(20 s)" in _ligne(20) and "(50 s)" in _ligne(59)
    assert "(1 min)" in _ligne(61) and "(1 min)" in _ligne(119) and "(2 min)" in _ligne(125)
