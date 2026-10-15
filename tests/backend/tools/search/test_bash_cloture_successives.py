# [desc] Deux agents successifs dans le même processus : chacun arrête à sa clôture ce que SES Bash ont lancé, même après un premier balayage (le balayage ne se fait que si un Bash a tourné depuis le précédent). [/desc]
"""`arreter_processus_lances` ne relit plus l'environnement de tout le poste à chaque clôture :
seulement si un Bash a été lancé depuis le balayage précédent. Ce qu'il faut garantir : une
2e clôture, après un 1er balayage, arrête encore ce que le 2e agent a lancé.

Multi-plateforme (le voisin `test_bash_processus_a_la_cloture` exige un shell POSIX) : le
témoin est un script Python lancé en fond qui signale son démarrage par un fichier ; un Bash
au premier plan attend ce fichier, pour que la clôture trouve le témoin DÉJÀ vivant."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil
import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

TEMOIN = "import pathlib, sys, time\npathlib.Path(sys.argv[1]).touch()\ntime.sleep(600)\n"
ATTENTE = ("import pathlib, sys, time\nfin = time.time() + 10\n"
           "while not pathlib.Path(sys.argv[1]).exists() and time.time() < fin:\n"
           "    time.sleep(0.05)\n")


def _processus(marque: str) -> list[psutil.Process]:
    trouves = []
    for proc in psutil.process_iter(["name"]):
        if not str(proc.info.get("name") or "").lower().startswith("python"):
            continue
        cmdline = proc.as_dict(["cmdline"], ad_value=None).get("cmdline") or []
        if any(marque in str(arg) for arg in cmdline):
            trouves.append(proc)
    return trouves


def _disparu(marque: str, limite: float = 10.0) -> bool:
    fin = time.time() + limite
    while time.time() < fin:
        if not _processus(marque):
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def menage():
    marques: list[str] = []
    yield marques
    for marque in marques:
        for proc in _processus(marque):
            proc.kill()


def _bash(ident: str, commande: str, fond: bool) -> str:
    extra = '<param name="background">true</param>' if fond else ""
    return (f'<tool_use name="Bash" id="{ident}"><param name="command">{commande}</param>'
            f'{extra}</tool_use>')


def _agent_qui_lance_en_fond(dossier: Path) -> str:
    """Un agent lance le témoin en fond, attend qu'il tourne, puis clôt. Rend sa marque."""
    dossier.mkdir()
    temoin, attente, pret = dossier / "temoin.py", dossier / "attente.py", dossier / "pret"
    temoin.write_text(TEMOIN, encoding="utf-8")
    attente.write_text(ATTENTE, encoding="utf-8")
    #  Sous Windows l'outil Bash passe par PowerShell : un exécutable entre guillemets s'y
    #  appelle par l'opérateur `&`.
    python = ("& " if sys.platform == "win32" else "") + f'"{Path(sys.executable).as_posix()}"'
    mock = MockLLM([
        _bash("b1", f'{python} "{temoin.as_posix()}" "{pret.as_posix()}"', fond=True)
        + _bash("b2", f'{python} "{attente.as_posix()}" "{pret.as_posix()}"', fond=False),
        "Le serveur tourne, j'ai fini.",
    ])
    bouzecode(["lance un serveur de test puis termine"], mock_llm=mock)
    assert pret.exists(), "le témoin n'a jamais démarré"
    return temoin.as_posix()


def test_chaque_cloture_arrete_ce_que_ses_bash_ont_lance(menage, tmp_path, capsys):
    for rang in ("1re", "2e"):
        menage.append((tmp_path / rang / "temoin.py").as_posix())
        marque = _agent_qui_lance_en_fond(tmp_path / rang)
        #  La clôture annonce ce qu'elle a arrêté.
        assert "processus lancés par Bash arrêtés" in capsys.readouterr().out, \
            f"{rang} clôture : rien d'arrêté"
        assert _disparu(marque), f"{rang} clôture : le Bash de fond survit"
