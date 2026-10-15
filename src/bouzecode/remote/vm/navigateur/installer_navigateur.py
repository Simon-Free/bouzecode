"""Equivalent `playwright install chromium` pour les VM Rundeck rec (Ubuntu 18.04, glibc 2.27, sans root,
sans Internet). Mesures du 2026-10-05 sur vm-host : le Node embarque par Playwright exige
GLIBC_2.28 et les CDN de navigateurs sont coupes ; seul l'Artifactory repond. Tout vient donc de lui :

- Playwright (PyPI) + Node 22 en roue `nodejs-wheel-binaries` (manylinux 2.17), branche par
  PLAYWRIGHT_NODEJS_PATH ;
- Chromium headless : paquet npm `@sparticuz/chromium` (miroir npm-public), binaire brotli ;
- NSS/NSPR (seules libs systeme absentes, cf. ldd) : paquets conda-forge glibc>=2.17 (miroir conda).

Le binaire est expose a Playwright sous le chemin exact qu'il attend (lu dans son message
« Executable doesn't exist at ... ») via un lanceur bash qui pose LD_LIBRARY_PATH et --no-sandbox ;
`p.chromium.launch()` marche alors sans executable_path. Cache persistant par cle de versions,
construit dans un dossier temporaire suffixe puis renomme (atomique) ; reutilise s'il existe.
Usage : python3.11 installer_navigateur.py <racine_cache> <index_pip> <registre_npm> <canal_conda> <suffixe>
        [version_playwright]  (doit egaler celle des tests : les chemins des lanceurs en dependent)
Sortie : derniere ligne `BZ_NAVIGATEUR|{json des variables d'environnement a poser}`.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from deballage import deballer_chromium, deballer_conda

UV = "/data/datainno/uv/uv"
PLAYWRIGHT_VERSION_DEFAUT = "1.63.0"  # celle du uv.lock bouzecode : les lanceurs suivent ses revisions
CHROMIUM_NPM_VERSION = "149.0.0"
PAQUETS_CONDA = (
    "nspr-4.40-h29cc59b_0.conda", "nss-3.118-h445c969_0.conda", "libsqlite-3.53.4-h0c1763c_0.conda",
    "libzlib-1.3.2-h25fd6f3_3.conda", "libstdcxx-16.2.0-h934c35e_7.conda", "libgcc-16.2.0-ha9f2e26_7.conda",
)
ESSAI = """import json, re, sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try:
        b = p.chromium.launch(headless=True)
    except Exception as erreur:
        manque = re.search(r"Executable doesn't exist at (\\S+)", str(erreur))
        print("MANQUE|" + (manque.group(1) if manque else str(erreur)[:800])); sys.exit(3)
    page = b.new_page(); page.goto("data:text/html,<title>ok-bz</title><h1>x</h1>")
    print("OK|" + json.dumps({"titre": page.title(), "version": b.version})); b.close()
"""


def lancer(commande: list[str], env: dict | None = None, delai_s: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(commande, capture_output=True, text=True, env=env, timeout=delai_s)


def variables(dossier: Path) -> dict:
    node = next((dossier / "venv").glob("lib/python*/site-packages/nodejs_wheel/bin/node"))
    return {"PLAYWRIGHT_BROWSERS_PATH": str(dossier / "ms-playwright"), "PLAYWRIGHT_NODEJS_PATH": str(node),
            "BZ_PYTHON_NAVIGATEUR": str(dossier / "venv" / "bin" / "python")}


LANCEUR = """#!/bin/bash
# Lanceur relocalisable : remonte jusqu'a ms-playwright/, le cache est son parent.
R="$(readlink -f "$0")"
while [ "$(basename "$R")" != "ms-playwright" ]; do R="$(dirname "$R")"; done
D="$(dirname "$R")"
export LD_LIBRARY_PATH="$D/libs/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$D/chromium/chromium" --no-sandbox --no-zygote --disable-gpu "$@"
"""


def poser_lanceur(chemin_attendu: Path) -> None:
    chemin_attendu.parent.mkdir(parents=True, exist_ok=True)
    chemin_attendu.write_text(LANCEUR)
    chemin_attendu.chmod(0o755)
    marqueur = chemin_attendu
    while marqueur.parent.name != "ms-playwright":
        marqueur = marqueur.parent
    (marqueur / "INSTALLATION_COMPLETE").touch()


def essayer(dossier: Path, env: dict) -> str:
    (dossier / "essai_navigateur.py").write_text(ESSAI)
    for _ in range(3):  # chromium puis chromium_headless_shell selon ce que demande Playwright
        sortie = lancer([env["BZ_PYTHON_NAVIGATEUR"], str(dossier / "essai_navigateur.py")], env, 180)
        lignes = (sortie.stdout + sortie.stderr).strip().splitlines() or ["(vide)"]
        resultat = next((l for l in lignes if l.startswith(("OK|", "MANQUE|"))), lignes[-1])
        if not resultat.startswith("MANQUE|/"):
            return resultat
        poser_lanceur(Path(resultat.split("|", 1)[1]))
    return resultat


def construire(dossier: Path, version_pw: str, index_pip: str, registre_npm: str, canal_conda: str,
               env: dict) -> str:
    dossier.mkdir(parents=True)
    env_uv = dict(env, UV_INDEX_URL=index_pip, UV_CACHE_DIR=str(dossier.parent / "uv_cache"))
    lancer([UV, "venv", "--python", "python3.11", str(dossier / "venv")], env_uv).check_returncode()
    installation = lancer([UV, "pip", "install", "--python", str(dossier / "venv" / "bin" / "python"),
                           "--only-binary", ":all:", f"playwright=={version_pw}", "brotli", "zstandard",
                           "nodejs-wheel-binaries"], env_uv)
    if installation.returncode != 0:
        return "ECHEC|pip " + installation.stderr[-600:]
    python = str(dossier / "venv" / "bin" / "python")
    deballer_chromium(python, f"{registre_npm}/@sparticuz/chromium/-/chromium-{CHROMIUM_NPM_VERSION}.tgz",
                      dossier / "chromium")
    for paquet in PAQUETS_CONDA:
        deballer_conda(python, f"{canal_conda}/linux-64/{paquet}", dossier / "libs")
    return essayer(dossier, dict(env, **variables(dossier)))


def main(arguments: list[str]) -> int:
    racine, index_pip, registre_npm, canal_conda, suffixe = arguments[:5]
    version_pw = arguments[5] if len(arguments) > 5 and arguments[5] else PLAYWRIGHT_VERSION_DEFAUT
    cle = f"pw{version_pw}_chromium{CHROMIUM_NPM_VERSION}"
    final = Path(racine) / cle
    env = dict(os.environ, TMPDIR=str(Path(racine)))
    if (final / "PRET").exists():
        print("BZ_NAVIGATEUR|" + json.dumps({"reutilise": True, **variables(final)}))
        return 0
    temporaire = Path(racine) / f"{cle}.construction_{suffixe}"
    resultat = construire(temporaire, version_pw, index_pip, registre_npm, canal_conda, env)
    print("ESSAI|" + resultat)
    if not resultat.startswith("OK|"):
        shutil.rmtree(temporaire, ignore_errors=True)
        return 2
    (temporaire / "PRET").write_text(resultat)
    if not final.exists():
        temporaire.rename(final)  # rename atomique : un concurrent arrive soit avant, soit apres
    shutil.rmtree(temporaire, ignore_errors=True)
    print("BZ_NAVIGATEUR|" + json.dumps({"reutilise": False, **variables(final)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
