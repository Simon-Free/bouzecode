# [desc] Sérialise les tests qui lancent un pytest IMBRIQUÉ : un seul à la fois, tous workers xdist confondus. [/desc]
"""Ces tests-là ne se contentent pas de tourner : ils LANCENT un pytest complet.

`RunPythonTest` exécute `uv run --no-sync … pytest <fichier>` dans un sous-process et lit sa
sortie au fil de l'eau. Chaque test de ce répertoire paie donc un démarrage d'uv + un
démarrage de pytest, et se juge sur du TEMPS MURAL : « la barre atteint-elle 5/5 avant le
timeout ». Sous `-n auto`, seize workers font ça en même temps, sur une machine qui fait déjà
tourner le serveur web_v2 et ses agents. Les sous-process sont alors affamés de CPU et
dépassent leur budget de 60 s.

Mesuré le 2026-07-30 : ce répertoire passe en 31 s machine au repos, et sort 6 rouges en
146 s sous charge. Chaque test échouait SEUL au hasard des runs — d'où trois diagnostics
successifs de « flake ». Ce n'en était pas un : c'était de la contention, reproductible dès
qu'on regarde la bonne chose.

Le remède est de retirer la CAUSE, pas d'élargir le budget. Élargir le timeout aurait rendu
le vert dépendant de la charge du moment et masqué une vraie régression de lenteur le jour où
elle arriverait ; sérialiser rend chaque sous-process aussi rapide qu'en isolation, et le
budget de 60 s redevient ce qu'il doit être — un garde-fou contre un blocage, pas une course.

Le verrou est un FICHIER, pas un `threading.Lock` : les workers xdist sont des PROCESSUS
distincts, un verrou mémoire ne les verrait pas.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

_LOCK_PATH = Path(tempfile.gettempdir()) / "bouzecode_nested_pytest.lock"

# Attente maximale avant de passer OUTRE. On ne bloque JAMAIS la suite : si le verrou n'est
# pas libéré (worker tué, machine saturée), on laisse le test tourner et il redevient ce
# qu'il était — sensible à la charge. Un test lent est un défaut ; une suite qui ne rend
# jamais la main en est un pire.
_MAX_WAIT_S = 240.0

# Un verrou plus vieux que ça appartient à un process mort : on le reprend. Calé au-dessus du
# budget d'un run imbriqué (60 s) pour ne jamais voler le verrou d'un test encore en cours.
_STALE_AFTER_S = 180.0


def _acquire() -> bool:
    """Prend le verrou, ou rend False au bout de `_MAX_WAIT_S`."""
    deadline = time.monotonic() + _MAX_WAIT_S
    while True:
        try:
            fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                perime = (time.time() - _LOCK_PATH.stat().st_mtime) > _STALE_AFTER_S
            except FileNotFoundError:
                continue  # libéré entre-temps : on retente immédiatement
            if perime:
                _release()  # verrou d'un process mort
                continue
            if time.monotonic() > deadline:
                return False
            time.sleep(0.2)


def _release() -> None:
    try:
        _LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def _un_seul_pytest_imbrique_a_la_fois():
    """Un seul test de ce répertoire lance un pytest imbriqué à la fois."""
    pris = _acquire()
    try:
        yield
    finally:
        if pris:
            _release()
