# [desc] testd : un job = la commande pytest de RunPythonTest ; exécution en sous-runs (hors navigateur tout de suite, navigateur via la réserve et le navigateur chaud) [/desc]
"""Déroulé d'un job : serveur applicatif chaud (si `tests.yaml` en décrit un), collecte pour
séparer les tests navigateur, puis deux sous-runs en parallèle — hors navigateur aussitôt,
navigateur une fois ses contextes obtenus, branché sur le navigateur chaud (`BZ_PW_WS`). Si le
navigateur chaud meurt pendant le sous-run navigateur, il est relancé et ce sous-run rejoué une
fois.

Un job dont toutes les cibles sont des fichiers déjà classés saute la collecte (cf.
`budget.classes`). Si RunPythonTest le demande (`base`), les échecs sont rejoués sur la base
DANS le créneau du job, avec ses workers déjà pris : pas de second job, donc pas d'attente de la
file par un job qui l'occupe."""
from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..budget.classes import memoriser, plan_sans_collecte
from ..budget.durations import charger, fichier_durees, fusionner
from ..budget.recentes import ajouter, medianes
from ..common import sans_fenetre, tuer_arbre
from ..garde.bloque import GardeTest, faulthandler_borne
from ..garde.limites import Limites, limites_de
from ..garde.signaux import section_lents, section_relances, seuil_lent
from .parties import partie_hors_navigateur, partie_navigateur
from .split import collecter, durees_mesurees, lire_evenements


#  Événements et classes (`_bz_testd_plugin`), relances coupées (`_bz_sans_relance`), actions
#  Playwright à 5 s (`_bz_pw_delai`).
PLUGINS_DU_SOUS_RUN = ["-p", "_bz_testd_plugin", "-p", "_bz_sans_relance", "-p", "_bz_pw_delai"]


@dataclass
class Job:
    cmd: list[str]
    env: dict
    cwd: str
    timeout: int
    python: str
    dossier: Path
    id: str
    etat: str = "queued"           # queued | running | done | cancelled
    soumis: float = field(default_factory=time.time)
    debut: float = 0.0
    fin: float = 0.0
    total: int | None = None
    notes: str = ""
    parties: list = field(default_factory=list)     # [{label, output, returncode}]
    dossiers_evenements: list = field(default_factory=list)
    procs: list = field(default_factory=list)
    timed_out: bool = False
    annule: bool = False
    workers: int = 0                # pris au budget de la machine (1 dès l'admission)
    n_accorde: int | None = None    # `-n` accordé au sous-run hors navigateur
    cibles: list = field(default_factory=list)      # `targets` de RunPythonTest
    base: dict | None = None        # {"communs": [...]} : comparer les échecs à la base
    a_nettoyer: list = field(default_factory=list)  # dossiers temporaires confiés au démon
    comparaison: str = ""
    limites: Limites = field(default_factory=Limites)  # délai par test (cf. garde.limites)

    def avancement(self) -> dict:
        return lire_evenements(list(self.dossiers_evenements))

    def doit_s_arreter(self) -> bool:
        return self.annule or self.timed_out or bool(self.debut and time.time() > self.debut + self.timeout)


def _sous_run(job: Job, label: str, cmd: list[str], env: dict, navigateur: bool = False) -> dict:
    """Lance un sous-run (sortie dans un fichier, jamais un tube) et l'attend ; un test bloqué
    au-delà de sa limite le fait tuer (cf. garde.bloque, garde.limites)."""
    sortie = job.dossier / f"{label}.txt"
    commande = faulthandler_borne(cmd, job.limites.vidage(navigateur)) + PLUGINS_DU_SOUS_RUN
    with open(sortie, "w", encoding="utf-8") as journal:
        proc = subprocess.Popen(commande, cwd=job.cwd, env=env,
                                stdout=journal, stderr=subprocess.STDOUT, **sans_fenetre(groupe=True))
    job.procs.append(proc)
    garde = GardeTest(job.limites, navigateur, job.cwd, Path(env["BZ_TESTD_EVENTS"]), sortie)
    while proc.poll() is None:
        bloque = garde.bloque()
        if bloque:
            job.notes += bloque
            tuer_arbre(proc.pid)
            proc.wait()
            break
        if job.doit_s_arreter():
            job.timed_out = job.timed_out or not job.annule
            tuer_arbre(proc.pid)
            proc.wait()
            break
        time.sleep(0.2)
    job.procs.remove(proc)
    return {"label": label, "output": str(sortie), "returncode": proc.returncode}


