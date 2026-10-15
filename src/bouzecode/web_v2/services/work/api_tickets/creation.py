# [desc] Créer un ticket (POST /api/projects/{slug}/tickets) : validation stricte, Idempotency-Key, garde de fratrie, collision d'isolation en 409 (jamais de bascule), lancement ASYNCHRONE par défaut. [/desc]
"""Le chemin unique de création d'un ticket (spec §5.1, §5.6) : l'UI, le Bureau, l'outil `Agent`
d'un manager et le Bureau y passent tous.

Ordre : projet → Idempotency-Key → validation, `execution` comprise (rien n'est créé avant ;
`cible=rundeck` part au lanceur distant, cf. `execution.py`) → garde d'environnement
(si lancement) → collision `shared` (409 `collision_isolation`, le serveur ne bascule JAMAIS en
worktree d'office) → doublon de fratrie (409 `doublon`) → création, puis `provisioning` et
lancement en fond (ou synchrone si `defer: false`)."""
from __future__ import annotations

import copy
import threading

from bouzecode.web_v2.services.horodatage import maintenant_iso

from ... import scope_guard
from .. import dispatch, projects, repos, tickets
from ..isolation import SHARED, agents_sharing_cwd
from . import execution as execution_du_lancement
from . import garde, validation
from .refus import Refus


def projet(slug: str) -> dict:
    trouve = projects.find(slug)
    if trouve is None:
        raise Refus("projet_inconnu", f"projet inconnu : {slug}", 404, slug=slug)
    return trouve


def _deja_cree(cle: str, slug: str) -> dict | None:
    if not cle:
        return None
    with tickets._connect() as conn:
        ligne = conn.execute("SELECT ticket_id FROM idempotence WHERE cle=? AND slug=?",
                             (cle, slug)).fetchone()
    return tickets.get_ticket(slug, ligne[0]) if ligne else None


def _retenir(cle: str, slug: str, ticket_id: str) -> None:
    if cle:
        with tickets._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO idempotence(cle, slug, ticket_id, at) "
                         "VALUES(?,?,?,?)", (cle, slug, ticket_id,
                                             maintenant_iso()))


def _collision(project: dict, mode: str, exclus: tuple = (), profil: str = "") -> None:
    """409 `collision_isolation` si le nouvel agent PEUT ÉCRIRE et qu'un autre agent écrivain
    travaille déjà dans le dépôt principal (`exclus` : les agents du ticket relancé lui-même).
    Un agent en lecture seule (profil sans outil d'écriture) n'écrase personne."""
    from types import SimpleNamespace

    from ..isolation import agent_can_write
    if mode != SHARED or not agent_can_write(SimpleNamespace(profile=profil)):
        return
    occupants = [a for a in agents_sharing_cwd(project["path"]) if a not in exclus]
    if occupants:
        raise Refus("collision_isolation", f"{len(occupants)} agent(s) écrivent déjà dans le "
                    "dépôt principal : choisis `worktree` (le serveur ne bascule jamais "
                    "d'office)", 409, agents=sorted(occupants), isolation=mode)


def _champs(payload: dict, parent: tuple[str, str], mode: str, profil: str, modele: str,
            branches: tuple[str, str], managed: bool) -> dict:
    agent_parent, ticket_parent = parent
    champs = {"parent": agent_parent or "", "isolation": mode, "profile": profil,
              "model": modele, "typology": str(payload.get("typology") or profil or "default"),
              "use_readme": bool(payload.get("use_readme")), "micro_id": payload.get("micro_id")
              or None, "parent_ticket_id": ticket_parent or None,
              "resume_branch": branches[0] or None, "work_branch": branches[1] or None,
              "ephemeral": True if payload.get("ephemeral") else None}
    if agent_parent and not managed:
        champs[dispatch.NON_MANAGE] = True
    lancement = {cle: valeur.strip() if isinstance(valeur, str) else valeur
                 for cle, valeur in (("tour", payload.get("parent_turn")),
                                     ("nom", payload.get("name")),
                                     ("doublon_assume", payload.get("doublon_assume")))
                 if valeur and str(valeur).strip()}
    if lancement:
        champs["lancement"] = lancement
    return champs


