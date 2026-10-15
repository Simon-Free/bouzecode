# [desc] Garde statique d'étanchéité des tests : pas de sleep nu dans un test, pas de port fixe, pas de dossier temporaire partagé (gettempdir) hors liste justifiée. [/desc]
"""Trois fuites d'étanchéité se voient dans le source des tests (cf. TEST_METHODOLOGY.md,
« Tests étanches »). Lecture AST de `tests/` et `src/bouzecode/web_v2/tests/` : ~2 s.

- `sleep` posé directement dans un `test_*`, hors boucle : une attente de durée, qui passe ou
  casse selon la charge. Une boucle qui sonde un état sous une limite est une attente bornée
  (autorisée) ; un `sleep` dans une fonction imbriquée simule une lenteur (autorisé).
- Port fixe : `bind`/`make_server`/`HTTPServer`/`app.run`… sur un entier non nul.
  Deux workers xdist (ou deux worktrees) se le disputent : port 0, puis lire le port attribué.
- `tempfile.gettempdir()` : un dossier commun à tous les processus de la machine. Utiliser
  tmp_path ; les exceptions ci-dessous sont justifiées une par une.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ARBRES = (RACINE / "tests", RACINE / "src" / "bouzecode" / "web_v2" / "tests")

#  Cibles de RunPythonTest : leur sommeil de 30 s EST l'objet du test qui les lance.
SLEEP_AUTORISES = {"tests/test_trivial_runner_slow.py", "tests/backend/tools/runner/test_trivial_runner_slow.py"}
GETTEMPDIR_AUTORISES = {
    #  Le produit traite À PART les extraits sous le tmp système : le fichier (mkstemp, unique)
    #  doit y être, c'est le comportement testé.
    "tests/backend/compaction/test_extraits_traites_mecaniquement.py",
    #  Chemin absent, jamais écrit : lu seulement pour provoquer « file not found ».
    "tests/backend/methodology/snippet/test_snippet_symbol.py",
    #  Le plugin qui FABRIQUE les HOME jetables de chaque process pytest (avant tout tmp_path) :
    #  un sous-dossier stable `bz-homes` du tmp machine. (Le verrou de runner/conftest.py, ancien
    #  occupant de cette liste, a été retiré au profit de pytest imbriqués étanches.)
    "src/bouzecode/web_v2/tests/pytest_home_etanche.py",
    #  Le LANCEUR du bac à sable (pas un test) : son HOME isolé par défaut est `<tmp>/bz-sandbox`,
    #  comme `tests/sandbox/run_sandbox.sh` (surchargé par BZ_SANDBOX_HOME).
    "tests/sandbox/run_sandbox.py",
}
_SERVEURS = {"bind", "make_server", "HTTPServer", "ThreadingHTTPServer", "TCPServer",
             "ThreadingTCPServer", "create_server"}
_LANCEURS = {"run", "serve"}  # app.run(port=…) : seul le mot-clé `port` compte


@functools.cache
def _sources() -> tuple:
    return tuple((fichier.relative_to(RACINE).as_posix(), ast.parse(fichier.read_text("utf-8")))
                 for arbre in ARBRES for fichier in sorted(arbre.rglob("*.py"))
                 if "node_modules" not in fichier.parts)


def _nom(appel: ast.Call) -> str:
    f = appel.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _sleeps_nus(noeud, dans_une_boucle=False):
    """Appels `sleep` du corps propre de `noeud` (fonctions imbriquées exclues) hors boucle."""
    for enfant in ast.iter_child_nodes(noeud):
        if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        boucle = dans_une_boucle or isinstance(enfant, (ast.For, ast.While, ast.AsyncFor))
        if isinstance(enfant, ast.Call) and _nom(enfant) == "sleep" and not boucle:
            yield enfant.lineno
        yield from _sleeps_nus(enfant, boucle)


def _entiers(noeud) -> list[int]:
    return [n.value for n in ast.walk(noeud) if isinstance(n, ast.Constant)
            and type(n.value) is int and n.value > 0]


def _port_fixe(appel: ast.Call) -> bool:
    """Seuls les appels qui OUVRENT un port comptent (`plan_restart(port=5056)` ne lie rien)."""
    nom = _nom(appel)
    if nom in _SERVEURS and any(_entiers(a) for a in appel.args[:2]):
        return True
    return nom in _SERVEURS | _LANCEURS and any(k.arg == "port" and _entiers(k.value)
                                                for k in appel.keywords)


def _appels(arbre):
    return (n for n in ast.walk(arbre) if isinstance(n, ast.Call))


def test_aucun_test_n_attend_une_duree_fixe():
    """Un test attend un état observable (boucle bornée, Event, join) : jamais un sleep nu."""
    fautes = [f"{chemin}:{ligne} ({fn.name})"
              for chemin, arbre in _sources() if chemin not in SLEEP_AUTORISES
              for fn in ast.walk(arbre)
              if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name.startswith("test_")
              for ligne in _sleeps_nus(fn)]
    assert not fautes, "sleep nu dans un test (attendre l'état, pas une durée) :\n" + "\n".join(fautes)


def test_aucun_test_n_ecoute_sur_un_port_fixe():
    """Un serveur de test écoute sur le port 0 et lit le port attribué."""
    fautes = [f"{chemin}:{appel.lineno}" for chemin, arbre in _sources()
              for appel in _appels(arbre) if _port_fixe(appel)]
    assert not fautes, "port fixe dans un test (utiliser le port 0) :\n" + "\n".join(fautes)


def test_aucun_test_ne_partage_le_tmp_systeme_sans_raison():
    """Les fichiers d'un test vivent dans tmp_path, pas dans le tmp commun à la machine."""
    fautes = [f"{chemin}:{appel.lineno}" for chemin, arbre in _sources()
              if chemin not in GETTEMPDIR_AUTORISES
              for appel in _appels(arbre) if _nom(appel) == "gettempdir"]
    assert not fautes, "gettempdir() dans un test (utiliser tmp_path) :\n" + "\n".join(fautes)


def test_le_garde_voit_un_sleep_nu_et_un_port_fixe():
    """Contrôle négatif : les détecteurs de sleep nu et de port fixe se déclenchent."""
    arbre = ast.parse("def test_x():\n    time.sleep(1)\n    s.bind(('127.0.0.1', 5056))\n"
                      "    for _ in r:\n        time.sleep(0.1)\n    app.run(port=8080)\n")
    fn = arbre.body[0]
    assert list(_sleeps_nus(fn)) == [2]
    assert [a.lineno for a in _appels(arbre) if _port_fixe(a)] == [3, 6]
    assert not _port_fixe(ast.parse("s.bind(('127.0.0.1', 0))").body[0].value)
