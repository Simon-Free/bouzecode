"""Executeur cote VM (stdlib seule) : reconstruit les projets du paquet, lance la commande, depose le resultat.

Usage : python3.11 vm_runner.py <dossier_paquet> <dossier_travail> <dossier_resultat>
- reconstruction : worktree tire du clone GitLab en cache (`depots_vm`, + bundle incremental) ou,
  sans remote, `git clone` du bundle complet ; branche de travail au SHA local, `git apply` des
  modifications non commitees, extraction des fichiers non suivis ;
- execution : la commande du manifeste, dans le premier projet, variables BZ_RESULTAT/BZ_TRAVAIL ;
- resultat : sortie.log, resultat.json, captures (`test-results/`), et en mode agent un bundle
  `<slug>.resultat.bundle` des commits produits depuis le SHA de depart.
Le meme code sert localement (tests, `reconstruire_projet`) : aucune dependance hors stdlib.
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # depots_vm, depose a cote sur la VM
import depots_vm  # noqa: E402
from environnement_vm import IDENTITE_GIT, environnement_vm, preparer_navigateur  # noqa: E402,F401

DOSSIERS_CAPTURES = ("test-results", "playwright-report")
# Fiche de cloture que `bouzecode -p --result-file "$BZ_RESULTAT/reponse.md"` ecrit a cote de la
# reponse (ui/cloture_cli.py) : la raison de fin de l'agent, que le code de sortie seul ne dit pas
# (execution 257426 : refus du modele, code 0, classee livree sans un commit).
FICHE_CLOTURE = "reponse.cloture.json"
CHAMPS_CLOTURE = ("close_reason", "close_detail", "final_answer")
# Debris d'execution jamais commites par le commit automatique (depot sans .gitignore : execution
# 257422, les .pyc de pytest etaient revenus dans agent/<ticket>).
EXCLUSIONS_AUTO_COMMIT = tuple(f":(exclude,glob){motif}" for motif in (
    "**/__pycache__/**", "**/*.pyc", "**/.pytest_cache/**", "**/.venv/**", "**/node_modules/**"))



def git(*arguments, cwd=None):
    return subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True,
                          env=dict(os.environ, **IDENTITE_GIT)).stdout.strip()


def extraire_archive(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for membre in tar.getmembers():
            cible = (destination / membre.name).resolve()
            if not membre.isfile() or destination.resolve() not in cible.parents:
                raise ValueError(f"entree d'archive refusee : {membre.name}")
        tar.extractall(destination, filter="data")


def reconstruire_projet(dossier_paquet: Path, projet: dict, destination: Path, run_id: str = "local") -> tuple[Path, dict]:
    """(depot reconstruit, trace a passer a `nettoyer_projet`)."""
    if projet.get("source") == "remote":
        depot, trace = depots_vm.worktree_depuis_cache(dossier_paquet, projet, destination, run_id)
    else:
        depot, trace = _clone_du_bundle(dossier_paquet, projet, destination), {}
    if projet.get("diff"):
        git("apply", "--whitespace=nowarn", str((dossier_paquet / projet["diff"]).resolve()), cwd=depot)
    if projet.get("archive_non_suivis"):
        extraire_archive(dossier_paquet / projet["archive_non_suivis"], depot)
    return depot, trace


def nettoyer_projet(projet: dict, depot: Path, trace: dict) -> None:
    if trace:
        depots_vm.retirer_worktree(projet, depot, trace)


def _clone_du_bundle(dossier_paquet: Path, projet: dict, destination: Path) -> Path:
    depot = destination / projet["slug"]
    git("clone", "--quiet", "--no-checkout", "-c", "core.autocrlf=false", str(dossier_paquet / projet["bundle"]), str(depot))
    git("checkout", "--quiet", "-B", projet["branche_travail"], projet["sha"], cwd=depot)
    return depot


def copier_captures(depot: Path, resultat: Path) -> list[str]:
    copies = []
    for nom in DOSSIERS_CAPTURES:
        if (depot / nom).is_dir():
            shutil.copytree(depot / nom, resultat / "captures" / nom, dirs_exist_ok=True)
            copies.append(nom)
    return copies


def commiter_reste(depot: Path, projet: dict) -> list[str]:
    """Commite ce que l'agent a laisse en plan, SAUF les fichiers non suivis transmis (non suivis en local)."""
    git("add", "-A", "--", ".", *EXCLUSIONS_AUTO_COMMIT, cwd=depot)
    if projet.get("fichiers_non_suivis"):
        git("reset", "-q", "--", *projet["fichiers_non_suivis"], cwd=depot)
    indexe = git("diff", "--cached", "--name-only", cwd=depot).splitlines()
    if indexe:
        git("commit", "-q", "-m", "bz: travail non commite de l'agent distant", cwd=depot)
    return indexe


