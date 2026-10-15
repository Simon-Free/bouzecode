# [desc] testd : les deux sous-runs d'un job — hors navigateur (workers pris au budget de la machine) et navigateur (contextes réservés, navigateur chaud, une reprise s'il meurt) [/desc]
from __future__ import annotations

from ..budget.durations import workers_voulus
from ..budget.workers import MAX_PAR_JOB, xdist_vole
from .split import avec_workers, env_sous_run, workers_demandes


def _plafond(job) -> int:
    """`-n` demandé par l'appelant (0 = parallel='off'), jamais plus de 4."""
    return min(MAX_PAR_JOB, workers_demandes(job.cmd))


def partie_hors_navigateur(job, nodeids, durees: dict, ressources, marqueurs: str,
                           label: str, garder: str, lancer, dossier_evenements, ws: str = "") -> dict:
    """`nodeids` None = collecte impossible : on garde le `-n` demandé, borné par le budget ;
    `ws` : navigateur chaud offert aux tests navigateur qui s'y trouveraient."""
    voulu = _plafond(job) if nodeids is None else workers_voulus(nodeids, durees, _plafond(job))
    supplement = ressources.workers.prendre_jusqu_a(voulu - 1) if voulu > 1 else 0
    job.workers += supplement
    job.n_accorde = 1 + supplement if voulu > 1 else 0
    if job.n_accorde < voulu:
        job.notes += f"[testd] -n {job.n_accorde} au lieu de {voulu} ({ressources.workers.etat()}).\n"
    commande = avec_workers(job.cmd, job.n_accorde, xdist_vole(job.python, job.env))
    env = env_sous_run(job.env, dossier_evenements(job, f"ev-{label}"), garder, marqueurs)
    if ws:
        env["BZ_PW_WS"] = ws
        env["BZ_PW_NOTES"] = str(job.dossier / "pw_notes.txt")
    return lancer(job, label, commande, env)


def partie_navigateur(job, nodeids, durees: dict, ressources, marqueurs: str,
                      lancer, dossier_evenements, label: str = "browser") -> dict | str:
    """Un créneau navigateur de la machine (`budget.creneaux`), puis des contextes pris à la
    réserve (1 par worker), branché sur le navigateur chaud ; si celui-ci meurt pendant le
    sous-run, il est relancé et le sous-run rejoué une fois.
    `label` "all" : job sans collecte (cf. budget.classes), rien n'est désélectionné."""
    if not ressources.creneaux.prendre(job.id, job.doit_s_arreter):
        return "[testd] tests navigateur non lancés (job arrêté pendant l'attente d'un créneau navigateur).\n"
    try:
        return _avec_contextes(job, nodeids, durees, ressources, marqueurs, lancer,
                               dossier_evenements, label)
    finally:
        ressources.creneaux.rendre(job.id)


def _avec_contextes(job, nodeids, durees: dict, ressources, marqueurs: str, lancer,
                    dossier_evenements, label: str) -> dict | str:
    garder = "browser" if label == "browser" else ""
    contextes_max = min(_plafond(job) or 1, ressources.contextes.total)
    workers = workers_voulus(nodeids, durees, contextes_max, navigateur=True)
    contextes = max(1, workers)
    if not ressources.contextes.prendre(contextes, job.doit_s_arreter):
        return "[testd] tests navigateur non lancés (job arrêté pendant l'attente des contextes).\n"
    try:
        for tentative in (1, 2):
            ws, serveur, note = ressources.navigateurs.point_d_acces(job.python, job.env)
            job.notes += note
            env = env_sous_run(job.env, dossier_evenements(job, f"ev-{label}-{tentative}"),
                               garder, marqueurs)
            if ws:
                env["BZ_PW_WS"] = ws
                env["BZ_PW_NOTES"] = str(job.dossier / "pw_notes.txt")
            commande = avec_workers(job.cmd, workers, xdist_vole(job.python, job.env))
            partie = lancer(job, label, commande, env, navigateur=True)
            if tentative == 2 or serveur is None or serveur.poll() is None or job.doit_s_arreter():
                return partie
            job.dossiers_evenements.pop()  # la tentative perdue ne compte pas
            job.notes += "[testd] le navigateur chaud est mort pendant les tests navigateur : rejoués une fois.\n"
    finally:
        ressources.contextes.rendre(contextes)
