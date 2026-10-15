"""Tests du lanceur bouzeui.ps1 (point d'entree reel : powershell.exe -File bouzeui.ps1).

Ce que ces tests prouvent, dans l'ordre des trois defauts signales :

1. un echec d'install ne se rejoue plus indefiniment : le tampon est pose des que le
   PAQUET est utilisable, meme si le shim de console n'a pas pu etre reecrit ;
2. un shim `Scripts\\bouzecode*.exe` verrouille n'est plus traite comme un echec ;
3. chaque lancement laisse une trace horodatee dans ~/.bouzecode/bouzeui.log.

Contraintes respectees : jamais le venv du depot (hook BOUZEUI_VENV -> tmp_path),
jamais le port 5056 ni de serveur lance (hook BOUZEUI_PREPARE_ONLY=1), aucun process
d'agent touche (les verrous sont poses par les tests eux-memes, sur leur propre venv).

Les tests qui construisent un venv jetable portent `@pytest.mark.slow` A LA MAIN :
tests/auto_markers.py ne le derive que pour les tests d'API, or `uv venv` + editable
install coutent des dizaines de secondes. La fixture est de portee session pour ne
payer cette construction qu'une fois.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bouzeui.ps1"
PYPROJECT = REPO_ROOT / "pyproject.toml"

INSTALL_MARKER = "installing package (uv pip install -e .)"
SHIM_SKIPPED_MARKER = "console shim not rewritten (locked by a running process) - skipped"
UP_TO_DATE_MARKER = "nothing to install"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="bouzeui.ps1 est un lanceur PowerShell/Windows"
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "version introuvable dans pyproject.toml"
    return match.group(1)


def log_path(home: Path) -> Path:
    return home / ".bouzecode" / "bouzeui.log"


def run_launcher(home: Path, venv_dir: Path, timeout: int = 900, extra_env=None):
    """Lance le vrai bouzeui.ps1 en mode preparation seule.

    L'environnement du process de test est transmis TEL QUEL (PYTHONHOME compris) :
    c'est au lanceur de s'en premunir, comme en usage reel depuis un agent.
    Retourne (returncode, console_output, log_text).
    """
    env = dict(os.environ)
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    env["BOUZEUI_VENV"] = str(venv_dir)
    env["BOUZEUI_PREPARE_ONLY"] = "1"
    # Ne jamais laisser un PYTHONPATH herite masquer un venv casse.
    env.pop("PYTHONPATH", None)
    env.update(extra_env or {})
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LAUNCHER),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    log_file = log_path(home)
    log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), log_text


def venv_python(venv_dir: Path) -> Path:
    return venv_dir / "Scripts" / "python.exe"


def venv_reports_version(venv_dir: Path) -> str:
    """Ce que le user exige comme resultat observable : import + version, PYTHONPATH vide."""
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    # Le python uv du venv de base exporte PYTHONHOME (sa stdlib) a ses enfants : herite,
    # il ferait charger au python du venv jetable une stdlib etrangere (SRE module mismatch).
    env.pop("PYTHONHOME", None)
    proc = subprocess.run(
        [
            str(venv_python(venv_dir)),
            "-c",
            "import bouzecode, importlib.metadata as m; print(m.version('bouzecode'))",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert proc.returncode == 0, f"import bouzecode a echoue depuis le venv:\n{proc.stderr}"
    return (proc.stdout or "").strip().splitlines()[-1].strip()


class SoftLock:
    """Verrou d'un .exe tel que Windows le pose sur l'IMAGE d'un process VIVANT.

    dwShareMode = READ|WRITE|DELETE : le fichier ne peut pas etre ouvert en ecriture
    par uv, mais il PEUT etre renomme -- exactement ce dont Unblock-Shims tire parti.
    """

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        GENERIC_READ = 0x80000000
        FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004  # READ|WRITE|DELETE
        OPEN_EXISTING = 3
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.restype = ctypes.c_void_p
        handle = create_file(
            ctypes.c_wchar_p(str(self.path)),
            GENERIC_READ,
            FILE_SHARE_ALL,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        assert handle not in (None, 0, -1, 0xFFFFFFFFFFFFFFFF), "CreateFileW a echoue"
        self.handle = handle
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None
        return False


# --------------------------------------------------------------------------- #
# 1-2. Contraintes statiques (encodage + nettoyage) -- rapides
# --------------------------------------------------------------------------- #
def test_launcher_is_pure_ascii_with_bom():
    """PowerShell 5.1 relit un .ps1 sans BOM en ANSI : un seul octet >= 0x80 casse le parseur."""
    raw = LAUNCHER.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "bouzeui.ps1 doit commencer par le BOM UTF-8"
    body = raw[3:]
    offenders = [(i, b) for i, b in enumerate(body) if b >= 0x80]
    assert not offenders, f"octets non-ASCII apres le BOM: {offenders[:5]}"


def test_launcher_has_no_leftover_usev2_and_ascii_banner():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "$UseV2" not in text, "la variable $UseV2 (option -v2 retiree) doit avoir disparu"
    assert "=== bouzeui ===" in text, "banner ASCII attendu"


def test_launcher_parses_under_powershell():
    """Garde-fou : un .ps1 qui ne se parse pas ne demarre pas du tout."""
    script = (
        "$t=$null; $e=$null; "
        f"$null=[System.Management.Automation.Language.Parser]::ParseFile('{LAUNCHER}',"
        "[ref]$t,[ref]$e); "
        "if ($e -and $e.Count -gt 0) { $e | ForEach-Object { $_.Message }; exit 1 } "
        "else { 'PARSE_OK' }"
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PARSE_OK" in proc.stdout


# --------------------------------------------------------------------------- #
# Fixture : un venv jetable, prepare UNE fois par le lanceur lui-meme
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("bouzeui")
    home = root / "home"
    home.mkdir()
    venv = root / "venv"
    rc, out, log = run_launcher(home, venv)
    return {"home": home, "venv": venv, "rc": rc, "out": out, "log": log}


# --------------------------------------------------------------------------- #
# 3. Nominal : le lanceur construit un venv reellement utilisable
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_first_launch_builds_a_usable_venv(prepared):
    assert prepared["rc"] == 0, prepared["out"]
    assert venv_python(prepared["venv"]).exists(), "le venv jetable n'a pas ete cree"
    stamp = prepared["venv"] / ".bouzeui_installed"
    assert stamp.exists(), "le tampon doit etre pose apres une install reussie"
    assert venv_reports_version(prepared["venv"]) == pyproject_version()


# --------------------------------------------------------------------------- #
# 8. Journal
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_every_launch_is_journalled(prepared):
    log_file = log_path(prepared["home"])
    assert log_file.exists(), "~/.bouzecode/bouzeui.log doit etre cree"
    text = prepared["log"]
    assert re.search(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] ", text, re.MULTILINE), text
    assert "launch: repo=" in text


# --------------------------------------------------------------------------- #
# 4. Idempotence : un venv sain ne declenche AUCUNE reinstallation
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_second_launch_reinstalls_nothing(prepared):
    home = prepared["home"].parent / "home2"
    home.mkdir(exist_ok=True)
    rc, out, log = run_launcher(prepared["home"], prepared["venv"])
    assert rc == 0, out
    # Le journal cumule les deux lancements : on regarde ce que le 2e a ajoute.
    added = log[len(prepared["log"]) :]
    assert INSTALL_MARKER not in added, f"reinstallation inutile:\n{added}"
    assert UP_TO_DATE_MARKER in added, added


# --------------------------------------------------------------------------- #
# 4 bis. PYTHONHOME herite (exporte par le python uv d'un autre venv) : ignore
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_inherited_foreign_pythonhome_is_ignored(prepared, tmp_path):
    foreign_home = tmp_path / "foreign_stdlib"
    foreign_home.mkdir()
    before = prepared["home"] / ".bouzecode" / "bouzeui.log"
    before_text = before.read_text(encoding="utf-8", errors="replace")
    rc, out, log = run_launcher(
        prepared["home"], prepared["venv"], extra_env={"PYTHONHOME": str(foreign_home)}
    )
    added = log[len(before_text) :]
    assert rc == 0, out + added
    assert "ignoring inherited PYTHONHOME=" in added, added
    assert UP_TO_DATE_MARKER in added, added


# --------------------------------------------------------------------------- #
# 5. Verrou "process vivant" (FILE_SHARE_DELETE) : l'install doit aboutir
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_running_exe_lock_does_not_block_install(prepared):
    venv = prepared["venv"]
    shim = venv / "Scripts" / "bouzecode.exe"
    assert shim.exists(), "le shim de console attendu n'existe pas"
    stamp = venv / ".bouzeui_installed"
    stamp.unlink(missing_ok=True)  # force needInstall

    before = prepared["log"]
    with SoftLock(shim):
        rc, out, log = run_launcher(prepared["home"], venv)

    added = log[len(before) :]
    assert rc == 0, out + "\n--- log ---\n" + added
    assert INSTALL_MARKER in added, added
    assert stamp.exists(), "le tampon doit etre repose apres une install reussie"
    assert venv_reports_version(venv) == pyproject_version()


# --------------------------------------------------------------------------- #
# 6. Verrou DUR (sans FILE_SHARE_DELETE) : os error 5, mais le paquet est OK
#    => tampon pose quand meme + message explicite. C'est le defaut 1 + 2.
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_hard_locked_shim_still_stamps_and_leaves_venv_usable(prepared):
    venv = prepared["venv"]
    shim = venv / "Scripts" / "bouzecode.exe"
    stamp = venv / ".bouzeui_installed"
    stamp.unlink(missing_ok=True)

    log_file = log_path(prepared["home"])
    before = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""

    # open('rb') de CPython => FILE_SHARE_READ|WRITE, PAS DELETE : ni rename ni delete.
    with open(shim, "rb") as handle:
        handle.read(1)
        rc, out, log = run_launcher(prepared["home"], venv)

    added = log[len(before) :]
    assert rc == 0, "un shim verrouille ne doit pas faire echouer le lancement:\n" + out + added
    assert SHIM_SKIPPED_MARKER in added, "message explicite attendu:\n" + added
    assert stamp.exists(), "le tampon doit etre pose: le PAQUET est bien installe"
    # Le resultat observable exige par le user :
    assert venv_reports_version(venv) == pyproject_version()


# --------------------------------------------------------------------------- #
# 7. Venv reellement inutilisable => echec BRUYANT, serveur non lance
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_broken_venv_fails_loudly(prepared, tmp_path):
    """Un venv dont le python est absent ne peut pas etre repare : il faut refuser."""
    home = tmp_path / "home"
    home.mkdir()
    venv = tmp_path / "brokenvenv"
    (venv / "Scripts").mkdir(parents=True)
    # pyvenv.cfg present mais python.exe absent : le lanceur croit le venv la, uv ne
    # peut rien y installer -> le health check ne passera jamais.
    (venv / "pyvenv.cfg").write_text("home = C:\\nowhere\n", encoding="utf-8")
    (venv / "Scripts" / "python.exe").write_bytes(b"not a real python")

    rc, out, log = run_launcher(home, venv, timeout=600)
    assert rc != 0, "un venv inutilisable doit faire echouer le lancement:\n" + out
    assert "unusable" in (out + log).lower(), out + log
    assert "starting server" not in (out + log), "le serveur ne doit PAS etre lance"
    shutil.rmtree(venv, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 6 bis. Incident du 2026-10-06 : shim verrouille par une session interactive +
#        metadonnees perimees d'une install EDITABLE => le serveur doit demarrer
#        en repli PYTHONPATH=src, et aucun shim ne doit disparaitre.
# --------------------------------------------------------------------------- #
STALE_VERSION = "3.5.98"
FALLBACK_MARKER = "FALLBACK: install returned"
# Hors ligne et sans cache, uv ne peut pas obtenir hatchling : l'install echoue a
# coup sur, comme celle qu'un shim verrouille a fait echouer le 2026-10-06.
FAILING_INSTALL_ENV = {"UV_OFFLINE": "1", "UV_NO_CACHE": "1"}


def site_packages(venv_dir: Path) -> Path:
    return venv_dir / "Lib" / "site-packages"


@contextlib.contextmanager
def stale_metadata(venv_dir: Path):
    """Fait dire aux metadonnees de l'install editable une version anterieure."""
    dist_info = site_packages(venv_dir) / f"bouzecode-{pyproject_version()}.dist-info"
    assert dist_info.is_dir(), f"dist-info attendu: {dist_info}"
    metadata = dist_info / "METADATA"
    original = metadata.read_text(encoding="utf-8")
    metadata.write_text(
        re.sub(r"^Version: .*$", f"Version: {STALE_VERSION}", original, count=1, flags=re.MULTILINE),
        encoding="utf-8",
    )
    stale_dir = dist_info.with_name(f"bouzecode-{STALE_VERSION}.dist-info")
    dist_info.rename(stale_dir)
    try:
        yield
    finally:
        stale_dir.rename(dist_info)
        metadata.write_text(original, encoding="utf-8")