def exporter_commits(depot: Path, projet: dict, resultat: Path) -> dict:
    auto_commites = commiter_reste(depot, projet)
    head = git("rev-parse", "HEAD", cwd=depot)
    sortie = {"sha_depart": projet["sha"], "sha_fin": head, "bundle": None, "auto_commites": auto_commites}
    if head != projet["sha"]:
        nom = f"{projet['slug']}.resultat.bundle"
        git("bundle", "create", str(resultat / nom), projet["branche_travail"], f"^{projet['sha']}", cwd=depot)
        sortie["bundle"] = nom
    return sortie


def executer_commande(commande: str, depot: Path, env: dict, resultat: Path, delai_s: int) -> dict:
    debut = time.monotonic()
    with open(resultat / "sortie.log", "w", encoding="utf-8") as journal:
        try:
            code = subprocess.run(commande, shell=True, cwd=depot, env=env, stdout=journal,
                                  stderr=subprocess.STDOUT, timeout=delai_s).returncode
        except subprocess.TimeoutExpired:
            code = "delai_depasse"
    return {"code": code, "duree_s": round(time.monotonic() - debut, 1)}


def lire_cloture(resultat: Path) -> dict:
    """Les champs de la fiche de cloture de l'agent, ou {} s'il n'en a pas ecrit."""
    fiche = resultat / FICHE_CLOTURE
    if not fiche.is_file():
        return {}
    donnees = json.loads(fiche.read_text(encoding="utf-8"))
    return {champ: donnees[champ] for champ in CHAMPS_CLOTURE if champ in donnees}


def executer_paquet(dossier_paquet: Path, travail: Path, resultat: Path) -> dict:
    manifeste = json.loads((dossier_paquet / "manifeste.json").read_text(encoding="utf-8"))
    travail.mkdir(parents=True, exist_ok=True)
    resultat.mkdir(parents=True, exist_ok=True)
    reconstruits = []
    try:  # un projet qui echoue a la reconstruction ne laisse pas les worktrees des precedents
        for projet in manifeste["projets"]:
            reconstruits.append(reconstruire_projet(dossier_paquet, projet, travail, manifeste["run_id"]))
        bilan = _executer(manifeste, dossier_paquet, travail, resultat, [depot for depot, _ in reconstruits])
    finally:
        for projet, (depot, trace) in zip(manifeste["projets"], reconstruits):
            nettoyer_projet(projet, depot, trace)
    # Comment chaque depot a ete obtenu : "clone" / "fetch" du cache GitLab, ou "bundle_complet".
    bilan["sources"] = {p["slug"]: trace.get("geste", "bundle_complet")
                        for p, (_, trace) in zip(manifeste["projets"], reconstruits)}
    (resultat / "resultat.json").write_text(json.dumps(bilan, indent=2), encoding="utf-8")
    return bilan


def _executer(manifeste: dict, dossier_paquet: Path, travail: Path, resultat: Path, depots: list[Path]) -> dict:
    env = dict(environnement_vm(travail, resultat), BZ_PAQUET=str(dossier_paquet))
    variables_navigateur = preparer_navigateur(resultat) if manifeste.get("navigateur") else {}
    if variables_navigateur is None:
        bilan = {"code": "navigateur_indisponible", "duree_s": 0}
    else:
        env.update(variables_navigateur)
        bilan = executer_commande(manifeste["commande"], depots[0], env, resultat, int(manifeste.get("delai_s", 3600)))
    bilan["mode"] = manifeste["mode"]
    bilan["captures"] = copier_captures(depots[0], resultat)
    bilan["junit"] = (resultat / "junit.xml").exists()
    if manifeste["mode"] == "agent":
        bilan.update(lire_cloture(resultat))
        bilan["projets"] = {p["slug"]: exporter_commits(d, p, resultat)
                            for p, d in zip(manifeste["projets"], depots) if not p.get("outil")}
    return bilan


def main(arguments: list[str]) -> int:
    dossier_paquet, travail, resultat = (Path(a) for a in arguments[:3])
    try:  # dossier de run retire meme si la reconstruction echoue (execution 257448 : il restait)
        bilan = executer_paquet(dossier_paquet, travail, resultat)
    finally:
        shutil.rmtree(travail, ignore_errors=True)
    print("BZ_RESULTAT|" + json.dumps(bilan), flush=True)
    return 0 if bilan["code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
