# [desc] Run `kind="remote"` d'un ticket execute sur Rundeck : pose, vivacite lue sur le run lui-meme (jamais de process local ni d'IPC), cloture livree ou plantee. [/desc]
"""Le run d'une execution Rundeck, tel que le ticket le porte.

    {"agent_id": "rd-<run_id>", "kind": "remote", "execution_id", "url", "run_id", "mode",
     "started_at", "termine": bool, "issue": "livre" | "echec", "raison", "reponse_path",
     "branches", "code", "journal_fin", "completed", "turns"}

Aucun agent local ne le porte : sa vivacite se lit sur ses champs (`termine`, `issue`), posees
par le suivi du watchdog (`distant.suivi`), qui applique aussi la transition du ticket
(`run_ended` livré, ou `crashed`). Tous les classements de runs passent par `est_distant` avant
de chercher un process, une fiche d'agent ou un fichier IPC.
"""
from __future__ import annotations

from pathlib import Path

from .. import ticket_fsm, tickets
from ..fsm import etats

KIND = "remote"
PREFIXE_AGENT = "rd-"
#: Runs qui PRODUISENT le travail du ticket (un agent local — dont la resolution de conflit
#: `merge_fix` —, ou une execution distante).
KINDS_TRAVAIL = ("work", "merge_fix", KIND)
LIVRE, ECHEC = "livre", "echec"


def est_distant(run: dict | None) -> bool:
    return isinstance(run, dict) and str(run.get("kind") or "") == KIND


def est_travail(run: dict | None) -> bool:
    return isinstance(run, dict) and str(run.get("kind") or "") in KINDS_TRAVAIL


def actif(run: dict) -> bool:
    """L'execution Rundeck n'est pas encore terminee (ni suivie jusqu'a son issue)."""
    return not run.get("termine")


def etat(run: dict) -> str:
    """L'etat de session equivalent (`_attach_run_state`) : 'running' tant que Rundeck tourne."""
    return "running" if actif(run) else "finished"


def vivacite(run: dict) -> str:
    """'running' | 'delivered' | 'crashed', au vocabulaire de `liveness.classify_agent_run`."""
    if actif(run):
        return "running"
    return "delivered" if run.get("issue") == LIVRE else "crashed"


def agent_id_de(resultat: dict) -> str:
    """Identifiant STABLE du run : derive du run_id Rundeck (sinon de l'execution_id)."""
    return PREFIXE_AGENT + str(resultat.get("run_id") or resultat.get("execution_id") or "inconnu")


def ajouter(slug: str, ticket: dict, resultat: dict, mode: str) -> dict:
    """Pose le run remote d'un lancement accepte (`resultat` = retour `ok` du lanceur)."""
    agent_id = agent_id_de(resultat)
    tickets.add_run(slug, ticket, agent_id, KIND, "", extra={
        "execution_id": str(resultat.get("execution_id") or ""), "url": str(resultat.get("url") or ""),
        "run_id": str(resultat.get("run_id") or ""), "mode": mode, "termine": False})
    return next(r for r in ticket["runs"] if r.get("agent_id") == agent_id)


def runs_ouverts(ticket: dict) -> list[dict]:
    return [r for r in ticket.get("runs") or [] if est_distant(r) and actif(r)]


def terminer(slug: str, ticket: dict, agent_id: str, champs: dict) -> None:
    """Clot le run (`termine` + `champs`) ; une issue LIVREE est aussi un tour clos (`completed`,
    `turns` +1 via `mark_run_completed`) : c'est ce qui fait bouger la signature de reveil."""
    def _appliquer(frais: dict) -> None:
        for run in frais.get("runs") or []:
            if isinstance(run, dict) and run.get("agent_id") == agent_id:
                run.update(champs, termine=True)
    tickets._mutate(slug, ticket["id"], _appliquer)
    for run in ticket.get("runs") or []:
        if isinstance(run, dict) and run.get("agent_id") == agent_id:
            run.update(champs, termine=True)
    if champs.get("issue") == LIVRE:
        tickets.mark_run_completed(slug, ticket, agent_id)
        finir(slug, ticket, agent_id, etats.RUN_ENDED, delivered=True, code="livre_rundeck")


def finir(slug: str, ticket: dict, agent_id: str, evenement: str, **data) -> None:
    """La fin de l'exécution Rundeck devient la transition du ticket (s'il est encore en vol)."""
    frais = tickets.get_ticket(slug, ticket["id"])
    if frais is not None and frais.get("state") in (etats.RUNNING, etats.AWAITING_INPUT):
        ticket.update(ticket_fsm.appliquer(slug, ticket["id"], evenement, "rundeck",
                                           agent_id=agent_id, **data))


def etiquette(run: dict) -> str:
    """Issue lisible pour le digest du parent, PURE (lue par la signature de reveil)."""
    quoi = "tests" if run.get("mode") == "tests" else "agent"
    if run.get("issue") == LIVRE:
        code = run.get("code")
        if quoi == "tests":
            return f"EXECUTION RUNDECK TERMINEE (tests, code {code}" + (
                ") — tests VERTS" if code == 0 else ") — tests ROUGES, voir le rapport")
        return "travail LIVRE sur Rundeck (branche agent/<ticket> importee, non validee, non mergee)"
    return f"ECHEC RUNDECK ({quoi}) : {run.get('raison') or 'cause inconnue'}"


def preuves(run: dict) -> dict[str, str]:
    """Ce que le digest de reveil lit d'un run remote : la reponse rapatriee (`reponse.md`),
    la raison d'un echec et la fin du journal Rundeck. Une seule lecture de fichier."""
    chemin = Path(str(run.get("reponse_path") or ""))
    rapport = chemin.read_text(encoding="utf-8", errors="replace") if run.get("reponse_path") \
        and chemin.is_file() else ""
    return {"close_reason": str(run.get("raison") or ""), "report": rapport,
            "last_text": str(run.get("journal_fin") or "")}


def ligne_de_livraison(run: dict) -> str:
    branches, locaux = run.get("branches") or {}, run.get("worktrees_locaux") or {}
    ou = ", ".join(f"{slug} : {(info or {}).get('branche') or 'agent/<ticket>'}"
                   + (f" (worktree {locaux[slug]})" if locaux.get(slug) else "")
                   for slug, info in branches.items()) or ("aucune branche (mode tests)" if run.get("mode") == "tests" else "aucune branche importee")
    return f"    LIVRAISON RUNDECK : {ou} — execution {run.get('execution_id')} ({run.get('url') or '-'})."


def vue_passage(run: dict, lien_at: str) -> dict:
    """Le passage d'une tache execute sur Rundeck, au vocabulaire de `taches_vue.passage`."""
    etat_ui = {"running": "running", "delivered": "finished"}.get(vivacite(run), "crashed")
    vue = {"agent_id": str(run.get("agent_id") or ""), "key": "", "etat": etat_ui,
           "started_at": str(run.get("started_at") or lien_at), "vivant": actif(run),
           "activite": f"Sur Rundeck (execution {run.get('execution_id')}) : {run.get('url') or '-'}"}
    if etat_ui == "crashed":
        vue["raison_echec"] = f"Execution Rundeck en echec : {run.get('raison') or 'cause inconnue'}"
    return vue
