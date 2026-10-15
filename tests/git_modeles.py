# [desc] Dépôts git de test bon marché : modèle construit une fois par worker puis copié, commits en masse en un seul lancement git. [/desc]
"""Mise en place des dépôts git de test avec le moins possible de lancements `git`.

Mesuré le 2026-09-30 sur la suite par défaut : 1 462 lancements de `git` pour 417 s d'attente
cumulée (100 à 300 ms par lancement sur ce poste, antivirus compris), soit 35 % du temps de la
suite — pour l'essentiel à refabriquer, test après test, le MÊME dépôt de départ.

Deux leviers, qui ne touchent qu'à la mise en place (ce que le test vérifie tourne toujours sur
du vrai git) :

- `depot_modele` : le dépôt de départ est construit UNE fois par worker (xdist compris) puis copié
  par test (`shutil.copytree`, ~40 ms) — chaque test a sa copie, aucun dépôt partagé n'est muté ;
- `ecrire_commits` : N commits en UN lancement (`git fast-import`) au lieu de 2 × N
  (`add` + `commit`). Les commits sont de vrais commits ; seul l'arbre de travail n'est pas
  réécrit (le checkout courant n'est pas touché).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def depot_modele(tmp_path_factory):
    """Rend `copier(dest, construire, *args)` : copie dans `dest` le dépôt que
    `construire(chemin, *args)` fabrique dans un dossier vide — construit une seule fois
    par worker et par couple (construire, args), puis recopié à chaque appel."""
    modeles: dict = {}

    def copier(dest, construire, *args) -> Path:
        cle = (construire, args)
        if cle not in modeles:
            modele = tmp_path_factory.mktemp("depot_modele") / "depot"
            modele.mkdir()
            construire(modele, *args)
            modeles[cle] = modele
        # Les `hooks/*.sample` de `git init` sont inertes : ne pas les recopier à chaque test.
        shutil.copytree(modeles[cle], dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.sample"))
        return Path(dest)

    return copier


def _bloc_data(texte: str) -> bytes:
    contenu = texte.encode("utf-8")
    return b"data %d\n" % len(contenu) + contenu + b"\n"


def ecrire_commits(depot, branche: str, depart: str, commits: list[tuple[str, dict[str, str]]],
                   *, auteur: str = "t <t@t.io>") -> None:
    """Écrit `commits` — liste de (message, {chemin: contenu}) — sur `branche`, à partir de
    `depart` (réf ou SHA), en UN lancement de `git fast-import`. La branche est créée ou
    réinitialisée comme un `git checkout -B branche depart` suivi d'un commit par élément ;
    chaque commit hérite de l'arbre du précédent, comme un `git add -A` successif."""
    horodatage = f"{int(time.time())} +0000"
    flux = bytearray()
    for index, (message, fichiers) in enumerate(commits):
        flux += f"commit refs/heads/{branche}\ncommitter {auteur} {horodatage}\n".encode()
        flux += _bloc_data(message)
        if index == 0:
            flux += f"from {depart}\n".encode()
        for chemin, contenu in fichiers.items():
            flux += f"M 100644 inline {chemin}\n".encode("utf-8") + _bloc_data(contenu)
        flux += b"\n"
    res = subprocess.run(["git", "-C", str(depot), "fast-import", "--quiet", "--force"],
                         input=bytes(flux), capture_output=True, timeout=60)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")


def git(depot, *args) -> str:
    """Un lancement git qui DOIT réussir ; rend sa sortie standard nettoyée."""
    res = subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=120)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}\n{res.stderr}"
    return res.stdout.strip()


def livraison_non_integree(racine: Path, base: str, branche: str) -> None:
    """`base` (1 commit) et `branche` (1 commit de plus), `base` extraite, identité en config
    locale : la situation d'un ticket dont la branche porte du travail jamais intégré."""
    git(racine, "init", "-b", base)
    git(racine, "config", "user.email", "bureau@test")
    git(racine, "config", "user.name", "Bureau")
    (racine / "a.txt").write_text("un", encoding="utf-8")
    git(racine, "add", "a.txt")
    git(racine, "commit", "-m", "base")
    git(racine, "checkout", "-b", branche)
    (racine / "b.txt").write_text("deux", encoding="utf-8")
    git(racine, "add", "b.txt")
    git(racine, "commit", "-m", "travail livre")
    git(racine, "checkout", base)


def develop_un_commit(racine: Path) -> None:
    """`develop` avec un seul commit (`f.txt` = « A »), sans identité en config locale."""
    git(racine, "init", "-q", "-b", "develop")
    (racine / "f.txt").write_text("A\n", encoding="utf-8")
    git(racine, "add", "-A")
    git(racine, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "A")
