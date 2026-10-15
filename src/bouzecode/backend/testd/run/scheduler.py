# [desc] testd : file d'attente des jobs pytest de tous les agents, admise sur le budget de workers de la machine, instantané d'un job pour le client [/desc]
"""Mesuré le 2026-10-13 : 20 sessions lançaient pytest + Chromium en même temps, un démarrage de
navigateur a pris 9 min. Un job n'est admis (dans l'ordre d'arrivée) que si un worker du budget
de la machine est libre (`budget.workers`) ; au-delà, il attend et le client voit sa position et
la charge du budget."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

from ..common import tuer_arbre
from .job import Job, executer

_journal = logging.getLogger("testd")


class Ordonnanceur:
    def __init__(self, ressources, dossier: Path) -> None:
        self._file: list[Job] = []
        self.jobs: dict[str, Job] = {}
        self._cond = threading.Condition()
        self._en_cours = 0
        self._ressources = ressources
        self._dossier = dossier
        self.derniere_activite = time.time()
        threading.Thread(target=self._distribuer, name="testd-file", daemon=True).start()

    def soumettre(self, cmd: list[str], env: dict, cwd: str, timeout: int, python: str,
                  cibles=(), base: dict | None = None, a_nettoyer=()) -> Job:
        job_id = uuid.uuid4().hex[:8]
        dossier = self._dossier / "jobs" / job_id
        dossier.mkdir(parents=True, exist_ok=True)
        job = Job(cmd=cmd, env=env, cwd=cwd, timeout=timeout, python=python or cmd[0], dossier=dossier,
                  id=job_id, cibles=list(cibles), base=base, a_nettoyer=list(a_nettoyer))
        with self._cond:
            self.jobs[job.id] = job
            self._file.append(job)
            self.derniere_activite = time.time()
            self._cond.notify()
        _journal.info("job %s soumis (cwd=%s) : %s", job.id, cwd, " ".join(cmd))
        #  Worktree neuf : ses fichiers sont lus en arrière-plan dès maintenant (cf. warm.prechauffage).
        prechauffage = getattr(self._ressources, "prechauffage", None)
        if prechauffage:
            prechauffage.demander(cwd, job.python)
        return job

    def position(self, job: Job) -> int:
        with self._cond:
            return self._file.index(job) + 1 if job in self._file else 0

    def inactif_depuis(self) -> float:
        with self._cond:
            if self._file or self._en_cours:
                return 0.0
            return time.time() - self.derniere_activite

    def annuler(self, job: Job) -> None:
        job.annule = True
        with self._cond:
            if job in self._file:
                self._file.remove(job)
                job.etat = "cancelled"
                self._clore(job)
        for proc in list(job.procs):
            tuer_arbre(proc.pid)

    def tout_annuler(self) -> None:
        for job in list(self.jobs.values()):
            if job.etat in ("queued", "running"):
                self.annuler(job)

    def _distribuer(self) -> None:
        """Admet la tête de file dès qu'un worker se libère (elle y reste en attendant)."""
        while True:
            with self._cond:
                while not self._file:
                    self._cond.wait()
                tete = self._file[0]
            if not self._ressources.workers.admettre(lambda: tete not in self._file):
                continue  # annulée pendant l'attente
            with self._cond:
                annulee = tete not in self._file
                if not annulee:
                    self._file.remove(tete)
                    self._en_cours += 1
            if annulee:  # annulée entre l'admission et la sortie de file
                self._ressources.workers.rendre(1)
                continue
            tete.workers = 1
            threading.Thread(target=self._executer, args=(tete,), name=f"testd-{tete.id}", daemon=True).start()

    def _executer(self, job: Job) -> None:
        job.etat, job.debut = "running", time.time()
        _journal.info("job %s démarre (attente %.1f s)", job.id, job.debut - job.soumis)
        try:
            executer(job, self._ressources)
        except Exception as erreur:  # le job échoue, pas le démon : ses workers doivent être rendus
            job.notes += f"[testd] erreur interne du démon : {erreur!r}\n"
            _journal.exception("job %s : erreur", job.id)
        job.etat = "cancelled" if job.annule else "done"
        self._ressources.workers.rendre(job.workers)
        with self._cond:
            self._en_cours -= 1
            self.derniere_activite = time.time()
            self._clore(job)
        _journal.info("job %s fini (%s, %.1f s, -n %s)", job.id, job.etat, job.fin - job.debut, job.n_accorde)

    def _clore(self, job: Job) -> None:
        job.fin = time.time()
        (job.dossier / "final.json").write_text(json.dumps(instantane(job, 0)), encoding="utf-8")

    def navigateur(self, job: Job) -> dict:
        """Navigateur chaud demandé par le plugin d'un test (démarré s'il ne tourne pas)."""
        ws, _, note = self._ressources.navigateurs.point_d_acces(job.python, job.env)
        job.notes += note
        return {"ws": ws}

    def instantane(self, job: Job) -> dict:
        creneaux = self._ressources.creneaux
        return instantane(job, self.position(job), self._ressources.workers.etat(),
                          creneaux.position(job.id), creneaux.etat())


def instantane(job: Job, position: int, budget: str = "", position_navigateur: int = 0,
               creneaux: str = "") -> dict:
    """Ce que voit le client : état, position (file des jobs, puis attente d'un créneau
    navigateur), avancement, et à la fin les sorties."""
    etat = {"job_id": job.id, "state": job.etat, "position": position, "total": job.total,
            "browser_position": position_navigateur, "browser_slots": creneaux,
            "notes": job.notes, "cwd": job.cwd, "cmd": job.cmd, "budget": budget,
            "workers": job.n_accorde,
            "queued_s": round((job.debut or time.time()) - job.soumis, 1),
            "elapsed_s": round(((job.fin or time.time()) - job.debut) if job.debut else 0, 1)}
    etat.update(job.avancement())
    if job.etat in ("done", "cancelled"):
        etat.update(parts=job.parties, timed_out=job.timed_out, base=job.comparaison)
    return etat