def _lancer(slug: str, project: dict, ticket: dict, profil: str, modele: str, mode: str,
            branches: tuple[str, str], defer: bool):
    from .. import fleet
    tickets.set_launching(slug, ticket)  # → provisioning, sous verrou
    #  Un lancement AJOUTE un process au parc : moment causal pour reborner le pool chaud (en
    #  fond : ce ménage relit tout le parc et n'apporte rien à la réponse).
    threading.Thread(target=fleet.sweep_warm_pool, daemon=True, name="sweep-warm-pool").start()
    args = (project["path"], profil, modele, mode, ticket.get("parent") or "", *branches)
    if defer:
        threading.Thread(target=dispatch._launch_bg, args=(slug, copy.deepcopy(ticket), *args),
                         daemon=True, name=f"lancement-{ticket['id']}").start()
        return None
    try:
        return dispatch._launch(slug, ticket, *args)
    except Exception as exc:  # le ticket ne reste pas en préparation : l'échec est GRAVÉ
        dispatch.record_launch_failure(slug, ticket, str(exc))
        raise


def creer(slug: str, payload: dict, idempotency_key: str = "") -> dict:
    """Crée (et lance, sauf `launch: false`) ; rend la réponse 201. Lève `Refus`."""
    project = projet(slug)
    rejoue = _deja_cree(idempotency_key, slug)
    if rejoue is not None:
        return reponse(slug, project, rejoue, rejoue=True)
    titre, prompt = validation.titre_et_prompt(payload)
    parent = validation.parent(payload)
    managed = bool(parent[0]) and payload.get("managed", True) is not False
    depot_git = bool(repos.repo_root(project["path"]))
    mode = validation.isolation(payload.get("isolation"), managed, depot_git)
    branches = validation.branches(project, mode, payload)
    profil = validation.profil(payload.get("profile") or "", project["path"]) or \
        dispatch.resolve_profile(str(payload.get("typology") or ""), project["path"], managed)
    modele = validation.modele(payload.get("model") or "")
    lancer = payload.get("launch", True) is not False
    execution = execution_du_lancement.valider(payload, slug)
    prompt = execution_du_lancement.prompt_avec_section(prompt, execution)
    if execution and execution["cible"] == "rundeck":
        if not lancer:
            raise Refus("options_distantes", "cible=rundeck lance aussitôt : `launch: false` "
                        "n'a pas de sens", 400)
        distant = execution_du_lancement.lancer_sur_rundeck(slug, titre, prompt, execution,
                                                            parent[0])
        corps = reponse(slug, project, distant["ticket"])
        corps["distant"] = distant["distant"]
        return corps
    if lancer:
        garde.exiger()
        _collision(project, mode, profil=profil)
    with scope_guard.verrou_de_fratrie(parent[0]):
        motif = scope_guard.refus_de_doublon(prompt, parent[0], payload.get("doublon_assume") or "")
        if motif:
            raise Refus("doublon", motif, 409)
        ticket = tickets.create_ticket(slug, titre, prompt)
        tickets.poser(slug, ticket, **_champs(payload, parent, mode, profil, modele, branches,
                                              managed), execution=execution)
        _retenir(idempotency_key, slug, ticket["id"])
        agent = _lancer(slug, project, ticket, profil, modele, mode, branches,
                        payload.get("defer", True) is not False) if lancer else None
    avertissements = scope_guard.review_dispatch(slug, ticket["id"], prompt, ticket.get(
        "typology") or "", parent[0]) if lancer else []
    return reponse(slug, project, tickets.get_ticket(slug, ticket["id"]) or ticket, agent=agent,
                   avertissements=avertissements)


def reponse(slug: str, project: dict, ticket: dict, agent=None, avertissements=(),
            rejoue: bool = False) -> dict:
    """Le corps 201 : le ticket (à plat, compatible avec l'ancienne forme) ET sous `ticket`,
    plus ce qu'un client ouvre aussitôt (`launch_key`, `key` si l'agent est déjà né)."""
    from ..etat_ticket import vue
    corps = {**ticket, **vue(ticket), "ticket": {**ticket, **vue(ticket)},
             "ticket_id": ticket["id"], "project_slug": slug, "project_name": project["name"],
             "launch_key": f"launching/{ticket['id']}", "isolation": ticket.get("isolation", ""),
             #  L'isolation demandée est respectée ou refusée : plus rien à expliquer (C8).
             "isolation_message": "",
             "scope_warnings": list(avertissements)}
    if agent is not None:
        corps["key"] = f"agent/{agent.agent_id}"
    if rejoue:
        corps["rejoue"] = True
    return corps
