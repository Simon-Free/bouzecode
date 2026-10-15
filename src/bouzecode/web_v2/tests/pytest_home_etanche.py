# [desc] Plugin pytest : HOME jetable par worker xdist et par test ; échec de tout test qui écrit dans le VRAI HOME, le HOME partagé du worker ou le dépôt, chemin nommé. [/desc]
"""Aucun test n'écrit dans le vrai HOME.

1. Redirection, AU CHARGEMENT du plugin (`-p` en tête d'`addopts`, donc avant tout conftest et
   tout import de `bouzecode`) : HOME, USERPROFILE et XDG_{CONFIG,CACHE,DATA,STATE}_HOME pointent
   sur un dossier jetable propre au processus (`bz-homes/bz-home-<worker>-*` sous le tmp système). Toutes
   les constantes figées à l'import (`CONFIG_DIR`, `AGENTS_DIR`, `TICKETS_DIR`, `~/.local/bin`…)
   naissent donc hors du vrai HOME, et les sous-processus (agents, CLI, git) héritent du faux.
   Le vrai HOME est transmis aux workers et aux pytest imbriqués par `BZ_TESTS_VRAI_HOME`.
   Filet quand le plugin n'est PAS chargé (`-o addopts=""` sans conftest racine, `--noconftest`,
   test hors du dépôt, `pytest.main()` d'un script) : `bouzecode/__init__.py` importe ce module
   dès que `_pytest` est chargé — la redirection a lieu, le rapport des hooks non (fuites du
   2026-10-06 : `remote/executions`, `web_v2/projects.json`). Second verrou côté code :
   `backend.core.garde_vrai_home` (registre des projets, store des tickets, registre distant).
   Exceptions légitimes, lues dans le vrai HOME : navigateurs Playwright, instantanés du bac.
   En plus, chaque TEST reçoit son propre HOME (fixture autouse `_home_du_test`) pour ce qui
   relit `Path.home()` à l'appel ; les chemins figés à l'import sont redirigés test par test
   par `production_isolation.isoler_les_fichiers_du_home`.

2. Détection, par un hook d'audit Python (`sys.addaudithook`) : chaque `open` en écriture,
   `mkdir`, `rename`, `remove`, `rmdir`, `symlink`, `utime`, `chmod`, `copyfile`, `rmtree`,
   `sqlite3.connect` et chaque sous-processus lancé avec le vrai HOME est comparé au vrai HOME
   et, pendant un test, au HOME du worker et au dépôt (partagés : y écrire fuit d'un test à
   l'autre, ou d'un worker à l'autre).
   Coût : une comparaison de préfixe par appel. Fiable : l'événement est levé par CPython
   lui-même, quel que soit le code qui écrit ; il nomme le chemin et le test en cours. Un test
   fautif ÉCHOUE (rapport de la phase converti) ; une écriture hors test fait échouer la session.
   L'écriture n'est PAS bloquée : bloquer ferait échouer ailleurs, sur un chemin moins lisible.

   Surveillé : tout fichier posé à la racine du HOME et tout ce qui vit sous un dossier caché
   (`~/.bouzecode`, `~/.local`, `~/.cache`, `~/.config`…). Les dépôts (`~/bouzecode-wt-*`) et
   leur venv sont hors champ : ce sont les tests eux-mêmes. Le dépôt testé l'est aussi quand il
   vit sous un dossier caché (worktrees d'agents dans `~/.bouzecode/worktrees`).

Pourquoi pas un instantané avant/après des mtime : sur ce poste, d'autres suites et de vrais
serveurs écrivent dans `~/.bouzecode` pendant le run. Un instantané y verrait leurs écritures
et échouerait au hasard — l'inverse d'un test étanche. Le hook ne voit que CE processus.
"""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import atexit
import importlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

VAR_VRAI_HOME = "BZ_TESTS_VRAI_HOME"
#  Relatifs au vrai HOME : lus (et éventuellement écrits) légitimement pendant les tests.
#  .bouzecode/testd : sortie de l'outillage de lancement des tests (événements, issues).
EXCLUS = (".cache/bz-sandbox", ".cache/ms-playwright", ".bouzecode/testd")
_ECRITURE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
#  Événement d'audit → positions des arguments qui sont des chemins écrits.
_CHEMINS = {
    "os.mkdir": (0,), "os.rename": (0, 1), "os.remove": (0,), "os.rmdir": (0,),
    "os.symlink": (1,), "os.link": (1,), "os.truncate": (0,), "os.chmod": (0,),
    "os.utime": (0,), "shutil.copyfile": (1,), "shutil.copytree": (1,),
    "shutil.rmtree": (0,), "shutil.move": (1,), "sqlite3.connect": (0,),
}
_EVENEMENTS = frozenset(_CHEMINS) | {"open", "subprocess.Popen"}


