"""Sonde n°2 (VM) : trouver un Chromium headless pilotable par Playwright SANS Internet ni root.

Constat de la sonde n°1 (2026-10-05, vm-host) : Ubuntu 18.04 / glibc 2.27, Internet coupe,
Artifactory joignable ; le Node embarque par Playwright 1.63 exige GLIBC_2.28. Tout vient donc
de l'Artifactory (seule source autorisee) :
- Node : roue PyPI `nodejs-wheel-binaries` (uv choisit la version compatible manylinux/glibc 2.27),
  branchee via PLAYWRIGHT_NODEJS_PATH ;
- Chromium : paquet npm `@sparticuz/chromium` (miroir npm-public), binaire + libs compresses brotli.
Entrees RD_OPTION_* : RUN_ID, INDEX_PIP, NPM_REGISTRE, PW_VERSION, CHROMIUM_VERSIONS (espaces).
"""
import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

UV = "/data/datainno/uv/uv"
RACINE = Path("/data/projects/bouzecode_remote")


def rapporter(cle, valeur):
    print(f"SONDE|{cle}|{json.dumps(valeur, ensure_ascii=False)}", flush=True)


def lancer(commande, delai_s=300, env=None):
    debut = time.monotonic()
    try:
        r = subprocess.run(commande, shell=True, capture_output=True, text=True, timeout=delai_s, env=env)
    except subprocess.TimeoutExpired:
        return {"code": "delai_depasse", "duree_s": delai_s, "sortie": ""}
    return {"code": r.returncode, "duree_s": round(time.monotonic() - debut, 1), "sortie": (r.stdout + r.stderr)[-1500:]}


def telecharger(url, destination):
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with ouvreur.open(url, timeout=120) as reponse, open(destination, "wb") as sortie:
        shutil.copyfileobj(reponse, sortie)
    return destination.stat().st_size


def preparer_venv(dossier, env):
    rapporter("venv", lancer(f"{UV} venv --python python3.11 {dossier}/venv", env=env))
    installer = f"{UV} pip install --python {dossier}/venv/bin/python --only-binary :all:"
    rapporter("pip", lancer(f"{installer} playwright=={env['PW_VERSION']} brotli", env=env))
    # Sans --only-binary, uv retombe sur le sdist (compilation qui telecharge les sources Node sur
    # github.com, coupe) : on exige une roue, uv prend la plus recente compatible glibc 2.27.
    rapporter("pip_node", lancer(f"{installer} nodejs-wheel-binaries", env=env))
    rapporter("pip_liste", lancer(f"{UV} pip list --python {dossier}/venv/bin/python", env=env))
    node = lancer(f"find {dossier}/venv -path '*nodejs_wheel*' -type f -name node | head -1")["sortie"].strip()
    rapporter("node", {"chemin": node, "version": lancer(f"{node} --version")["sortie"] if node else None})
    return node


def deballer_chromium(version, dossier, registre):
    cible = dossier / f"chromium-{version}"
    cible.mkdir(parents=True, exist_ok=True)
    archive = cible / "paquet.tgz"
    url = f"{registre}/@sparticuz/chromium/-/chromium-{version}.tgz"
    rapporter("npm_telechargement", {"version": version, "octets": telecharger(url, archive)})
    with tarfile.open(archive) as tar:
        tar.extractall(cible)
    contenu = sorted(p.name for p in (cible / "package" / "bin").iterdir())
    rapporter("npm_contenu", {"version": version, "bin": contenu})
    python = f"{dossier}/venv/bin/python"
    variantes = {}
    for nom in contenu:
        source = cible / "package" / "bin" / nom
        if nom == "chromium.br":
            lancer(f"{python} -c \"import brotli;open('{cible}/chromium','wb').write(brotli.decompress(open('{source}','rb').read()))\"")
            os.chmod(cible / "chromium", 0o755)
        elif nom.endswith(".tar.br") and nom.startswith("al2"):
            variante = nom[:-7]
            lancer(f"{python} -c \"import brotli;open('{cible}/{variante}.tar','wb').write(brotli.decompress(open('{source}','rb').read()))\"")
            lancer(f"mkdir -p {cible}/libs_{variante} && tar -xf {cible}/{variante}.tar -C {cible}/libs_{variante}")
            variantes[variante] = lancer(f"find {cible}/libs_{variante} -name '*.so*' -printf '%h\n' | sort -u | tr '\n' ':'")["sortie"].strip()
    return cible / "chromium", variantes


