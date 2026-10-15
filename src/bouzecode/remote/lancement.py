"""Lancer une tache sur Rundeck rec : paquet -> file share -> job `BZ_<run_id>` -> execution.

Contrat stable : succes `{ok: True, execution_id, url, statut, run_id, fichiers_refuses}`, refus explicite
`{ok: False, code, message}`. Codes : cible_indisponible, environnement_interdit,
acces_rundeck_manquant, llm_injoignable_depuis_rundeck, jeton_llm_manquant, commande_manquante,
projet_inconnu, mode_inconnu.
"""
import json
import os
import re
import shlex
import tempfile
from pathlib import Path

import requests

from bouzecode.remote import registre
from bouzecode.remote.paquet.paquet_transfert import MODES, construire_paquet
from bouzecode.remote.transport import llm, settings
from bouzecode.remote.transport.fileshare_client import ClientFileShare, ErreurFileShare
from bouzecode.remote.transport.rundeck_client import ClientRundeck, ErreurRundeck
from bouzecode.remote.vm import job_template

# Mesure du 2026-10-05 depuis vm-host : gateway prod et preprod repondent 401 sans jeton (donc
# joignables en direct, sans proxy). Le mode agent est donc ouvert ; a repasser a False si une
# nouvelle sonde (vm/sondes/sonde_vm.py) montre le contraire.
LLM_JOIGNABLE_DEPUIS_RUNDECK = True
OPTIONS_JOB = ("RUN_ID", "INDEX_PIP", "NPM", "CONDA", "PW_VERSION")
DOSSIER_VM = Path(__file__).parent / "vm"


def refus(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message}


def resoudre_depots(slugs: list[str], ticket: dict, execution: dict) -> tuple[dict[str, Path], dict | None]:
    """Chemin de chaque projet : execution['chemins'], puis ticket['worktrees'], puis le registre web_v2."""
    chemins = dict(ticket.get("worktrees") or {}, **(execution.get("chemins") or {}))
    manquants = [slug for slug in slugs if slug not in chemins]
    if manquants:
        from bouzecode.web_v2.services.work.projects import list_projects
        chemins.update({p["slug"]: p["path"] for p in list_projects() if p["slug"] in manquants})
    inconnus = [slug for slug in slugs if slug not in chemins or not (Path(chemins[slug]) / ".git").exists()]
    if inconnus:
        return {}, refus("projet_inconnu", f"projets sans depot git local : {inconnus}")
    return {slug: Path(chemins[slug]) for slug in slugs}, None


def consigne_du_ticket(ticket: dict) -> str:
    return ticket.get("prompt") or ticket.get("intent") or ticket.get("title") or ""


def projets_demandes(ticket: dict, execution: dict) -> list[str]:
    """`execution['projets']` (le 1er = depot principal), sinon le projet du ticket (`ticket['slug']`)."""
    projets = [str(p) for p in execution.get("projets") or [] if str(p).strip()]
    return projets or ([str(ticket["slug"])] if ticket.get("slug") else [])


def commande_agent(projet_principal: str, modele: str = "") -> str:
    """Agent bouzecode headless sur la VM, depuis le bundle du depot bouzecode, consigne lue dans le paquet.
    `-m` explicite : la VM n'a pas le config.json du poste, elle doit lancer le MEME modele."""
    option_modele = f"-m {shlex.quote(modele)} " if modele else ""
    return ('"$BZ_UV" run --project "$BZ_TRAVAIL/bouzecode" bouzecode -p --accept-all ' + option_modele +
            f'--cwd "$BZ_TRAVAIL/{projet_principal}" --result-file "$BZ_RESULTAT/reponse.md" '
            '"$(cat "$BZ_PAQUET/consigne.txt")"')


def _options_execution(run_id: str, version_playwright: str) -> dict:
    hote = os.environ.get(settings.VARIABLE_HOTE_ARTIFACTORY, "")
    return {"RUN_ID": run_id, "INDEX_PIP": settings.index_pip_artifactory(),
            "NPM": f"https://{hote}/artifactory/api/npm/npm-public",
            "CONDA": f"https://{hote}/artifactory/api/conda/conda-forge", "PW_VERSION": version_playwright}


def _fichiers_vm() -> dict[str, str]:
    sources = [DOSSIER_VM / "vm_runner.py", DOSSIER_VM / "depots_vm.py", DOSSIER_VM / "environnement_vm.py",
               DOSSIER_VM / "navigateur" / "installer_navigateur.py",
               DOSSIER_VM / "navigateur" / "deballage.py"]
    return {source.name: source.read_text(encoding="utf-8") for source in sources}


def soumettre_job(reglages, run_id: str, distant: str, mode: str, execution: dict,
                  secrets: dict[str, str]) -> tuple[str, dict]:
    """`secrets` : {nom d'option Rundeck: valeur}, poses en options `secure`, jamais dans le YAML."""
    """Importe le job `BZ_<run_id>` et le lance ; si le lancement echoue, le job cree est supprime."""
    vm_distant = f"{settings.VM_MONTAGE_SHARE}/{distant}"
    arguments = f"{vm_distant}/paquet {settings.VM_RACINE_TRAVAIL}/{run_id} {vm_distant}/resultat"
    rundeck = ClientRundeck(reglages)
    job_id = rundeck.importer_job(job_template.yaml_job(
        run_id, _fichiers_vm(), "vm_runner.py", list(OPTIONS_JOB), f"bouzecode distant ({mode})",
        arguments=arguments, options_secretes=tuple(secrets), delai_max=f"{int(execution.get('delai_s', 3600)) + 900}s"))
    options = _options_execution(run_id, execution.get("version_playwright", ""))
    options.update(secrets)
    try:
        return job_id, rundeck.lancer_job(job_id, options)
    except Exception:
        rundeck.supprimer_job(job_id)
        raise


