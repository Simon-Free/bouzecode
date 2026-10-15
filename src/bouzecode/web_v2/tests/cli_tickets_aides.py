# [desc] Aides des tests de `bouzecode tickets|projets` : dépôt git de démonstration enregistré, exécution de la CLI en process (sortie, code), JSON de la sortie. [/desc]
from __future__ import annotations

import json
import subprocess

from bouzecode.ui import tickets_cli
from bouzecode.web_v2.services.work import projects


def git(depot, *arguments) -> str:
    return subprocess.run(["git", *arguments], cwd=depot, check=True, capture_output=True,
                          text=True).stdout.strip()


def depot_demo(tmp_path, slug: str = "demo"):
    """Un dépôt git enregistré sous `slug`, avec un fichier non suivi utile et un secret."""
    chemin = tmp_path / slug
    chemin.mkdir()
    git(chemin, "init", "-q", "-b", "main")
    git(chemin, "config", "user.email", "t@example.invalid")
    git(chemin, "config", "user.name", "T")
    (chemin / "a.txt").write_text("a\n", encoding="utf-8")
    git(chemin, "add", "a.txt")
    git(chemin, "commit", "-q", "-m", "initial")
    (chemin / "notes").mkdir()
    (chemin / "notes" / "plan.md").write_text("le plan\n", encoding="utf-8")
    (chemin / ".env").write_text("SECRET=1\n", encoding="utf-8")
    existants = json.loads(projects.PROJECTS_PATH.read_text(encoding="utf-8")) \
        if projects.PROJECTS_PATH.is_file() else []
    projects.PROJECTS_PATH.write_text(json.dumps(existants + [
        {"slug": slug, "name": slug, "path": str(chemin)}]), encoding="utf-8")
    return chemin


def cli(capsys, *argv: str) -> tuple[int, str, str]:
    """`bouzecode <argv>` en process : (code de sortie, stdout, stderr)."""
    capsys.readouterr()
    code = tickets_cli.main(list(argv))
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def cli_json(capsys, *argv: str) -> tuple[int, dict]:
    code, sortie, _ = cli(capsys, *argv, "--json")
    return code, json.loads(sortie)
