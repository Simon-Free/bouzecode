"""Sonde de faisabilite executee SUR la VM Rundeck (stdlib seule, Python >= 3.8).

Rapporte, une ligne `SONDE|<cle>|<json>` par mesure : systeme, Python/uv, disques et droits
d'ecriture, reseau sortant (direct et via proxy non authentifie), puis l'installation de
Playwright + Chromium sans root et le lancement d'un Chromium headless sur une page `data:`.
Entrees (variables RD_OPTION_* posees par Rundeck) : CIBLES (URLs separees par des espaces),
PROXY (URL du proxy, facultative), INDEX_PIP, RUN_ID. Aucun secret n'est lu ni imprime.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

UV = "/data/datainno/uv/uv"
RACINE = Path("/data/projects/bouzecode_remote")


def rapporter(cle, valeur):
    print(f"SONDE|{cle}|{json.dumps(valeur, ensure_ascii=False)}", flush=True)


def lancer(commande, delai_s=120, env=None, cwd=None):
    debut = time.monotonic()
    try:
        resultat = subprocess.run(
            commande, shell=isinstance(commande, str), capture_output=True, text=True,
            timeout=delai_s, env=env, cwd=cwd,
        )
    except subprocess.TimeoutExpired as depassement:
        sortie = ((depassement.stdout or b"") + (depassement.stderr or b"")).decode(errors="replace")
        return {"code": "delai_depasse", "duree_s": delai_s, "sortie": sortie[-1500:]}
    sortie = (resultat.stdout + resultat.stderr).strip()
    return {"code": resultat.returncode, "duree_s": round(time.monotonic() - debut, 1), "sortie": sortie[-1500:]}


def sonder_systeme():
    os_release = Path("/etc/os-release").read_text() if Path("/etc/os-release").exists() else ""
    rapporter("systeme", {
        "hote": platform.node(), "noyau": platform.release(), "machine": platform.machine(),
        "os_release": [l for l in os_release.splitlines() if l.startswith(("PRETTY_NAME", "ID=", "VERSION_ID"))],
        "utilisateur": lancer("id")["sortie"], "home": os.environ.get("HOME"),
        "glibc": platform.libc_ver(), "cpu": os.cpu_count(),
        "memoire": lancer("free -m | head -2")["sortie"],
    })
    outils = {nom: shutil.which(nom) for nom in ("python3", "python3.11", "python3.12", "git", "node", "curl",
                                                 "chromium", "chromium-browser", "google-chrome", "Xvfb", "sudo")}
    outils["uv"] = lancer(f"{UV} --version")["sortie"] if Path(UV).exists() else None
    outils["git_version"] = lancer("git --version")["sortie"] if outils["git"] else None
    outils["python_courant"] = sys.version
    rapporter("outils", outils)
    rapporter("variables_proxy", {k: bool(v) for k, v in os.environ.items() if "proxy" in k.lower()})


def sonder_disques(run_id):
    disques = {}
    for chemin in ("/tmp", os.environ.get("HOME", "/tmp"), "/data/projects", "/data/filestorage/datascience"):
        if not Path(chemin).exists():
            disques[chemin] = "absent"
            continue
        usage = shutil.disk_usage(chemin)
        essai = Path(chemin) / f".bz_ecriture_{run_id}"
        ecriture = lancer(f"touch '{essai}' && rm -f '{essai}'")["code"] == 0
        disques[chemin] = {"libre_go": round(usage.free / 1e9, 1), "total_go": round(usage.total / 1e9, 1),
                           "ecriture": ecriture}
    rapporter("disques", disques)


def tester_url(url, proxy):
    gestionnaire = urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
    ouvreur = urllib.request.build_opener(gestionnaire)
    debut = time.monotonic()
    try:
        with ouvreur.open(url, timeout=10) as reponse:
            return {"http": reponse.status, "s": round(time.monotonic() - debut, 1)}
    except urllib.error.HTTPError as erreur:
        return {"http": erreur.code, "s": round(time.monotonic() - debut, 1)}
    except Exception as erreur:  # la sonde DOIT rapporter la classe d'echec reseau, pas planter
        return {"erreur": f"{type(erreur).__name__}: {str(erreur)[:120]}", "s": round(time.monotonic() - debut, 1)}


def sonder_reseau(cibles, proxy):
    for url in cibles:
        rapporter("reseau", {"url": url, "direct": tester_url(url, None),
                             "proxy_sans_auth": tester_url(url, proxy) if proxy else None})


def sonder_playwright(dossier, index_pip, proxy):
    env = dict(os.environ, UV_INDEX_URL=index_pip, UV_CACHE_DIR=str(dossier / "uv_cache"),
               PLAYWRIGHT_BROWSERS_PATH=str(dossier / "ms-playwright"))
    rapporter("pw_venv", lancer(f"{UV} venv --python python3.11 {dossier}/venv", env=env))
    rapporter("pw_pip", lancer(f"{UV} pip install --python {dossier}/venv/bin/python playwright", 300, env))
    python = f"{dossier}/venv/bin/python"
    rapporter("pw_dry_run", lancer(f"{python} -m playwright install --dry-run chromium", 60, env))
    rapporter("pw_install_direct", lancer(f"{python} -m playwright install chromium", 300, env))
    if proxy and lancer(f"ls {dossier}/ms-playwright/chromium-*/INSTALLATION_COMPLETE")["code"] != 0:
        env_proxy = dict(env, HTTPS_PROXY=proxy, HTTP_PROXY=proxy)
        rapporter("pw_install_proxy", lancer(f"{python} -m playwright install chromium", 300, env_proxy))
    rapporter("pw_navigateurs", lancer(f"ls -la {dossier}/ms-playwright 2>&1; du -sh {dossier}/ms-playwright"))
    rapporter("pw_ldd", lancer(f"for b in $(find {dossier}/ms-playwright -maxdepth 4 -type f "
                               f"\\( -name chrome -o -name headless_shell \\)); do echo $b; "
                               f"ldd $b | grep 'not found'; done"))
    essai = ("from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p:\n"
             "    b = p.chromium.launch(headless=True)\n"
             "    pg = b.new_page(); pg.goto('data:text/html,<title>ok-bz</title><h1>x</h1>')\n"
             "    print('TITRE', pg.title()); b.close()\n")
    (dossier / "essai_pw.py").write_text(essai)
    rapporter("pw_lancement", lancer(f"{python} {dossier}/essai_pw.py", 120, env))


def main():
    run_id = os.environ.get("RD_OPTION_RUN_ID", "manuel")
    proxy = os.environ.get("RD_OPTION_PROXY", "")
    cibles = os.environ.get("RD_OPTION_CIBLES", "").split()
    sonder_systeme()
    sonder_disques(run_id)
    sonder_reseau(cibles, proxy)
    dossier = RACINE / run_id
    dossier.mkdir(parents=True, exist_ok=True)
    sonder_playwright(dossier, os.environ.get("RD_OPTION_INDEX_PIP", ""), proxy)
    rapporter("taille_dossier_essai", lancer(f"du -sh {dossier}")["sortie"])
    shutil.rmtree(dossier, ignore_errors=True)
    rapporter("fin", {"nettoye": not dossier.exists()})


if __name__ == "__main__":
    main()