def _dossier_evenements(job: Job, nom: str) -> Path:
    dossier = job.dossier / nom
    dossier.mkdir(parents=True, exist_ok=True)
    job.dossiers_evenements.append(dossier)
    return dossier


def _filtree(job: Job) -> bool:
    """Collecte filtrée (`-k`, `-m`, ids) : un test navigateur a pu être écarté."""
    selection = Path(job.env.get("BZ_SELECTION") or job.dossier / "absent")
    filtres = json.loads(selection.read_text(encoding="utf-8")).get("fichiers_filtres")         if selection.is_file() else []
    #  Les options de pytest seulement : `python -m pytest` porte aussi un `-m`.
    options = job.cmd[job.cmd.index("pytest") + 1:] if "pytest" in job.cmd else job.cmd
    return any(a in ("-k", "-m") for a in options) or any("::" in c for c in job.cibles) or bool(filtres)


def _sous_runs(job: Job, ressources, durees: dict, marqueurs: str, historique: Path) -> None:
    plan = plan_sans_collecte(historique, job.cwd, job.cibles, durees)
    if plan is not None:
        job.notes += "[testd] collecte sautée : fichiers déjà classés (cf. durées).\n"
        job.total = len(plan["nodeids"]) or None
        partie = (partie_navigateur(job, plan["nodeids"], durees, ressources, marqueurs, _sous_run,
                                    _dossier_evenements, label="all") if plan["browser"] else
                  partie_hors_navigateur(job, plan["nodeids"], durees, ressources, marqueurs, "all",
                                         "", _sous_run, _dossier_evenements,
                                         ressources.navigateurs.deja_chaud(job.python, job.env)))
        resultats = {"autres": partie}
    else:
        groupes, note = collecter(job.cmd, job.env, job.cwd, job.dossier, marqueurs, job.doit_s_arreter)
        job.notes += note
        if groupes:
            memoriser(historique, job.cwd, groupes, _filtree(job))
        resultats = _separes(job, groupes, durees, ressources, marqueurs)
    for cle in ("autres", "navigateur"):
        if isinstance(resultats.get(cle), str):
            job.notes += resultats.pop(cle)
    job.parties = [resultats[c] for c in ("autres", "navigateur") if c in resultats]


def _separes(job: Job, groupes, durees: dict, ressources, marqueurs: str) -> dict:
    navigateur = groupes["browser"] if groupes else []
    autres = groupes["other"] if groupes else None
    job.total = len(navigateur) + len(autres) if groupes else None
    resultats: dict = {}
    fil = None
    if autres is None or autres:  # un groupe vide ne lance aucun sous-run
        label, garder = ("other", "other") if navigateur else ("all", "")
        #  Un test navigateur peut s'y trouver (collecte impossible, ou lanceur que le plugin ne
        #  reconnaît pas) : le navigateur chaud déjà lancé lui reste offert (plugin
        #  `_bz_pw_patch`), aucun n'est démarré pour lui.
        ws = ressources.navigateurs.deja_chaud(job.python, job.env)
        fil = threading.Thread(target=lambda: resultats.update(autres=partie_hors_navigateur(
            job, autres, durees, ressources, marqueurs, label, garder, _sous_run, _dossier_evenements,
            ws)))
        fil.start()
    if navigateur:
        resultats["navigateur"] = partie_navigateur(job, navigateur, durees, ressources, marqueurs,
                                                    _sous_run, _dossier_evenements)
    if fil:
        fil.join()
    return resultats


