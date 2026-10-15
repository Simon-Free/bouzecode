# [desc] Bac à sable bouzeui v2 multiplateforme (Windows compris) : faux LLM + web_v2 dans un HOME jetable (HOME ET USERPROFILE isolés), seed, arrêt de tout ce qui vit dans ce HOME. [/desc]
"""Équivalent Python de `run_sandbox.sh`, utilisable sous Windows (pas d'`env -i`, pas de pgrep).

    python tests/sandbox/run_sandbox.py start [--seed] [--fresh] [--test]
    python tests/sandbox/run_sandbox.py stop | status | seed

Variables : BZ_SANDBOX_HOME (dossier temporaire `bz-sandbox`), BZ_UI_PORT (5156),
MOCK_LLM_PORT (5199), MOCK_LLM_LATENCY / MOCK_LLM_CHUNK_DELAY (0 avec --test ou BZ_E2E=1).

Garanties : l'environnement des process est CONSTRUIT (jamais hérité) — ni clé d'API, ni proxy
d'entreprise, ni le vrai profil : sous Windows `Path.home()` lit USERPROFILE, isolé comme HOME.
L'arrêt tue le serveur, le faux LLM et tout process dont la ligne de commande cite ce HOME.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parents[2]
PY = Path(sys.executable)
SB = Path(os.environ.get("BZ_SANDBOX_HOME") or Path(tempfile.gettempdir()) / "bz-sandbox")
RUN = SB / ".run"
UI_PORT = os.environ.get("BZ_UI_PORT", "5156")
LLM_PORT = os.environ.get("MOCK_LLM_PORT", "5199")
REEL = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser()
NAVIGATEURS = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
                   or Path(os.environ.get("LOCALAPPDATA", REEL / "AppData/Local")) / "ms-playwright")
ARGS = sys.argv[2:]
MODELE = "claude-opus-5"
MODE_TEST = os.environ.get("BZ_E2E") == "1" or "--test" in ARGS


def log(message: str) -> None:
    print(f"[sandbox] {message}", flush=True)


def _norme(chemin) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(chemin)))).rstrip(os.sep) + os.sep


def exiger_un_home_isole() -> None:
    """Refuse un BZ_SANDBOX_HOME qui serait le vrai HOME, l'un de ses parents ou un dossier du
    vrai store (`~/.bouzecode`) : le bac y migrerait le vrai store, `stop` y tuerait tout process
    qui cite ce HOME et `--fresh` l'effacerait. Le vrai HOME d'un process de test est celui que
    `pytest_home_etanche` transmet (BZ_TESTS_VRAI_HOME)."""
    bac = _norme(SB)
    for variable in ("BZ_TESTS_VRAI_HOME", "USERPROFILE", "HOME"):
        if not os.environ.get(variable):
            continue
        reel = _norme(os.environ[variable])
        if reel.startswith(bac) or bac.startswith(_norme(Path(reel) / ".bouzecode")):
            sys.exit(f"REFUS : le HOME du bac à sable ({SB}) n'est pas isolé du vrai HOME "
                     f"({os.environ[variable]}, {variable}). Choisir un BZ_SANDBOX_HOME jetable.")


def environnement() -> dict[str, str]:
    """L'environnement MINIMAL du faux LLM, du serveur, du seed (et donc des agents)."""
    systeme = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                                          "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")
               if k in os.environ}
    git = shutil.which("git")
    chemins = [str(PY.parent), *([str(Path(git).parent)] if git else []),
               *(p for p in os.environ.get("PATH", "").split(os.pathsep)
                 if "system32" in p.lower() or "powershell" in p.lower()), "/usr/bin", "/bin"]
    latence = os.environ.get("MOCK_LLM_LATENCY") or ("0" if MODE_TEST else "0.8")
    env = {**systeme, "HOME": str(SB), "USERPROFILE": str(SB), "APPDATA": str(SB / "AppData/Roaming"),
           "LOCALAPPDATA": str(SB / "AppData/Local"), "TEMP": str(SB / "tmp"), "TMP": str(SB / "tmp"),
           "USER": "sandbox", "USERNAME": "sandbox", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "TERM": "dumb",
           "PATH": os.pathsep.join(chemins), "PYTHONPATH": str(REPO / "src"),
           "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{LLM_PORT}", "ANTHROPIC_API_KEY": "sk-mock-sandbox",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
           "BOUZECODE_SANDBOX": "1", "MOCK_LLM_PORT": LLM_PORT, "MOCK_LLM_LATENCY": latence,
           "MOCK_LLM_USAGE_SEMANTICS": os.environ.get("MOCK_LLM_USAGE_SEMANTICS", "gateway"),
           "GIT_AUTHOR_NAME": "sandbox", "GIT_AUTHOR_EMAIL": "sandbox@localhost",
           "GIT_COMMITTER_NAME": "sandbox", "GIT_COMMITTER_EMAIL": "sandbox@localhost"}
    env["BOUZECODE_USAGE_INPUT_INCLUDES_CACHE_WRITE"] = "0" if env["MOCK_LLM_USAGE_SEMANTICS"] == "anthropic" else "1"
    for cle in ("MOCK_LLM_CHUNK_DELAY", "MOCK_LLM_SLOW_DELAY"):
        if os.environ.get(cle) or (MODE_TEST and cle == "MOCK_LLM_CHUNK_DELAY"):
            env[cle] = os.environ.get(cle) or "0"
    if NAVIGATEURS.is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(NAVIGATEURS)
    return env


