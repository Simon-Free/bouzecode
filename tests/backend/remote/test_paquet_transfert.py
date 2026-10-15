"""Paquet de transfert : reconstruire depuis le paquet redonne le meme arbre (vrais depots git)."""
import json
import subprocess
from pathlib import Path

from bouzecode.remote.paquet.paquet_transfert import construire_paquet
from bouzecode.remote.vm.vm_runner import reconstruire_projet


def git(depot: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=depot, check=True, capture_output=True, text=True).stdout.strip()


def ecrire(chemin: Path, texte: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(texte.encode("utf-8"))


def creer_depot(racine: Path) -> Path:
    racine.mkdir(parents=True)
    git(racine, "init", "-q", "-b", "travail")
    git(racine, "config", "user.email", "test@example.invalid")
    git(racine, "config", "user.name", "Test")
    git(racine, "config", "core.autocrlf", "false")
    ecrire(racine / "src" / "module.py", "VALEUR = 1\n")
    ecrire(racine / "README.md", "depot\n")
    git(racine, "add", "src/module.py", "README.md")
    git(racine, "commit", "-q", "-m", "premier")
    ecrire(racine / "src" / "module.py", "VALEUR = 2\n")
    git(racine, "commit", "-q", "-am", "second")
    return racine


def contenu_arbre(racine: Path) -> dict[str, bytes]:
    return {p.relative_to(racine).as_posix(): p.read_bytes() for p in sorted(racine.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(racine).parts}


def test_reconstruction_redonne_le_meme_arbre(tmp_path):
    depot = creer_depot(tmp_path / "projet")
    ecrire(depot / "src" / "module.py", "VALEUR = 3  # non commite\n")
    ecrire(depot / "donnees" / "jeu.csv", "a,b\n1,2\n")
    ecrire(depot / "notes.txt", "brouillon\n")
    attendu = contenu_arbre(depot)
    sha = git(depot, "rev-parse", "HEAD")

    manifeste = construire_paquet("bz_test_1", "tests", "pytest -q", {"projet": depot},
                                  {"projet": ["donnees/jeu.csv", "notes.txt"]}, tmp_path / "paquet")
    reconstruit, _ = reconstruire_projet(tmp_path / "paquet", manifeste["projets"][0], tmp_path / "vm")

    assert contenu_arbre(reconstruit) == attendu
    assert git(reconstruit, "rev-parse", "HEAD") == sha
    assert git(reconstruit, "rev-parse", "--abbrev-ref", "HEAD") == "bz/bz_test_1"
    assert git(reconstruit, "log", "--format=%s") == "second\npremier"


def test_manifeste_decrit_projets_et_refus(tmp_path):
    depot = creer_depot(tmp_path / "projet")
    ecrire(depot / ".env", "SECRET=1\n")
    (depot / "outil.exe").write_bytes(b"MZ")
    (depot / "gros.bin").write_bytes(b"0" * 2048)
    ecrire(depot / "ok.txt", "ok\n")

    manifeste = construire_paquet("bz_test_2", "agent", "echo", {"projet": depot},
                                  {"projet": [".env", "outil.exe", "gros.bin", "ok.txt", "../dehors.txt"]},
                                  tmp_path / "paquet", seuil_octets=1024)
    projet = manifeste["projets"][0]
    relu = json.loads((tmp_path / "paquet" / "manifeste.json").read_text(encoding="utf-8"))

    assert relu == manifeste
    assert projet["branche"] == "travail"
    assert projet["sha"] == git(depot, "rev-parse", "HEAD")
    assert projet["diff"] is None
    assert projet["fichiers_non_suivis"] == ["ok.txt"]
    assert {r["chemin"]: r["raison"] for r in projet["fichiers_refuses"]} == {
        ".env": "secret potentiel",
        "outil.exe": "executable interdit",
        "gros.bin": "trop gros (> 1024 octets)",
        "../dehors.txt": "chemin hors du depot",
    }
    reconstruit, _ = reconstruire_projet(tmp_path / "paquet", projet, tmp_path / "vm")
    assert not (reconstruit / ".env").exists()
    assert (reconstruit / "ok.txt").read_bytes() == b"ok\n"