def essayer_chromium(executable, nom_libs, libs, dossier, env, node):
    rapporter("essai", {"chromium": str(executable), "libs": nom_libs})
    env_libs = dict(env, LD_LIBRARY_PATH=libs) if libs else dict(env)
    rapporter("chromium_ldd", lancer(f"ldd {executable} | grep -E 'not found|GLIBC' ; echo fin", env=env_libs))
    rapporter("chromium_version", lancer(f"{executable} --version", 60, env_libs))
    if lancer(f"{executable} --version", 60, env_libs)["code"] != 0:
        return
    rapporter("chromium_dump_dom", lancer(
        f"{executable} --headless=new --no-sandbox --disable-gpu --single-process --no-zygote "
        f"--dump-dom 'data:text/html,<title>ok-bz</title><h1>bonjour</h1>'", 60, env_libs))
    essai = ("import sys\nfrom playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p:\n"
             "    b = p.chromium.launch(executable_path=sys.argv[1], headless=True,\n"
             "        args=['--no-sandbox','--disable-gpu','--single-process','--no-zygote'])\n"
             "    pg = b.new_page(); pg.goto('data:text/html,<title>ok-bz</title><h1>x</h1>')\n"
             "    pg.screenshot(path=sys.argv[2]); print('TITRE', pg.title(), b.version); b.close()\n")
    (dossier / "essai_pw.py").write_text(essai)
    env_pw = dict(env_libs, PLAYWRIGHT_NODEJS_PATH=node)
    capture = executable.parent / f"capture_{nom_libs}.png"
    rapporter("playwright_lancement", lancer(f"{dossier}/venv/bin/python {dossier}/essai_pw.py {executable} {capture}",
                                             180, env_pw))
    rapporter("playwright_capture", {"octets": capture.stat().st_size if capture.exists() else 0})


def main():
    run_id = os.environ.get("RD_OPTION_RUN_ID", "manuel")
    dossier = RACINE / run_id
    dossier.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, UV_INDEX_URL=os.environ.get("RD_OPTION_INDEX_PIP", ""), TMPDIR=str(dossier),
               UV_CACHE_DIR=str(dossier / "uv_cache"), PW_VERSION=os.environ.get("RD_OPTION_PW_VERSION", "1.62.0"))
    node = preparer_venv(dossier, env)
    rapporter("pw_cli_node_externe", lancer(f"{dossier}/venv/bin/python -m playwright --version", 60,
                                            dict(env, PLAYWRIGHT_NODEJS_PATH=node)))
    libs_al2 = {}
    for version in os.environ.get("RD_OPTION_CHROMIUM_VERSIONS", "").split():
        executable, variantes = deballer_chromium(version, dossier, os.environ["RD_OPTION_NPM_REGISTRE"])
        libs_al2.update({f"al2_de_{version}": v for k, v in variantes.items() if k == "al2"})
        essais = {"systeme": "", **libs_al2}
        for nom_libs, libs in essais.items():
            essayer_chromium(executable, nom_libs, libs, dossier, env, node)
    rapporter("taille_dossier_essai", lancer(f"du -sh {dossier}")["sortie"])
    shutil.rmtree(dossier, ignore_errors=True)
    rapporter("fin", {"nettoye": not dossier.exists()})


if __name__ == "__main__":
    main()
