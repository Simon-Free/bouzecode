"""Construit le paquet de transfert d'une execution distante, dans un dossier local.

Par projet : `<slug>.bundle` — INCREMENTAL (commits locaux absents du remote GitLab, que la VM
clone en cache) ou complet si le depot n'a pas de remote joignable (cf. `source_git`) —,
`<slug>.diff` (modifications suivies non commitees, s'il y en a), `<slug>.non_suivis.tar.gz`
(fichiers non suivis acceptes par `filtre_fichiers`). Plus `manifeste.json` : projets,
branches, SHA, fichiers transmis et refuses, commande, mode. La reconstruction est faite par
`bouzecode.remote.vm.vm_runner.reconstruire_projet` (le meme code tourne sur la VM).
"""
import json
import subprocess
import tarfile
from pathlib import Path

from bouzecode.remote.paquet import source_git
from bouzecode.remote.paquet.filtre_fichiers import SEUIL_OCTETS_DEFAUT, trier_fichiers_non_suivis
from bouzecode.web_v2.services.horodatage import maintenant_iso

MODES = ("agent", "tests")


def _git(depot: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=depot, check=True, capture_output=True, text=True).stdout.strip()


def _ecrire_diff(depot: Path, destination: Path) -> bool:
    diff = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=depot, check=True, capture_output=True).stdout
    if not diff:
        return False
    destination.write_bytes(diff)
    return True


def _ecrire_archive(depot: Path, chemins: list[str], destination: Path) -> None:
    with tarfile.open(destination, "w:gz") as tar:
        for chemin in chemins:
            tar.add(depot / chemin, arcname=chemin, recursive=False)


def preparer_projet(slug: str, depot: Path, non_suivis: list[str], dossier: Path, branche_travail: str,
                    seuil_octets: int, via_remote: bool = True) -> dict:
    branche = _git(depot, "rev-parse", "--abbrev-ref", "HEAD")
    sha = _git(depot, "rev-parse", "HEAD")
    source = source_git.analyser(depot) if via_remote else {"source": "bundle_complet",
                                                            "raison": "jeton GitLab absent du poste"}
    projet = {"slug": slug, "branche": branche, "sha": sha, "branche_travail": branche_travail,
              "bundle": f"{slug}.bundle", "diff": None, "archive_non_suivis": None, **source}
    projet["ref_bundle"] = source_git.ecrire_bundle(depot, branche, source, dossier / projet["bundle"])
    if projet["ref_bundle"] is None:
        projet["bundle"] = None  # HEAD deja sur le remote : rien a transporter
    projet["octets_bundle"] = (dossier / projet["bundle"]).stat().st_size if projet["bundle"] else 0
    if _ecrire_diff(depot, dossier / f"{slug}.diff"):
        projet["diff"] = f"{slug}.diff"
    tri = trier_fichiers_non_suivis(depot, non_suivis, seuil_octets)
    if tri.acceptes:
        projet["archive_non_suivis"] = f"{slug}.non_suivis.tar.gz"
        _ecrire_archive(depot, tri.acceptes, dossier / projet["archive_non_suivis"])
    projet["fichiers_non_suivis"] = tri.acceptes
    projet["fichiers_refuses"] = tri.refuses
    return projet


def construire_paquet(run_id: str, mode: str, commande: str, projets: dict[str, Path],
                      fichiers_non_suivis: dict[str, list[str]], dossier: Path,
                      seuil_octets: int = SEUIL_OCTETS_DEFAUT, delai_s: int = 3600, navigateur: bool = False,
                      outils: set[str] = frozenset(), branche_travail: str = "", via_remote: bool = True) -> dict:
    """`projets` : {slug: chemin du depot} ; le premier est celui ou la commande s'execute.
    `outils` : projets transmis pour OUTILLER la VM (bouzecode lui-meme) : jamais rapatries.
    `branche_travail` : branche creee sur la VM au SHA local (`agent/<ticket>`, defaut `bz/<run_id>`).
    `via_remote` faux : bundle complet pour tous (pas de jeton GitLab pour cloner sur la VM)."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} inconnu, attendu un de {MODES}")
    dossier.mkdir(parents=True, exist_ok=True)
    manifeste = {
        "version": 1, "run_id": run_id, "mode": mode, "commande": commande, "delai_s": delai_s,
        "navigateur": navigateur,
        "cree_le": maintenant_iso(),
        "projets": [preparer_projet(slug, Path(depot), fichiers_non_suivis.get(slug, []), dossier,
                                    branche_travail or f"bz/{run_id}", seuil_octets, via_remote)
                    for slug, depot in projets.items()],
    }
    for projet in manifeste["projets"]:
        projet["outil"] = projet["slug"] in outils
    (dossier / "manifeste.json").write_text(json.dumps(manifeste, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifeste
