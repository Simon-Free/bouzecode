# [desc] testd : budget de workers pytest de la machine (8 par défaut), admission sensible à la charge (RAM, CPU via psutil), choix de `--dist worksteal` [/desc]
"""Le budget se compte en WORKERS, pas en runs : un run sans xdist coûte 1, un run `-n 3` en
coûte 3 ; aucun job n'en prend plus de 4. Les contextes navigateur sont une réserve à part
(`warm.browser_pool.ReserveDeContextes`).

Charge : psutil est déjà une dépendance de bouzecode. Sous 2 Go de RAM libre ou au-dessus de 90 %
de CPU en moyenne sur 5 s, aucun worker n'est accordé — sauf si rien ne tourne du tout, sinon
une machine chargée par d'autres process bloquerait la file pour toujours."""
from __future__ import annotations

import subprocess
import threading
from collections import deque

import psutil

from ..common import sans_fenetre

MAX_PAR_JOB = 4
_RAM_MIN = 2 * 1024 ** 3
_CPU_MAX = 90.0


class BudgetWorkers:
    def __init__(self, total: int) -> None:
        self.total = max(1, total)
        self.occupes = 0
        self._cond = threading.Condition()
        self._cpu = deque(maxlen=5)
        threading.Thread(target=self._mesurer_cpu, name="testd-cpu", daemon=True).start()

    def _mesurer_cpu(self) -> None:
        while True:
            self._cpu.append(psutil.cpu_percent(interval=1.0))

    def surcharge(self) -> str:
        """Raison de refuser un worker de plus ("" : la machine peut en prendre)."""
        libre = psutil.virtual_memory().available
        if libre < _RAM_MIN:
            return f"RAM libre {libre / 1024 ** 3:.1f} Go"
        cpu = sum(self._cpu) / len(self._cpu) if len(self._cpu) == self._cpu.maxlen else 0.0
        return f"CPU {cpu:.0f} %" if cpu > _CPU_MAX else ""

    def admettre(self, abandon) -> bool:
        """Bloque jusqu'à 1 worker libre (et une machine non surchargée, si quelque chose tourne
        déjà) ; le prend. False si `abandon()` devient vrai."""
        with self._cond:
            while self.occupes >= self.total or (self.occupes and self.surcharge()):
                if abandon():
                    return False
                self._cond.wait(0.5)
            self.occupes += 1
            return True

    def prendre_jusqu_a(self, nombre: int) -> int:
        """Prend jusqu'à `nombre` workers de plus SANS attendre ; rend combien."""
        with self._cond:
            if nombre <= 0 or self.surcharge():
                return 0
            accordes = min(nombre, self.total - self.occupes)
            self.occupes += accordes
            return accordes

    def rendre(self, nombre: int) -> None:
        with self._cond:
            self.occupes = max(0, self.occupes - nombre)
            self._cond.notify_all()

    def etat(self) -> str:
        raison = self.surcharge() if self.occupes else ""
        return f"{self.occupes}/{self.total} workers occupés" + (f", {raison}" if raison else "")


_VOL: dict[str, bool] = {}


def xdist_vole(python: str, env: dict) -> bool:
    """`--dist worksteal` existe-t-il (pytest-xdist ≥ 3.2) dans le python du projet ?"""
    if python not in _VOL:
        sonde = subprocess.run([python, "-c", "import xdist; print(xdist.__version__)"],
                               capture_output=True, text=True, env=env, timeout=60,
                               **sans_fenetre())
        morceaux = sonde.stdout.strip().split(".")[:2] if sonde.returncode == 0 else []
        _VOL[python] = len(morceaux) == 2 and all(m.isdigit() for m in morceaux) and \
            (int(morceaux[0]), int(morceaux[1])) >= (3, 2)
    return _VOL[python]
