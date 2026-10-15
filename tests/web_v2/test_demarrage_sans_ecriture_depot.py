# [desc] Démarrer un agent web dans un dépôt git n'y crée aucun fichier (régression AGENTS.md non suivi). [/desc]
"""Un démarrage d'agent n'écrit JAMAIS dans le dépôt de l'utilisateur.

Vu en réel : l'assistant du Bureau, lancé dans le checkout principal d'un dépôt de
l'utilisateur, y a trouvé un `AGENTS.md` NON SUIVI qu'il n'avait pas écrit. Il en a déduit
qu'« un autre agent écrivait déjà dans le dépôt », et l'agent racine a été isolé en
worktree à tort. L'auteur était la boucle IPC elle-même : avant chaque tour, elle lançait
le hook `readme_sync` qui peignait une carte `AGENTS.md` à la racine du cwd.

Le test passe par le vrai chemin de démarrage d'un agent web (`run_agent_event_loop`),
cwd = un dépôt git temporaire, et un vrai tour d'agent joué par `MockLLM`.
"""
from __future__ import annotations

import subprocess

from bouzecode.web_v2.runtime.ipc import from_dir, run_agent_event_loop
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def _depot_utilisateur(racine):
    """Un petit dépôt propre, avec du code dans un sous-dossier comme un vrai projet."""
    (racine / "jeu").mkdir()
    (racine / "jeu" / "enigme.py").write_text("def resoudre():\n    return 42\n")
    (racine / "README.md").write_text("# Portail\n")
    subprocess.run([*GIT, "init", "-q"], cwd=racine, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=racine, check=True)
    subprocess.run([*GIT, "commit", "-qm", "init"], cwd=racine, check=True)


def test_demarrer_un_agent_ne_cree_aucun_fichier_dans_le_depot(tmp_path, monkeypatch):
    depot = tmp_path / "portail"
    depot.mkdir()
    _depot_utilisateur(depot)
    monkeypatch.chdir(depot)
    monkeypatch.delenv("BOUZECODE_README_SYNC", raising=False)  # réglage par défaut
    ipc_dir = tmp_path / "ipc"
    ipc_dir.mkdir()

    run_agent_event_loop(
        "bonjour",
        lambda prompt: bouzecode([prompt], mock_llm=MockLLM(["Bonjour."])),
        from_dir(str(ipc_dir)),
        keep_warm=False,
    )

    statut = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                            cwd=depot, capture_output=True, text=True, check=True).stdout
    assert statut == "", f"le démarrage de l'agent a écrit dans le dépôt :\n{statut}"