def _vrai_home() -> str:
    return os.path.realpath(os.environ.get(VAR_VRAI_HOME) or os.path.expanduser("~"))


VRAI_HOME = _vrai_home()
_PREFIXE = VRAI_HOME.rstrip(os.sep) + os.sep
#  normpath : sous Windows, joindre ".cache/bz-sandbox" laissait un « / » que le chemin
#  normalisé comparé ne contient jamais — l'exclusion ne s'appliquait pas.
_EXCLUS = tuple(os.path.normpath(os.path.join(VRAI_HOME, e)) for e in EXCLUS)
#  Rangés dans UN sous-dossier qui ne disparaît jamais, pas à plat dans %TEMP% : un pytest qui
#  parcourt %TEMP% (cible hors de son rootdir) y tombait sur un `bz-home-*` d'un autre process en
#  train d'être supprimé — FileNotFoundError à la collecte (mesuré le 2026-10-05).
DOSSIER_DES_HOMES = Path(tempfile.gettempdir()) / "bz-homes"
DOSSIER_DES_HOMES.mkdir(exist_ok=True)
FAUX_HOME = Path(tempfile.mkdtemp(prefix=f"bz-home-{os.environ.get('PYTEST_XDIST_WORKER', 'main')}-",
                                  dir=DOSSIER_DES_HOMES))

#  (test en cours ou None, événement, chemin) ; vidé test par test.
_violations: list[tuple[str | None, str, str]] = []
_hors_test: list[str] = []
_test_courant: list[str | None] = [None]
#  Le HOME du worker est partagé par tous ses tests : y écrire pendant un test laisse un état au
#  suivant (et, avant ce plugin, c'était le vrai HOME). Interdit aussi, hors test toléré (imports).
_PREFIXE_FAUX = str(FAUX_HOME) + os.sep
#  Le dépôt (rootdir) : posé par pytest_configure. Un chemin relatif au cwd y retombe souvent.
_PREFIXE_DEPOT: list[str] = []


def _variables_de_home(home: Path) -> dict[str, str]:
    variables = {"HOME": str(home), "USERPROFILE": str(home)}
    for nom, sous in (("CONFIG", ".config"), ("CACHE", ".cache"), ("DATA", ".local/share"),
                      ("STATE", ".local/state")):
        variables[f"XDG_{nom}_HOME"] = str(home / sous)
    return variables


def _rediriger() -> None:
    os.environ[VAR_VRAI_HOME] = VRAI_HOME
    os.environ.update(_variables_de_home(FAUX_HOME))
    navigateurs = Path(VRAI_HOME) / ".cache" / "ms-playwright"
    if navigateurs.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(navigateurs))
    os.environ.setdefault("BZ_SNAPSHOT_DIR", str(Path(VRAI_HOME) / ".cache" / "bz-sandbox"))
    _cache_d_analyse_powershell()
    atexit.register(shutil.rmtree, FAUX_HOME, ignore_errors=True)


def _cache_d_analyse_powershell() -> None:
    """Rend à powershell.exe son cache d'analyse des modules, qu'un HOME jetable lui ôte.

    Sous un USERPROFILE jetable, `GetFolderPath('LocalApplicationData')` rend "" (le dossier
    n'existe pas) : plus de cache, et la PREMIÈRE commande introuvable d'un process réanalyse
    tous les modules du PSModulePath — 2,2 à 2,8 s au lieu de 70 ms (mesuré le 2026-09-30 ;
    `test_execution_policy_wrapper_is_kept_because_it_is_deliberate` y passait 12 s). Une COPIE
    du cache réel, désignée par PSModuleAnalysisCachePath : lue, jamais le vrai fichier."""
    reel = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/PowerShell/ModuleAnalysisCache"
    if sys.platform != "win32" or "PSModuleAnalysisCachePath" in os.environ or not reel.is_file():
        return
    copie = FAUX_HOME / "ModuleAnalysisCache"
    shutil.copyfile(reel, copie)
    os.environ["PSModuleAnalysisCachePath"] = str(copie)


