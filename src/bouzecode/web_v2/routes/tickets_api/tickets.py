# [desc] Ressource ticket (spec §6.2) : liste PURE filtrée/paginée, création 201 (validation stricte, Idempotency-Key), fiche (ticket + runs + delivery + integration), PATCH en `created`, journal (GET/POST events), runs. [/desc]
from __future__ import annotations

from flask import Blueprint, request

from ...schema import corps_attendu
from ...services.work import ticket_fsm, tickets
from ...services.work.api_tickets import creation, lectures, validation
from ...services.work.api_tickets.refus import Refus
from ...services.work.etat_ticket import vue
from ...services.work.fsm import etats, journal
from ._commun import corps, json, ticket_ou_refus

tickets_v3_bp = Blueprint("tickets_v3_api", __name__)


@tickets_v3_bp.get("/api/projects/<slug>/tickets")
def api_tickets_lister(slug: str):
    """?state=a,b&archived=0|1|all&parent=&limit=&cursor= → {tickets:[résumé : id, title, state,
    state_reason, version, status, status_ui, libelle_statut, created_at, typology, isolation,
    parent, runs légers, delivery?], next_cursor, total}. LECTURE PURE du store (ni git, ni
    session). `include_archived=1` = `archived=all` ; `full=1` : les tickets entiers. 400
    `etat_inconnu`, 404 `projet_inconnu`."""
    creation.projet(slug)
    archived = request.args.get("archived") or ("all" if request.args.get(
        "include_archived") == "1" else "0")
    return json(lectures.lister(slug, request.args.get("state") or "", archived,
                                request.args.get("parent") or "", request.args.get("limit"),
                                request.args.get("cursor"), request.args.get("full") == "1"))


@tickets_v3_bp.post("/api/projects/<slug>/tickets")
@corps_attendu(title="texte ≤ 200 car., requis", prompt="texte ≤ 200 000 car., requis",
               isolation="shared|worktree|worktree_venv (requise pour un agent parent)",
               profile="nom d'un profil du catalogue", model="nom d'un modèle (GET /api/models)",
               typology="typologie",
               parent="{agent_id, ticket_id} de l'agent qui crée le ticket",
               work_branch="branche existante et libre",
               resume_branch="branche de départ du worktree", micro_id="tâche du Bureau liée",
               ephemeral="booléen (worktree jetable)",
               doublon_assume="raison d'un périmètre en doublon assumé",
               launch="booléen, défaut true", defer="booléen, défaut true (lancement en fond)",
               execution="{cible: local|rundeck, projets, fichiers_non_suivis, mode, commande, "
                         "navigateur} (docs/specs/assistant_execution.md)")
def api_tickets_creer(slug: str):
    """crée (et lance, sauf `launch: false`) un ticket → 201 {ticket, ticket_id,
    project_slug, project_name, launch_key, isolation, key? (si defer:false), scope_warnings, +
    le ticket à plat}. En-tête `Idempotency-Key` : rejouer la clé rend le même ticket (`rejoue:
    true`). Lancement ASYNCHRONE (`provisioning`). Isolation OBLIGATOIRE pour un agent parent
    (400 `isolation_requise`), défaut `worktree` pour l'humain (`shared` hors dépôt git). 400
    `champ_requis`, `titre_trop_long`, `prompt_trop_long`, `isolation_inconnue`,
    `isolation_impossible`, `isolation_incompatible`, `profil_inconnu`, `modele_inconnu`,
    `branche_introuvable`,
    404 `projet_inconnu`, 409 `collision_isolation` (jamais de bascule d'office) / `doublon`,
    503 `env_indisponible`. `execution.cible = rundeck` : aucun agent local, le ticket part sur
    Rundeck (réponse + `distant` {ok, execution_id, url, run_id, fichiers_refuses}) ; 400
    `cible_inconnue`, `depot_inconnu`, `fichiers_invalides`, `options_distantes`,
    `commande_manquante`, 501 `cible_indisponible`, 502 `lancement_impossible`."""
    resultat = creation.creer(slug, corps(), request.headers.get("Idempotency-Key", "").strip())
    return json(resultat, 201)


@tickets_v3_bp.get("/api/projects/<slug>/tickets/<ticket_id>")
def api_ticket_fiche(slug: str, ticket_id: str):
    """{ticket, runs, legacy_runs (lecture seule), delivery, integration} + le ticket à plat.
    LECTURE PURE."""
    return json(lectures.fiche(ticket_ou_refus(slug, ticket_id)))


@tickets_v3_bp.patch("/api/projects/<slug>/tickets/<ticket_id>")
@corps_attendu(title="texte ≤ 200 car.", prompt="texte")
def api_ticket_modifier(slug: str, ticket_id: str):
    """{title?, prompt?} — seulement tant que le ticket est `created` (409 `transition_refusee`)."""
    ticket = ticket_ou_refus(slug, ticket_id, geste=True)
    if ticket.get("state") != etats.CREATED:
        raise ticket_fsm.TransitionRefusee(ticket, "patch")
    payload = corps()
    champs = {cle: payload[cle] for cle in ("title", "prompt") if cle in payload}
    if not champs:
        raise Refus("champ_requis", "title ou prompt requis", 400, champs=["title", "prompt"])
    titre, prompt = validation.titre_et_prompt({**ticket, **champs})
    tickets.poser(slug, ticket, title=titre, prompt=prompt)
    return json({**ticket, **vue(ticket)})


@tickets_v3_bp.get("/api/projects/<slug>/tickets/<ticket_id>/events")
def api_ticket_evenements(slug: str, ticket_id: str):
    """?since=<seq> → {events:[{seq, at, kind, actor, data}]} : le journal (transitions,
    commentaires, demandes d'arrêt…). LECTURE PURE."""
    ticket = ticket_ou_refus(slug, ticket_id)
    since = request.args.get("since") or "0"
    return json({"events": ticket_fsm.events(slug, ticket_id, int(since) if since.isdigit() else 0),
                 **vue(ticket)})


@tickets_v3_bp.post("/api/projects/<slug>/tickets/<ticket_id>/events")
@corps_attendu(kind="comment (seule valeur)", text="texte, requis")
def api_ticket_noter(slug: str, ticket_id: str):
    """{kind: "comment", text} → 201 {seq} : une NOTE au journal, jamais un message à l'agent
    (pour lui parler : POST …/messages)."""
    ticket = ticket_ou_refus(slug, ticket_id)
    payload = corps()
    if (payload.get("kind") or "comment") != journal.COMMENT:
        raise Refus("kind_inconnu", "seul kind=comment peut être posé", 400,
                    kind=payload.get("kind"))
    texte = str(payload.get("text") or "").strip()
    if not texte:
        raise Refus("texte_requis", "text requis", 400)
    tickets.add_comment(slug, ticket, texte, False)
    return json({"ok": True, "kind": journal.COMMENT, "text": texte}, 201)


@tickets_v3_bp.get("/api/projects/<slug>/tickets/<ticket_id>/runs")
def api_ticket_runs(slug: str, ticket_id: str):
    """{runs (récent en tête), legacy_runs} — LECTURE PURE."""
    return json(lectures.runs(ticket_ou_refus(slug, ticket_id)))