def repond(url: str, secondes: float) -> bool:
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    fin = time.time() + secondes
    while time.time() < fin:
        try:
            with ouvreur.open(url, timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def vivant(nom: str) -> int | None:
    fichier = RUN / f"{nom}.pid"
    if fichier.exists() and psutil.pid_exists(int(fichier.read_text())):
        return int(fichier.read_text())
    return None


def demarrer(nom: str, commande: list[str], url: str, delai: float) -> None:
    if vivant(nom):
        log(f"{nom} déjà lancé (pid {vivant(nom)})")
        return
    if repond(url, 0.5):
        sys.exit(f"{url} répond déjà : port pris par un autre process")
    journal = open(RUN / f"{nom}.log", "wb")  # noqa: SIM115 — gardé ouvert par le process fils
    drapeaux = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(commande, cwd=SB, env=environnement(), stdout=journal,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=drapeaux)
    (RUN / f"{nom}.pid").write_text(str(process.pid))
    if not repond(url, delai):
        sys.exit(f"{nom} ne répond pas sur {url}, voir {RUN / f'{nom}.log'}")
    log(f"{nom:<8}: {url}  (pid {process.pid})")


def seed(mode: str) -> None:
    env = {**environnement(), "BZ_UI": f"http://127.0.0.1:{UI_PORT}"}
    subprocess.run([str(PY), str(REPO / "tests/sandbox/seed.py"), mode], cwd=SB, env=env, check=True)
    (SB / (".seeded" if mode == "offline" else ".seeded_live")).touch()


def _inscriptible_puis(fonction, chemin, _exc) -> None:
    """Les objets git sont en lecture seule sous Windows : rmtree les refuse sans ce chmod."""
    os.chmod(chemin, stat.S_IWRITE)
    fonction(chemin)


def cmd_start() -> None:
    if "--fresh" in ARGS:
        cmd_stop()
        if SB.exists():  # échec bruyant : un reste (fichier verrouillé) fausserait le seed
            shutil.rmtree(SB, onexc=_inscriptible_puis)
    if (REPO / ".env").exists():
        sys.exit(f"REFUS : {REPO / '.env'} existe (vrais secrets, chargé par les agents)")
    for dossier in (RUN, SB / "tmp", SB / "AppData/Roaming", SB / "AppData/Local", SB / ".bouzecode"):
        dossier.mkdir(parents=True, exist_ok=True)
    #  Le modèle par défaut du code (claude-opus-5-5) est servi par le gateway préprod : la garde
    #  d'environnement refuserait tout lancement. Le bac à sable fixe un modèle `anthropic`,
    #  que le faux LLM sert (ANTHROPIC_BASE_URL).
    config = SB / ".bouzecode" / "config.json"
    if not config.exists():
        config.write_text('{"model": "%s"}\n' % os.environ.get("BZ_SANDBOX_MODEL", MODELE), encoding="utf-8")
    demarrer("mock_llm", [str(PY), str(REPO / "tests/sandbox/mock_llm_server.py")],
             f"http://127.0.0.1:{LLM_PORT}/health", 20)
    if "--seed" in ARGS and not (SB / ".seeded").exists():
        seed("offline")
    demarrer("web", [str(PY), "-m", "bouzecode.web_v2", "--port", UI_PORT],
             f"http://127.0.0.1:{UI_PORT}/api/version", 90)
    if "--seed" in ARGS and not (SB / ".seeded_live").exists():
        seed("live")
    log(f"HOME sandbox : {SB}   journaux : {RUN}")


def process_du_bac() -> list[psutil.Process]:
    """Tout process dont la ligne de commande ou le répertoire courant est dans ce HOME."""
    trouves = []
    for proc in psutil.process_iter(["pid", "cmdline", "cwd"]):
        texte = " ".join(proc.info.get("cmdline") or []) + " " + str(proc.info.get("cwd") or "")
        if str(SB).lower() in texte.lower() and proc.pid != os.getpid():
            trouves.append(proc)
    return trouves


def cmd_stop() -> None:
    cibles = [psutil.Process(pid) for pid in (vivant("web"), vivant("mock_llm")) if pid]
    cibles += [enfant for proc in cibles for enfant in proc.children(recursive=True)]
    cibles += process_du_bac()
    for proc in cibles:
        if proc.is_running():
            proc.kill()
    psutil.wait_procs(cibles, timeout=10)
    for nom in ("web", "mock_llm"):
        (RUN / f"{nom}.pid").unlink(missing_ok=True)
    log(f"arrêté ({len(cibles)} process)")


def cmd_status() -> None:
    for nom in ("mock_llm", "web"):
        log(f"{nom:<8}: {'UP pid ' + str(vivant(nom)) if vivant(nom) else 'DOWN'}")
    log(f"process dans le HOME : {len(process_du_bac())}")


if __name__ == "__main__":
    commande = sys.argv[1] if len(sys.argv) > 1 else "start"
    exiger_un_home_isole()
    if commande == "seed":
        seed("offline")
        seed("live")
    else:
        {"start": cmd_start, "stop": cmd_stop, "status": cmd_status}[commande]()
