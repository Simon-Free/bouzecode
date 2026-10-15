# [desc] Vrai lancement Chromium du plugin `_bz_pw_patch` : coquille headless livrée par Playwright plutôt qu'Edge système, et fermeture qui tue le navigateur au lieu d'attendre sa fermeture polie [/desc]
"""Autonome (copié à côté de `_bz_pw_patch`, lu aussi par la sonde de testd) : stdlib seulement,
Playwright n'est jamais importé ici.

Mesuré le 2026-10-14 (médianes de ≥ 3 runs, poste chargé) : Edge système (`channel="msedge"`)
ferme poliment en 7 à 51 s (7,4 s pour la coquille livrée), un lancement a pendu 175 s, et sa
requête favicon échoue en `net::ERR_ABORTED`, comptée comme erreur par les contrôles stricts de
page. D'où : la coquille `chromium_headless_shell-<rév>` de CETTE version de Playwright quand
elle est installée, Edge sinon (et c'est dit) ; et un navigateur lancé par le patch est TUÉ à
sa fermeture (0,0 s, ses enfants tombent avec lui) avant que Playwright ne solde la session."""
import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path


def dossier_navigateurs() -> Path:
    """Même règle que le registre de Playwright (`lib/server/registry/index.js`)."""
    defini = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    paquet = importlib.util.find_spec("playwright")
    if defini == "0" and paquet:
        return Path(paquet.origin).parent / "driver" / "package" / ".local-browsers"
    if defini:
        return Path(defini)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"


def revision_coquille() -> str:
    """Révision de `chromium-headless-shell` attendue par le Playwright importable ("" : aucun)."""
    paquet = importlib.util.find_spec("playwright")
    if not paquet:
        return ""
    navigateurs = Path(paquet.origin).parent / "driver" / "package" / "browsers.json"
    if not navigateurs.is_file():
        return ""
    for navigateur in json.loads(navigateurs.read_text(encoding="utf-8"))["browsers"]:
        if navigateur["name"] == "chromium-headless-shell":
            return str(navigateur["revision"])
    return ""


def coquille_installee() -> str:
    """Révision de la coquille si elle est installée pour ce Playwright, "" sinon."""
    revision = revision_coquille()
    dossier = dossier_navigateurs() / f"chromium_headless_shell-{revision}"
    return revision if revision and (dossier / "INSTALLATION_COMPLETE").is_file() else ""


def sonde() -> dict:
    """Ce que testd demande au python du projet avant de lancer son navigateur chaud."""
    if not importlib.util.find_spec("playwright"):
        return {"version": "", "coquille": "", "attendue": ""}
    return {"version": importlib.metadata.version("playwright"), "coquille": coquille_installee(),
            "attendue": revision_coquille()}


def canal_par_defaut(note) -> str | None:
    """None : la coquille livrée ; "msedge" quand elle manque (`note` le dit)."""
    if coquille_installee():
        return None
    attendue = revision_coquille()
    note(f"[bz-pw] chromium_headless_shell-{attendue} absente de {dossier_navigateurs()} -> Edge système (msedge)")
    return "msedge"


def tuer(pid: int) -> None:
    """Tue le process navigateur, sans lancer de process (sous charge, un démarrage de process
    s'étire de 10 à 40 fois) : ses enfants (rendu, GPU, réseau) tombent avec lui."""
    if sys.platform != "win32":
        import signal
        os.kill(pid, signal.SIGKILL)
        return
    import ctypes
    noyau = ctypes.windll.kernel32
    poignee = noyau.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if poignee:  # 0 : déjà sorti
        noyau.TerminateProcess(poignee, 1)
        noyau.CloseHandle(poignee)


def _pid(info: dict) -> int:
    return next(p["id"] for p in info["processInfo"] if p["type"] == "browser")


def armer_fermeture(navigateur) -> None:
    """`close()` d'un navigateur lancé par le patch : tuer, puis solder la session Playwright."""
    pid = _pid(navigateur.new_browser_cdp_session().send("SystemInfo.getProcessInfo"))
    fermer = navigateur.close

    def fermer_en_tuant(*args, **kwargs):
        if navigateur.is_connected():
            tuer(pid)
        return fermer(*args, **kwargs)
    navigateur.close = fermer_en_tuant


async def armer_fermeture_async(navigateur) -> None:
    session = await navigateur.new_browser_cdp_session()
    pid = _pid(await session.send("SystemInfo.getProcessInfo"))
    fermer = navigateur.close

    async def fermer_en_tuant(*args, **kwargs):
        if navigateur.is_connected():
            tuer(pid)
        return await fermer(*args, **kwargs)
    navigateur.close = fermer_en_tuant