def surveille(chemin: str) -> bool:
    """Vrai si `chemin` (absolu) est une zone du vrai HOME qu'aucun test ne doit toucher."""
    if not chemin.startswith(_PREFIXE):
        return False
    chemin = os.path.normpath(chemin)
    if not chemin.startswith(_PREFIXE) or chemin.startswith(_EXCLUS):
        return False
    relatif = chemin[len(_PREFIXE):]
    return relatif.startswith(".") or os.sep not in relatif


def _absolu(brut, relatif_au_cwd: bool) -> str | None:
    if isinstance(brut, int) or brut is None:
        return None
    try:
        chemin = os.fsdecode(os.fspath(brut))
    except TypeError:
        return None
    if os.path.isabs(chemin):
        return chemin
    return os.path.join(os.getcwd(), chemin) if relatif_au_cwd else None


def _ouverture_en_ecriture(args) -> bool:
    mode, flags = args[1], args[2]
    if isinstance(flags, int) and flags & _ECRITURE:
        return True
    return isinstance(mode, str) and any(c in mode for c in "wax+")


def _home_de_l_enfant(args) -> tuple:
    """HOME et USERPROFILE : sous Windows, `Path.home()` de l'enfant lit USERPROFILE."""
    env = args[3] if len(args) > 3 else None
    if not isinstance(env, dict):
        return ()
    return tuple(env[nom] for nom in ("HOME", "USERPROFILE") if env.get(nom))


def _chemins_ecrits(evenement: str, args) -> tuple:
    if evenement == "open":
        return (args[0],) if _ouverture_en_ecriture(args) else ()
    if evenement == "subprocess.Popen":
        return _home_de_l_enfant(args)
    if evenement == "sqlite3.connect" and str(args[0]).startswith((":memory:", "file:")):
        return ()
    return tuple(args[i] for i in _CHEMINS.get(evenement, ()) if i < len(args))


def _fautif(evenement: str, chemin: str) -> bool:
    if evenement == "subprocess.Popen":
        return os.path.realpath(chemin) == VRAI_HOME
    #  Le dépôt testé peut vivre DANS un dossier caché du vrai HOME (worktrees d'agents sous
    #  ~/.bouzecode/worktrees) : ce n'est pas le vrai HOME mais le dépôt, que la règle
    #  `_partage_pendant_un_test` gouverne. Sans ça, son bytecode passait pour une fuite et
    #  `-n 4` faisait échouer le test qui compilait un module le premier.
    if chemin.startswith(tuple(_PREFIXE_DEPOT)) or _bytecode(chemin):
        return False
    #  `mkdir` d'un dossier qui existe déjà (parents=True, exist_ok=True) n'écrit rien.
    return surveille(chemin) and not (evenement == "os.mkdir" and os.path.isdir(chemin))


def _bytecode(chemin: str) -> bool:
    """`…/__pycache__/m.cpython-312.pyc` et son fichier temporaire `….pyc.<n>` : écrits par
    l'import de Python lui-même, jamais un état qu'un test laisse. Les relever remplissait la
    section « hors d'un test » de ~460 lignes de faux positifs (run du 2026-10-07)."""
    return "/__pycache__/" in chemin.replace("\\", "/") and ".pyc" in os.path.basename(chemin)


def _partage_pendant_un_test(evenement: str, chemin: str) -> bool:
    """HOME du worker ou dépôt lui-même : partagés par tous les tests (et le dépôt par tous les
    workers). Le bytecode et le cache de pytest y sont chez eux."""
    if _test_courant[0] is None or not chemin.startswith((_PREFIXE_FAUX, *_PREFIXE_DEPOT)):
        return False
    return "__pycache__" not in chemin and not (evenement == "os.mkdir" and os.path.isdir(chemin))


def _noter(evenement: str, chemin: str) -> None:
    if _fautif(evenement, chemin) or _partage_pendant_un_test(evenement, chemin):
        _violations.append((_test_courant[0], evenement, chemin))


def _resolu_contre_cwd(evenement: str, args) -> bool:
    """Un chemin relatif ne se résout contre le cwd que si aucun `dir_fd` n'a pu être passé :
    `open()` intégré (mode texte) et `sqlite3.connect`. `os.open`, `os.remove`… sous `rmtree`
    reçoivent des noms relatifs à un descripteur : ce n'est pas le cwd, on les ignore."""
    return evenement == "sqlite3.connect" or (evenement == "open" and isinstance(args[1], str))


def _audit(evenement: str, args) -> None:
    if evenement not in _EVENEMENTS:
        return
    for brut in _chemins_ecrits(evenement, args):
        chemin = _absolu(brut, _resolu_contre_cwd(evenement, args))
        if chemin:
            _noter(evenement, chemin)