def _si_aucun_test(job: Job) -> str:
    """Rien n'a tourné : le verdict de pytest et ce qui a tout désélectionné (cf. pytest_zero).
    La sortie du run passe en dernier (son verdict), la collecte d'abord (son « N deselected »,
    que xdist ne répète pas, et ses `ERROR: file or directory not found`)."""
    from ...tools.ops.pytest_zero import aucun_test_lance, explication
    if job.doit_s_arreter() or job.avancement()["done"]:
        return ""
    journal, collecte = job.dossier / "collecte.log", job.dossier / "collecte.json"
    textes = [Path(p).read_text(encoding="utf-8", errors="replace")
              for p in [journal, *(p["output"] for p in job.parties)] if Path(p).exists()]
    if not textes or not aucun_test_lance(textes[-1]):
        return ""
    ecartes = (json.loads(collecte.read_text(encoding="utf-8")).get("deselected")
               if collecte.exists() else None)
    return explication(job.cmd, Path(job.cwd), job.env, "\n".join(textes), ecartes)


def _comparer_a_la_base(job: Job) -> None:
    """Échecs (et erreurs) de tous les sous-runs, rejoués sur la base avec le `-n` déjà accordé."""
    from ...tools.ops.baseline import comparer_avec_la_base
    from ...tools.ops.selection_plugin import lire_issues
    issues: dict = {}
    for dossier in job.dossiers_evenements:
        issues.update(lire_issues(Path(dossier) / "issues.json"))
    echecs = sorted(i for i, issue in issues.items() if issue in ("failed", "error"))
    xdist = ["-n", str(job.n_accorde)] if (job.n_accorde or 0) > 1 else []
    job.comparaison = comparer_avec_la_base(Path(job.cwd), echecs, job.python, job.env,
                                            [*xdist, *job.base["communs"]], job.timeout)


def _signaux(job: Job, config: dict) -> str:
    """Tests lents et relances neutralisées (cf. garde.signaux) : dits, jamais tués."""
    dossiers = list(job.dossiers_evenements)
    return (section_lents(dossiers, seuil_lent(config),
                          lambda nodeid: job.limites.liste_lent(nodeid, job.cwd))
            + section_relances(dossiers, [Path(p["output"]) for p in job.parties]))


def executer(job: Job, ressources) -> None:
    """Exécute le job jusqu'au bout ; remplit `parties`, `notes`. Les durées mesurées enrichissent
    l'historique du dépôt, qui ordonne et dimensionne les runs suivants."""
    from ...tools.ops.selection_plugin import nettoyer
    from ..warm.app_servers import config_tests
    from ..warm.demande import apprendre, env_navigateur
    config = config_tests(job.cwd)
    marqueurs = ",".join(["browser", "e2e", str((config.get("browser") or {}).get("marker") or "")]).strip(",")
    env_app, note = ressources.applis.prendre(config, job.python, job.env)
    job.notes += note
    historique = fichier_durees(job.cwd)
    durees = charger(historique)
    job.limites = limites_de(config, {**durees, **medianes(historique)})
    instantane = job.dossier / "durees.json"  # figé : tous les workers xdist trient pareil
    instantane.write_text(json.dumps(durees), encoding="utf-8")
    job.env = {**job.env, **env_app, **env_navigateur(job, ressources),
               "BZ_TESTD_DURATIONS": str(instantane)}
    try:
        _sous_runs(job, ressources, durees, marqueurs, historique)
        job.notes += _si_aucun_test(job)
        if job.base is not None and not job.doit_s_arreter():
            _comparer_a_la_base(job)
    finally:
        job.notes += _signaux(job, config)
        mesurees = durees_mesurees(job.dossiers_evenements)
        fusionner(historique, mesurees)
        ajouter(historique, mesurees)
        apprendre(job, historique)
        ressources.applis.rendre(config)
        for dossier in job.a_nettoyer:
            nettoyer(dossier)
        notes_pw = job.dossier / "pw_notes.txt"
        if notes_pw.exists():
            job.notes += "".join(sorted(set(notes_pw.read_text(encoding="utf-8").splitlines(True))))
