# [desc] testd : créneaux navigateur de la machine — au plus N sous-runs navigateur à la fois (2 par défaut), servis dans l'ordre d'arrivée, position visible [/desc]
"""Session B4 (2026-10-14) : 18 jobs, `queued_s = 0` partout, alors que 4 sous-agents jouaient
leurs tests navigateur en même temps et que chacun allait 2 à 4 fois moins vite (8,7 s seul,
152 s en concurrence). Le budget compte des WORKERS xdist ; un test navigateur coûte bien plus
qu'un worker (navigateur, serveur applicatif, rendu). Ici le nombre de sous-runs navigateur
simultanés est borné pour toute la machine, quel que soit leur `-n` ; les contextes
(`warm.browser_pool.ReserveDeContextes`) restent bornés à part."""
from __future__ import annotations

import threading


class CreneauxNavigateur:
    def __init__(self, total: int) -> None:
        self.total = max(1, total)
        self._file: list[str] = []      # jobs en attente, dans l'ordre d'arrivée
        self._actifs: set[str] = set()
        self._cond = threading.Condition()

    def prendre(self, job_id: str, abandon) -> bool:
        """Bloque jusqu'à un créneau libre ET son tour ; False si `abandon()` devient vrai."""
        with self._cond:
            self._file.append(job_id)
            while self._file[0] != job_id or len(self._actifs) >= self.total:
                if abandon():
                    self._file.remove(job_id)
                    self._cond.notify_all()
                    return False
                self._cond.wait(0.5)
            self._file.pop(0)
            self._actifs.add(job_id)
            self._cond.notify_all()
            return True

    def rendre(self, job_id: str) -> None:
        with self._cond:
            self._actifs.discard(job_id)
            self._cond.notify_all()

    def position(self, job_id: str) -> int:
        """Rang du job dans l'attente d'un créneau (0 : il n'attend pas)."""
        with self._cond:
            return self._file.index(job_id) + 1 if job_id in self._file else 0

    def etat(self) -> str:
        with self._cond:
            return (f"{len(self._actifs)}/{self.total} jobs navigateur en cours, "
                    f"{len(self._file)} en attente")
