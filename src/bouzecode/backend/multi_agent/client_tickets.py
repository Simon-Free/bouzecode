# [desc] Client des routes cibles des tickets pour les outils d'agent (Agent, MessageAgent) : POST /api/projects/{slug}/tickets et …/{id}/messages, projet hérité du parent, réponse ramenée à la forme que lisent les outils. [/desc]
"""Les outils `Agent` et `MessageAgent` d'un manager parlent aux routes CIBLES (spec ticketing §5.6,
lot L3) ; les anciennes routes `dispatch` et `agent/message` ont été retirées au lot L6.

* le projet de l'enfant est celui du parent (`GET /api/agents/{parent}` → `project_slug`) sauf
  slug explicite : l'agent ne connaît pas les slugs, le client lit celui de son parent ;
* l'isolation est OBLIGATOIRE pour un manager (le serveur répond 400 `isolation_requise`) ;
* le titre est tiré du prompt (`titres.titre_lisible`, pur) ou du nom donné ;
* `Idempotency-Key` : un appel rejoué ne crée pas deux enfants.
Tout refus du serveur revient en `{routed: False, code, error, …details}` (forme lue par
`_spawn_web_ticket_agent`). Sans projet connu (parent rattaché à aucun projet ouvert, ou
inconnu du serveur), rien n'est créé : `{routed: False, code: "projet_requis", parent_unknown,
projets_ouverts}` — le serveur ne déduit JAMAIS un projet (arbitrage P9)."""
from __future__ import annotations

import hashlib
import os
import uuid

ORIGINE = "http://127.0.0.1:5056"
_ISOLATIONS = {"worktree+venv": "worktree_venv"}


# Le serveur web n'écoute pas toujours sur 5056 (bac à sable, second serveur) : `app.main` pose
# `BOUZECODE_WEB_BASE_URL`, hérité par les agents qu'il lance. `_sur_le_serveur` réécrit
# l'origine par défaut à l'APPEL — une URL déjà remplacée passe telle quelle.
_ORIGINE_PAR_DEFAUT = "http://127.0.0.1:5056"


def _sur_le_serveur(url: str) -> str:
    base = (os.environ.get("BOUZECODE_WEB_BASE_URL") or "").strip().rstrip("/")
    if base and url.startswith(_ORIGINE_PAR_DEFAUT):
        return base + url[len(_ORIGINE_PAR_DEFAUT):]
    return url


def _get_json(url: str) -> dict:
    """GET JSON (lecture des enfants : `enfants._web`, seam `_web_get` en test).
    Appel LOCAL → `core.local_http`, jamais proxyfié (cf. panne 407 du 2026-07-28)."""
    from ..core.local_http import local_json
    return local_json("GET", url, timeout=60)


def _url(chemin: str) -> str:
    return _sur_le_serveur(ORIGINE + chemin)


def _appel(methode: str, chemin: str, corps: dict | None = None, timeout: int = 60,
           en_tetes: dict | None = None) -> dict:
    from ..core.local_http import local_json
    return local_json(methode, _url(chemin), corps, timeout=timeout, headers=en_tetes)


def _refus(refus) -> dict:
    erreur = refus.corps.get("error")
    if not isinstance(erreur, dict):
        raise refus
    return {**(erreur.get("details") or {}), "routed": False, "code": erreur.get("code", ""),
            "error": erreur.get("message", "")}


def _projet_du_parent(parent: str) -> tuple[str, dict | None]:
    """(slug, refus) : le projet du parent (lu sur SA fiche, jamais deviné), ou le refus
    `projet_requis` qui nomme les projets ouverts — l'appelant relance avec `project_slug`."""
    from ..core.local_http import LocalServerError
    try:
        fiche = _appel("GET", f"/api/agents/{parent}") if parent else {}
    except LocalServerError as refus:
        if refus.status != 404:
            raise
        fiche = None
    slug = str((fiche or {}).get("project_slug") or "")
    if slug:
        return slug, None
    projets = _appel("GET", "/api/projects").get("projects") or []
    return "", {"routed": False, "code": "projet_requis", "parent_unknown": fiche is None,
                "projets_ouverts": [str(p.get("slug") or "") for p in projets]}


def _titre(body: dict) -> str:
    from ...web_v2.services.work.titres import titre_lisible
    prompt = str(body.get("prompt") or "")
    return (str(body.get("name") or "").strip() or titre_lisible(prompt)
            or prompt.strip().split("\n")[0][:80])[:200]


def creer_ticket(body: dict) -> dict:
    """Crée et lance le ticket de l'enfant ; rend la forme historique (`routed`, `ticket_id`,
    `project_slug`, `project_name`, `typology`, `scope_warnings`, `key?`)."""
    from ..core.local_http import LocalServerError
    parent = str(body.get("parent") or "")
    slug = str(body.get("project_slug") or "")
    if not slug:
        slug, refus = _projet_du_parent(parent)
        if refus is not None:
            return refus
    isolation = str(body.get("isolation") or "")
    demande = {"title": _titre(body), "prompt": body.get("prompt") or "",
               "typology": body.get("typology") or "", "model": body.get("model") or "",
               "isolation": _ISOLATIONS.get(isolation, isolation), "launch": True,
               "defer": body.get("defer", True) is not False,
               "parent": {"agent_id": parent,
                          "ticket_id": os.environ.get("BOUZECODE_TICKET_ID", "")},
               **{cle: body[cle] for cle in ("resume_branch", "work_branch", "doublon_assume",
                                             "name", "parent_turn") if body.get(cle)}}
    empreinte = "|".join(str(x) for x in (parent, body.get("parent_turn"), body.get("name"),
                                          body.get("prompt")))
    cle = hashlib.sha256(empreinte.encode("utf-8")).hexdigest()[:32] if body.get(
        "parent_turn") else uuid.uuid4().hex
    try:
        reponse = _appel("POST", f"/api/projects/{slug}/tickets", demande, timeout=180,
                         en_tetes={"Idempotency-Key": cle})
    except LocalServerError as refus:
        return _refus(refus)
    return {**reponse, "routed": True}


def message_a_l_enfant(parent: str, ticket_id: str, texte: str, interrompre: bool,
                       arreter: bool, lire_enfants=None) -> dict:
    """POST /api/projects/{slug}/tickets/{id}/messages ; le slug est lu dans MES enfants."""
    from ..core.local_http import LocalServerError
    lire = lire_enfants or (lambda: _appel("GET", f"/api/agents/{parent}/children"))
    enfants = (lire() or {}).get("children") or []
    slug = next((e.get("slug") for e in enfants if e.get("ticket_id") == ticket_id), "")
    if not slug:
        return {"ok": False, "error": f"le ticket {ticket_id} n'est pas un de tes enfants"}
    corps = {"text": texte, "mode": "now" if interrompre else "queue", "arreter": arreter,
             "origine": "parent"}
    try:
        return _appel("POST", f"/api/projects/{slug}/tickets/{ticket_id}/messages", corps)
    except LocalServerError as refus:
        erreur = refus.corps.get("error") if isinstance(refus.corps, dict) else None
        return {"ok": False, "error": (erreur or {}).get("message") or str(refus)}