def deposer_et_lancer(ticket: dict, mode: str, commande: str, depots: dict[str, Path], execution: dict) -> dict:
    reglages = settings.charger_reglages(execution.get("environnement", settings.ENVIRONNEMENT_AUTORISE))
    run_id = settings.nouvel_identifiant_execution("bz" + str(ticket.get("id", "x"))[:8].replace("-", ""))
    identifiants_git = settings.identifiants_gitlab()
    distant = f"{settings.FILESHARE_RACINE}/{run_id}"
    share = ClientFileShare(reglages)
    with tempfile.TemporaryDirectory(prefix="bz_paquet_") as dossier_temporaire:
        dossier = Path(dossier_temporaire)
        manifeste = construire_paquet(run_id, mode, commande, depots, execution.get("fichiers_non_suivis") or {},
                                      dossier, delai_s=int(execution.get("delai_s", 3600)),
                                      navigateur=bool(execution.get("navigateur")),
                                      outils=set(execution.get("projets_outils") or ()),
                                      branche_travail=branche_agent(ticket), via_remote=bool(identifiants_git))
        consigne = consigne_du_ticket(ticket)
        if consigne:
            (dossier / "consigne.txt").write_text(consigne, encoding="utf-8")
        for fichier in sorted(dossier.iterdir()):
            share.deposer(f"{distant}/paquet/{fichier.name}", fichier.read_bytes())
    try:
        variables_llm = llm.variables_pour(execution["modele_llm"])[0] if execution.get("modele_llm") else {}
        secrets = {llm.PREFIXE_OPTION + nom: valeur for nom, valeur in variables_llm.items()}
        if any(p.get("source") == "remote" for p in manifeste["projets"]):
            secrets.update(identifiants_git)
        job_id, lancement = soumettre_job(reglages, run_id, distant, mode, execution, secrets)
    except Exception:
        share.supprimer_arborescence(distant)  # pas de paquet orphelin sur le share si le job n'est pas lance
        raise
    fiche = {"run_id": run_id, "job_id": job_id, "mode": mode, "ticket_id": ticket.get("id"), "share": distant,
             "depots": {slug: str(chemin) for slug, chemin in depots.items()}, "url": lancement["url"],
             "projets": [{k: p.get(k) for k in ("slug", "sha", "branche", "branche_travail", "fichiers_refuses",
                                                "source", "octets_bundle", "outil")}
                         for p in manifeste["projets"]]}
    registre.enregistrer(lancement["execution_id"], fiche)
    return {"ok": True, "execution_id": lancement["execution_id"], "url": lancement["url"], "statut": "running",
            "run_id": run_id, "fichiers_refuses": {p["slug"]: p["fichiers_refuses"] for p in manifeste["projets"]},
            "transfert": {p["slug"]: {k: p.get(k) for k in ("source", "octets_bundle", "raison", "commits_a_envoyer")}
                          for p in manifeste["projets"]}}


def branche_agent(ticket: dict) -> str:
    """`agent/<ticket>` assaini comme `worktrees.provision` : la meme branche que le chemin local."""
    return "agent/" + re.sub(r"[^A-Za-z0-9_-]", "-", str(ticket.get("id") or "x"))


def lancer_sur_rundeck(ticket: dict, execution: dict) -> dict:
    if execution.get("cible") != "rundeck":
        return refus("cible_indisponible", f"cible {execution.get('cible')!r} non servie ici (attendu 'rundeck')")
    if execution.get("environnement", settings.ENVIRONNEMENT_AUTORISE) != settings.ENVIRONNEMENT_AUTORISE:
        return refus("environnement_interdit", "seul l'environnement Rundeck 'rec' est autorise")
    if settings.secrets_manquants():
        return refus("acces_rundeck_manquant", f"variables absentes : {settings.secrets_manquants()}")
    mode = execution.get("mode", "agent")
    if mode not in MODES:
        return refus("mode_inconnu", f"mode {mode!r}, attendu un de {MODES}")
    slugs = projets_demandes(ticket, execution)
    if not slugs:
        return refus("projet_inconnu", "aucun projet a transmettre")
    # Agent bouzecode par defaut (pas de commande fournie) : seul cas ou le jeton LLM part sur la VM.
    agent_bouzecode = mode == "agent" and not execution.get("commande")
    if agent_bouzecode:
        if not LLM_JOIGNABLE_DEPUIS_RUNDECK:
            return refus("llm_injoignable_depuis_rundeck", "le gateway LLM n'est pas joignable depuis la VM")
        modele = str(execution.get("modele") or llm.modele_par_defaut())
        manquants = llm.variables_pour(modele)[1]
        if manquants:
            return refus("jeton_llm_manquant", f"modele {modele} : variables absentes {manquants}")
        outils = [] if "bouzecode" in slugs else ["bouzecode"]  # l'outil, pas un livrable : rien a rapatrier
        slugs += outils
        execution = dict(execution, modele_llm=modele, projets_outils=outils,
                         chemins={"bouzecode": str(Path(__file__).resolve().parents[3]), **(execution.get("chemins") or {})})
    commande = (commande_agent(slugs[0], execution["modele_llm"]) if agent_bouzecode
                else str(execution.get("commande") or ""))
    if not commande:
        return refus("commande_manquante", "le mode tests exige une commande")
    depots, refus_depots = resoudre_depots(slugs, ticket, execution)
    if refus_depots:
        return refus_depots
    try:
        return deposer_et_lancer(ticket, mode, commande, depots, execution)
    except (ErreurRundeck, ErreurFileShare, requests.RequestException) as erreur:
        return refus("acces_rundeck_manquant", f"{type(erreur).__name__}: {str(erreur)[:300]}")
