# [desc] Issue et reponse d'une execution Rundeck rapatriee : raison d'echec (code, branches non reimportees) et `reponse.md` lue par le digest de reveil. [/desc]
"""Ce que le parent lira d'une execution distante terminee.

Mode agent : la VM ecrit `reponse.md` (le `--result-file` de l'agent bouzecode) ; elle est
rapatriee telle quelle par `recuperer`. Mode tests (ou agent sans reponse) : on compose ici
une reponse courte — code, resume JUnit, captures, fin de `sortie.log` — dans le meme dossier.
"""
from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

from .... import close_reasons
from ..refus_modele import REFUS_MODELE

LIGNES_SORTIE = 40
REPONSE_AGENT = "reponse.md"
REPONSE_COMPOSEE = "reponse_bouzecode.md"


def issue_de_l_agent(resultat: dict) -> tuple[str, str]:
    """`(issue, code)` de la fin de l'agent distant : strictement `close_reasons.issue_de_fin`
    sur la fiche de cloture du CLI rapatriee par `recuperer`. Seul FinalAnswer livre ; une
    reponse en prose, un refus, une fin forcee -> `idle_no_delivery` ; une mort en vol, ou une
    VM sans fiche (agent mort avant d'ecrire sa cloture) -> `stopped`."""
    return close_reasons.issue_de_fin(str(resultat.get("close_reason") or ""),
                                      bool(resultat.get("final_answer")))


def _raison_de_cloture(resultat: dict) -> str:
    close_reason = str(resultat.get("close_reason") or "")
    detail = str(resultat.get("close_detail") or "")[:300]
    if close_reason == REFUS_MODELE:
        return ("le modele a refuse la consigne (filtre de contenu) : reformule-la ou relance"
                + (f" — {detail}" if detail else ""))
    if not close_reason:
        return (f"l'agent distant n'a laisse aucune fiche de cloture (code {resultat.get('code')}) "
                "— sans FinalAnswer prouvee, rien n'est livre")
    return f"l'agent distant s'est arrete sans livrer ({close_reason})" + (f" — {detail}" if detail else "")


def raison_d_echec(run: dict, etat: dict, resultat: dict) -> str:
    """"" si l'execution a LIVRE ; sinon pourquoi elle a echoue, en une phrase."""
    code = resultat.get("code")
    agent_non_livre = run.get("mode") != "tests" and issue_de_l_agent(resultat)[0] != "delivered"
    if agent_non_livre and resultat.get("close_reason"):
        return _raison_de_cloture(resultat)  # avant le code : un refus sortait en 0 (257426)
    if not isinstance(code, int) or isinstance(code, bool):
        return (f"la commande n'a pas abouti sur la VM ({code}, statut Rundeck "
                f"{etat.get('statut') or resultat.get('statut')})")
    if run.get("mode") == "tests":
        return ""  # des tests rouges sont un RESULTAT a lire, pas une panne
    if code != 0:
        return f"l'agent distant s'est arrete en code {code}"
    if agent_non_livre:  # code 0 mais aucune fiche : aucune FinalAnswer prouvee
        return _raison_de_cloture(resultat)
    refusees = {slug: info for slug, info in (resultat.get("branches") or {}).items()
                if not (info or {}).get("ok")}
    if refusees:
        detail = " ; ".join(f"{slug} : {(info or {}).get('message') or (info or {}).get('code')}"
                            for slug, info in refusees.items())
        return (f"branche non reimportee ({detail}) — bundle conserve dans "
                f"{resultat.get('dossier_local')}")
    return ""


def _resume_junit(chemin: str | None) -> str:
    if not chemin or not Path(chemin).is_file():
        return "aucun rapport JUnit"
    racine = ElementTree.parse(chemin).getroot()
    suites = [racine] if racine.tag == "testsuite" else list(racine.iter("testsuite"))
    total = {cle: sum(int(s.get(cle) or 0) for s in suites)
             for cle in ("tests", "failures", "errors", "skipped")}
    return (f"{total['tests']} tests, {total['failures']} en echec, {total['errors']} en erreur, "
            f"{total['skipped']} sautes ({chemin})")


def _fin_de_sortie(dossier: Path) -> str:
    sortie = dossier / "sortie.log"
    if not sortie.is_file():
        return "(pas de sortie.log)"
    lignes = sortie.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lignes[-LIGNES_SORTIE:])


def ecrire_reponse(run: dict, resultat: dict, dossier: Path) -> Path:
    """Le chemin de la reponse que le digest lira : celle de l'agent, sinon une composee."""
    if run.get("mode") != "tests" and (dossier / REPONSE_AGENT).is_file():
        return dossier / REPONSE_AGENT
    quoi = "Tests" if run.get("mode") == "tests" else "Agent"
    lignes = [f"{quoi} sur Rundeck : code {resultat.get('code')}, statut {resultat.get('statut')}.",
              f"JUnit : {_resume_junit(resultat.get('junit'))}.",
              f"Captures : {len(resultat.get('captures') or [])} fichier(s) dans {dossier}.",
              f"Execution : {resultat.get('url') or run.get('url') or '-'}", "",
              "Fin de la sortie :", "```", _fin_de_sortie(dossier), "```"]
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / REPONSE_COMPOSEE
    chemin.write_text("\n".join(lignes), encoding="utf-8")
    return chemin
