# [desc] Tests du contrat env.json (canal IPC agent→serveur) : merge, atomicité, champs validés, lecture tolérante [/desc]
"""L'agent est un process séparé : quand il se provisionne un worktree en vol, le serveur
continue de croire à l'ancien `cwd` et la première reprise repart au mauvais endroit. Ces
tests fixent le contrat du fichier `env.json` déposé dans le dossier IPC déjà existant
(celui où `plan_mode` écrit `plan.md`) : pas de second canal, pas de socket.

Aucun mock : de vrais dossiers temporaires et de vrais fichiers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime import env_signal


def test_ce_que_l_agent_ecrit_le_serveur_le_relit(tmp_path: Path) -> None:
    assert env_signal.write(str(tmp_path), cwd=str(tmp_path / "wt"),
                            worktree_root=str(tmp_path / "wt")) is True
    assert env_signal.read(str(tmp_path)) == {
        "cwd": str(tmp_path / "wt"), "worktree_root": str(tmp_path / "wt")}
    assert env_signal.path(str(tmp_path)) == tmp_path / "env.json"


def test_le_venv_demande_plus_tard_n_efface_pas_le_worktree_deja_signale(tmp_path: Path) -> None:
    """L'action `venv` n'écrit que `base_venv`, APRÈS que l'action `worktree` a écrit le cwd :
    une écriture qui remplacerait le fichier ferait oublier au serveur le déplacement."""
    env_signal.write(str(tmp_path), cwd="/w/t", worktree_root="/w/t")
    env_signal.write(str(tmp_path), base_venv="/w/t/.venv")
    assert env_signal.read(str(tmp_path)) == {
        "cwd": "/w/t", "worktree_root": "/w/t", "base_venv": "/w/t/.venv"}


def test_aucun_fichier_temporaire_ne_traine(tmp_path: Path) -> None:
    """Écriture tmp + os.replace : le serveur ne doit jamais lire un JSON à moitié écrit,
    et le dossier IPC ne doit pas se remplir de résidus."""
    env_signal.write(str(tmp_path), cwd="/w/t")
    env_signal.write(str(tmp_path), cwd="/w/t2")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["env.json"]


def test_sans_dossier_ipc_l_agent_n_echoue_pas(tmp_path: Path) -> None:
    """Un agent lancé hors serveur web n'a pas de dossier IPC : signaler n'est alors pas
    une erreur, c'est un no-op — sinon l'outil planterait en CLI."""
    assert env_signal.write("", cwd="/w/t") is False
    assert env_signal.read("") == {}


def test_un_fichier_illisible_ne_casse_pas_la_reprise(tmp_path: Path) -> None:
    """Le serveur relit ce fichier sur le chemin de reprise : un JSON tronqué (crash pendant
    l'écriture, disque plein) doit dégrader vers « je ne sais rien », jamais lever."""
    (tmp_path / "env.json").write_text("{ tronq", encoding="utf-8")
    assert env_signal.read(str(tmp_path)) == {}
    assert env_signal.read(str(tmp_path / "absent")) == {}


def test_un_champ_inconnu_est_refuse_tout_de_suite(tmp_path: Path) -> None:
    """Le serveur n'adopte qu'un jeu de champs connu. Une faute de frappe côté agent doit
    éclater à l'écriture, pas se perdre en silence dans un fichier que personne ne lit."""
    with pytest.raises(ValueError):
        env_signal.write(str(tmp_path), cw="/w/t")
    assert not (tmp_path / "env.json").exists()


def test_le_fichier_est_du_json_lisible_a_l_oeil(tmp_path: Path) -> None:
    """Ce fichier est un outil de diagnostic humain quand une reprise repart au mauvais
    endroit : il doit s'ouvrir et se lire, pas se décoder."""
    env_signal.write(str(tmp_path), cwd="/w/t")
    texte = (tmp_path / "env.json").read_text(encoding="utf-8")
    assert json.loads(texte) == {"cwd": "/w/t"}
    assert "\n" in texte