def _message(violations) -> str:
    lignes = sorted({f"{evt} {chemin}" for _t, evt, chemin in violations})
    return (f"Écriture hors des dossiers du test — vrai HOME ({VRAI_HOME}), HOME partagé du "
            f"worker ({FAUX_HOME}) ou dépôt. Passer par tmp_path (monkeypatch.chdir pour un "
            "chemin relatif) ou rediriger le chemin figé à l'import dans "
            "production_isolation.isoler_les_fichiers_du_home :\n  " + "\n  ".join(lignes))


def _vider() -> list:
    pris = list(_violations)
    del _violations[: len(pris)]
    return pris


#  Affectation de module qui lit le HOME à l'import : `CONFIG_DIR = bouzecode_data_dir()`.
_FIGE_A_L_IMPORT = re.compile(r"^[A-Za-z_]\w*\s*(:[^=]*)?=.*(Path\.home\(\)|expanduser\()", re.M)


def _modules_qui_figent_le_home(racine: Path) -> list[str]:
    modules = []
    for fichier in racine.rglob("*.py"):
        source = fichier.read_text("utf-8", "replace")
        if "tests" in fichier.parts or not _FIGE_A_L_IMPORT.search(source):
            continue
        modules.append(".".join(fichier.relative_to(racine.parent).with_suffix("").parts))
    return sorted(modules)


def pytest_configure(config):
    _PREFIXE_DEPOT[:] = [os.path.realpath(config.rootpath) + os.sep]


def preparer_home_du_worker(home: Path) -> Path:
    """Crée d'avance le dossier de données (`~/.bouzecode` ou `~/.bouzecode`) du HOME du worker.
    Les modules qui l'ont figé à l'import le créent paresseusement (`mkdir(parents=True)`) : le
    premier test du worker qui y touchait faisait ce `os.mkdir`, relevé comme écriture dans le
    HOME partagé, et échouait seul (premier test de chaque fichier lancé en `-n`)."""
    from bouzecode.paths import data_dir

    dossier = data_dir(home)
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def pytest_sessionstart(session):
    """Importe d'avance les modules qui figent un chemin du HOME à l'import, sous le HOME du
    WORKER. Sinon le premier test qui les importe les fige sur SON HOME de test, que tous les
    tests suivants du worker partageraient alors sans que rien ne le voie."""
    import bouzecode

    preparer_home_du_worker(FAUX_HOME)
    for nom in _modules_qui_figent_le_home(Path(bouzecode.__file__).parent):
        try:
            importlib.import_module(nom)
        except Exception:  # module optionnel absent de l'environnement : rien à figer
            pass


@pytest.fixture(autouse=True)
def _home_du_test(tmp_path_factory, monkeypatch):
    """HOME propre à CHAQUE test pour tout ce qui relit `Path.home()` à l'appel (checkpoints,
    profils Chrome, sorties d'outils…) et pour les sous-processus. Les chemins figés à l'import
    restent sur le HOME du worker : `production_isolation` les redirige un par un."""
    home = tmp_path_factory.mktemp("home")
    for nom, valeur in _variables_de_home(home).items():
        monkeypatch.setenv(nom, valeur)
    return home


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item):
    _hors_test.extend(f"{e} {c}" for _t, e, c in _vider())
    _test_courant[0] = item.nodeid
    yield
    _test_courant[0] = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    resultat = yield
    rapport = resultat.get_result()
    fautes = _vider()
    if not fautes:
        return
    if rapport.failed:
        rapport.sections.append(("écritures hors du test", _message(fautes)))
    else:
        rapport.outcome = "failed"
        rapport.longrepr = _message(fautes)


def pytest_sessionfinish(session):
    _hors_test.extend(f"{e} {c}" for _t, e, c in _vider())
    sortie = getattr(session.config, "workeroutput", None)
    if sortie is not None:
        sortie["bz_home_hors_test"] = list(_hors_test)
    elif _hors_test:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    """Contrôleur xdist : rapatrie les écritures hors test de chaque worker."""
    _hors_test.extend(getattr(node, "workeroutput", {}).get("bz_home_hors_test", ()))


def pytest_terminal_summary(terminalreporter):
    if _hors_test:
        terminalreporter.section("écritures dans le VRAI HOME hors d'un test", red=True)
        for ligne in sorted(set(_hors_test)):
            terminalreporter.write_line(ligne)


_rediriger()
sys.addaudithook(_audit)