@contextlib.contextmanager
def editable_link_removed(venv_dir: Path):
    """Simule une install interrompue apres la desinstallation : plus de .pth vers src."""
    src = str(REPO_ROOT / "src").lower()
    links = [
        pth
        for pth in site_packages(venv_dir).glob("*.pth")
        if src in pth.read_text(encoding="utf-8", errors="replace").lower()
    ]
    assert links, "le .pth de l'install editable est introuvable"
    for pth in links:
        pth.rename(pth.with_suffix(".pth.off"))
    try:
        yield
    finally:
        for pth in links:
            pth.with_suffix(".pth.off").rename(pth)


def assert_shims_in_place(venv_dir: Path) -> None:
    scripts = venv_dir / "Scripts"
    assert (scripts / "bouzecode.exe").exists(), "bouzecode.exe ne doit jamais disparaitre"
    assert (scripts / "bouzecode.exe").exists()
    leftovers = sorted(p.name for p in scripts.glob("*.locked-*"))
    assert not leftovers, f"shims laisses de cote: {leftovers}"


def run_with_hard_locked_shim(prepared):
    venv = prepared["venv"]
    log_file = log_path(prepared["home"])
    before = log_file.read_text(encoding="utf-8", errors="replace")
    with open(venv / "Scripts" / "bouzecode.exe", "rb") as handle:
        handle.read(1)
        rc, out, log = run_launcher(prepared["home"], venv, extra_env=FAILING_INSTALL_ENV)
    return rc, out, log[len(before) :]


@pytest.mark.slow
def test_locked_shim_and_stale_editable_metadata_start_in_fallback(prepared):
    venv = prepared["venv"]
    stamp = venv / ".bouzeui_installed"
    stamp_before = stamp.read_text(encoding="ascii")
    with stale_metadata(venv):
        rc, out, added = run_with_hard_locked_shim(prepared)
    assert rc == 0, "metadonnees perimees + shim verrouille ne doivent pas bloquer:\n" + out + added
    assert f"metadata says bouzecode {STALE_VERSION}" in added, added
    assert FALLBACK_MARKER in added, added
    assert "prepare-only: skipping server launch" in added, added
    assert "shim restored (install did not rewrite it): bouzecode.exe" in added, added
    assert stamp.read_text(encoding="ascii") == stamp_before, "repli => tampon NON reecrit"
    assert_shims_in_place(venv)


@pytest.mark.slow
def test_editable_link_lost_still_starts_from_src(prepared):
    venv = prepared["venv"]
    with editable_link_removed(venv):
        rc, out, added = run_with_hard_locked_shim(prepared)
    assert rc == 0, "import possible via src => le serveur doit demarrer:\n" + out + added
    assert "venv state is 'broken'" in added, added
    assert FALLBACK_MARKER in added, added
    assert_shims_in_place(venv)
