# [desc] Les outils de PILOTAGE du Bureau : un assistant qui commande la flotte, sans jamais coder. [/desc]
"""Outils de l'assistant de Bureau.

L'humain veut parler à un assistant (« fais ci, fais ca ») qui LANCE des taches,
ouvre des tickets, lit les reponses et remplit sa todolist. Cet assistant n'est pas
un moteur de chat neuf : c'est un agent bouzecode ordinaire dont les outils ne sont
pas Read/Edit/Bash mais les services du Bureau, appeles EN PROCESS.

Deux regles de conception :

* **Imports paresseux.** `backend/tools` ne doit pas dependre de `web_v2` au
  chargement (import circulaire + cout de demarrage pour TOUS les agents) : chaque
  handler importe son service dans son corps.
* **Aucun HTTP.** On appelle les services directement : pas de port a connaitre,
  pas d'authentification a traverser, pas de serveur a supposer demarre.

Le profil `bureau-assistant` (backend/profiles/builtin/) n'autorise QUE ces outils :
l'assistant pilote la flotte, il ne l'edite pas. Pour coder, il lance un agent.
"""
from __future__ import annotations

from ..core.tool_registry import ToolDef, register_tool
from .bureau_lancement import PARAMS_EXECUTION

FENETRE_DEFAUT = "7j"

#  Fenetre par defaut des sources d'activite TEAMS (Teams / Canaux). Constante
#  distincte de `FENETRE_DEFAUT` (qui reste a 7j pour le reste-a-faire) : le service
#  `ms_activite` vaut 30j, l'outil valait 7j, et le 2026-09-21 l'assistant a rappele
#  `Teams` sans fenetre apres un echec — il a obtenu 7 jours sans les avoir demandes,
#  perdant les 11, 12 et 13/09 sans le savoir. Les deux defauts doivent coincider.
FENETRE_DEFAUT_ACTIVITE = "30j"


# --------------------------------------------------------------------------- #
#  Handlers — chacun rend un dict JSON-able, jamais une exception nue.
# --------------------------------------------------------------------------- #

def reste_a_faire(fenetre: str = FENETRE_DEFAUT) -> dict:
    """Ce qu'il reste a faire sur les tickets termines de la fenetre.

    Lit les declarations `FinalAnswer.taches_restantes` telles quelles (aucun LLM ne
    relit une reponse pour la deviner) : « mes tickets des 2 derniers jours ou il me
    reste des trucs » est donc un simple `fenetre="2j"`.
    """
    from bouzecode.web_v2.services.work import todo_board
    from bouzecode.web_v2.services.work.todo_live import TodoSource

    return todo_board.collect(TodoSource(), fenetre=str(fenetre or FENETRE_DEFAUT))


# --------------------------------------------------------------------------- #
#  Taches — les MEMES objets que l'ecran du Bureau (SPEC v3 §4.9)
# --------------------------------------------------------------------------- #
#  Avant le 2026-09-23 cet outil ecrivait des « puces » (`todo_state`) et `Flotte` lisait la
#  table v1 `tasks` : l'assistant ne voyait pas les taches ecrites a l'ecran, et ce qu'il
#  « closait » y restait (audit Bureau F-14). Il parle desormais aux taches (micros) et aux
#  chantiers (macros), exactement comme l'ecran.
#
#  Deux voies, choisies selon le geste :
#  * lecture et edition du brief -> service en process (base SQLite partagee) ;
#  * tout ce qui LANCE, ARRETE ou PARLE a un agent -> HTTP vers le serveur local (ecrivain
#    unique des process d'agents), meme route que le bouton de l'ecran. `_http` est le point
#    d'injection des tests.


def _http(methode: str, chemin: str, corps: dict | None = None) -> dict:
    import os

    from ..core.local_http import local_json
    base = (os.environ.get("BOUZECODE_WEB_BASE_URL") or "http://127.0.0.1:5056").rstrip("/")
    return local_json(methode, base + chemin, corps, timeout=180)


def _appel(methode: str, chemin: str, corps: dict | None = None) -> dict:
    """Appel HTTP dont l'echec devient une REPONSE d'outil (jamais une exception nue)."""
    try:
        return {"ok": True, **(_http(methode, chemin, corps) or {})}
    except Exception as souci:  # noqa: BLE001 — LocalServerError, reseau : on le DIT
        #  Le serveur rend ses refus sous la forme unique {"error": {"code", "message"}} :
        #  le code machine (agent_actif, deja_en_cours...) remonte tel quel a l'assistant.
        erreur = (getattr(souci, "corps", None) or {}).get("error")
        code = erreur.get("code") if isinstance(erreur, dict) else ""
        return {"ok": False, "erreur": code or "serveur", "message": str(souci)}


def _moi() -> dict:
    """`{"parent": <mon agent_id>}` quand l'assistant tourne comme agent web, sinon `{}`.

    Le serveur rattache a ce parent le ticket de ce que l'assistant lance : c'est ce qui le
    fait REVEILLER quand la tache finit ou pose une question (`wake.process_wakes`). Sans lui
    le ticket naissait `dispatcher:manual`, comme un clic a l'ecran, et l'assistant n'avait
    aucun enfant : personne ne le reveillait jamais (TODO du 2026-09-25, §6). Meme lecture
    que l'outil `Agent` (`multi_agent.enfants.mon_id`) : le nom du dossier IPC.

    Hors web (assistant du terminal, `bouzecode --assistant`) : l'identite `tui:<id>` posee
    par `ui/assistant_tui.armer_identite` — ses taches lui sont rattachees et il les suit
    avec `Flotte(attendre_s=N)`."""
    import os
    from pathlib import Path
    ipc = os.environ.get("BOUZECODE_WEB_IPC_DIR") or ""
    if ipc:
        return {"parent": Path(ipc).stem}
    tui = os.environ.get("BOUZECODE_TUI_PARENT") or ""
    return {"parent": tui} if tui else {}


def _question_resumee(ligne: dict) -> dict | None:
    question = ligne.get("question") or {}
    if ligne.get("statut_ui") != "a_repondre" or not question:
        return None
    return {"texte": question.get("question", ""),
            "options": [o.get("label") if isinstance(o, dict) else o
                        for o in question.get("options") or []],
            "agent_id": question.get("agent_id", ""),
            "ticket_id": question.get("ticket_id", "")}


def _s(valeur) -> str:
    return str(valeur or "")


def _resume(ligne: dict) -> dict:
    """La forme rendue a l'assistant : ce qu'il faut pour en parler et agir."""
    from bouzecode.web_v2.services.work import classement
    passages = ligne.get("passages") or []
    vue = {
        "id": _s(ligne.get("id")),
        "titre": _s(ligne.get("titre")),
        "texte": _s(ligne.get("titre")),
        "chantier": _s((ligne.get("macro") or {}).get("titre")),
        "macro_id": _s(ligne.get("macro_id")),
        "projet": _s(ligne.get("projet_defaut") or ligne.get("projet_slug")),
        "statut": _s(ligne.get("statut_ui") or ligne.get("etat")),
        "libelle_statut": _s(ligne.get("libelle_statut")),
        "passages": len(passages),
    }
    dernier = passages[0] if passages else {}
    #  Le ticket du dernier passage : c'est lui que nomme le reveil de l'assistant, et que
    #  l'humain retrouve a l'ecran.
    optionnels = {"agent_id": dernier.get("agent_id"), "ticket_id": dernier.get("ticket_id"),
                  "raison_echec": ligne.get("raison_echec"),
                  "question": _question_resumee(ligne),
                  "classement": classement.texte(ligne.get("classement"))}
    vue.update({cle: valeur for cle, valeur in optionnels.items() if valeur})
    return vue


def _toutes_les_lignes() -> list[dict]:
    from bouzecode.web_v2.services.work import bureau_lignes
    vue = bureau_lignes.collect_lignes()
    lignes = [l for c in vue.get("chantiers") or [] for l in c.get("lignes") or []]
    return lignes + list(vue.get("non_rattachees") or [])


def _trouver(reference: str) -> dict | None:
    """Une tache par son id, ou a defaut par son TITRE exact (insensible a la casse)."""
    from bouzecode.web_v2.services.work import micros
    reference = str(reference or "").strip()
    if not reference:
        return None
    micro = micros.get_micro(reference)
    if micro is not None:
        return micro
    cible = reference.casefold()
    for micro in reversed(micros.list_micros()):
        if str(micro.get("titre") or "").strip().casefold() == cible:
            return micro
    return None


def _chantier_de(titre: str, macro_id: str, chantier: str) -> tuple[str, str]:
    """(macro_id, titre de tache) — accepte encore la convention « CHANTIER : titre »."""
    from bouzecode.web_v2.services.work import micros
    macro_id = str(macro_id or "").strip()
    if not macro_id and str(chantier or "").strip():
        macro_id = str(micros.ensure_macro(str(chantier).strip())["id"])
    if not macro_id and " : " in titre:
        tete, reste = titre.split(" : ", 1)
        if tete.strip() and reste.strip():
            macro_id = str(micros.ensure_macro(tete.strip())["id"])
            titre = reste.strip()
    return macro_id, titre


def _txt(valeur) -> str:
    return str(valeur or "").strip()


def _lister(p: dict) -> dict:
    lignes = [_resume(l) for l in _toutes_les_lignes()]
    if not p["include_closed"]:
        lignes = [l for l in lignes if l["statut"] not in ("faite", "abandonnee")]
    if p["statut"]:
        lignes = [l for l in lignes if l["statut"] == p["statut"]]
    return {"ok": True, "taches": lignes}


def _creer(p: dict) -> dict:
    from bouzecode.web_v2.services.work import micros
    titre = _txt(p["titre"])
    if not titre:
        return {"ok": False, "erreur": "titre_vide",
                "message": "Une tache a besoin d'un titre : ce qu'on veut OBTENIR."}
    macro, titre = _chantier_de(titre, p["macro_id"], p["chantier"])
    #  Provenance : la session de l'assistant qui a fabriqué la ligne (souvent depuis un mail
    #  ou un message Teams) — auditable et purgeable par vague (`micros.micros_de_session`).
    micro = micros.create_micro(titre=titre, corps=str(p["corps"] or p["intent"] or ""),
                                macro_id=macro, projet_slug=_txt(p["projet_slug"]),
                                origine="assistant", decision=bool(p["decision"]),
                                session_id=_txt(p.get("session_id")), source="assistant")
    return {"ok": True, "tache": {**_resume(micro), "id": micro["id"]}, "micro": micro}


def _repondre(p: dict) -> dict:
    if not _txt(p["agent_id"]) or not _txt(p["texte"]):
        return {"ok": False, "erreur": "agent_id_ou_texte_manquant",
                "message": "Pour repondre : agent_id (de la question) et texte."}
    return _appel("POST", f"/api/agents/{_txt(p['agent_id'])}/messages",
                  {"text": _txt(p["texte"]), "mode": "refuse"})


def _modifier(ident: str, p: dict) -> dict:
    from bouzecode.web_v2.services.work import micros
    champs = {"titre": _txt(p["titre"]), "corps": str(p["corps"] or p["intent"] or ""),
              "projet_slug": _txt(p["projet_slug"])}
    champs = {cle: valeur for cle, valeur in champs.items() if valeur}
    if not champs:
        return {"ok": False, "erreur": "rien_a_modifier"}
    return {"ok": True, "tache": _resume(micros.update_micro(ident, **champs))}


def _transmis(reponse: dict) -> list[dict]:
    """Ce que l'assistant doit pouvoir dire : qui a recu, et quand il le lira."""
    return [{"agent_id": t.get("agent_id", ""),
             "quand": "tour coupe, repart avec" if t.get("interruption") else
                      ("a sa prochaine etape" if t.get("en_tour") else "reveille avec"),
             **({"erreur": t.get("error")} if not t.get("ok") else {})}
            for t in reponse.get("transmis") or []]


def _preciser(ident: str, p: dict) -> dict:
    """Ajoute la precision au brief ET la transmet a l'agent qui travaille sur la tache
    (meme route que l'ecran). `interrompre` coupe son tour ; `sous_agents` l'etend a ses
    sous-agents encore joignables."""
    if not _txt(p["texte"]):
        return {"ok": False, "erreur": "texte_vide"}
    reponse = _appel("POST", f"/api/micros/{ident}/precisions",
                     {"texte": _txt(p["texte"]), "auteur": "assistant", "transmettre": True,
                      "interrompre": bool(p["interrompre"]), "sous_agents": bool(p["sous_agents"])})
    if not reponse.get("ok"):
        return reponse
    if reponse.get("doublon"):
        return {"ok": True, "doublon": True,
                "tache": _resume(reponse.get("micro") or {"id": ident}), "transmis": [],
                "message": ("Precision identique a la derniere, deja ajoutee et transmise a "
                            f"{(reponse.get('precision') or {}).get('created_at', '')} : ni "
                            "ajoutee ni retransmise. Rien a refaire.")}
    transmis = _transmis(reponse)
    return {"ok": True, "tache": _resume(reponse.get("micro") or {"id": ident}),
            "transmis": transmis,
            "message": ("Precision ajoutee au brief et transmise." if transmis else
                        "Precision ajoutee au brief ; aucun agent en cours a qui la transmettre.")}


def _deplacer(ident: str, p: dict) -> dict:
    from bouzecode.web_v2.services.work import micros
    cible, _ = _chantier_de("", p["macro_id"], p["chantier"])
    return {"ok": True, "tache": _resume(micros.update_micro(ident, macro_id=cible))}


def _execution(p: dict) -> dict:
    from .bureau_lancement import NOMS_EXECUTION, execution_depuis
    return execution_depuis(**{nom: p.get(nom) for nom in NOMS_EXECUTION})


def _lancer(ident: str, p: dict) -> dict:
    from .bureau_lancement import expliquer_injoignable
    return expliquer_injoignable(_appel("POST", f"/api/micros/{ident}/lancer",
                                        {"projet_slug": _txt(p["projet_slug"]), **_moi(),
                                         **_execution(p)}))


def _relancer(ident: str, p: dict) -> dict:
    from .bureau_lancement import expliquer_injoignable
    return expliquer_injoignable(_appel("POST", f"/api/micros/{ident}/relancer",
                                        {"retour": _txt(p["texte"]), "mode": _txt(p["mode"]),
                                         "projet_slug": _txt(p["projet_slug"]), **_moi(),
                                         **_execution(p)}))


def _clore(ident: str, p: dict) -> dict:
    etat = "abandonnee" if _txt(p["outcome"]).lower() in ("abandon", "abandonnee") else "faite"
    return _appel("POST", f"/api/micros/{ident}/etat", {"etat": etat})


def _vue_ensemble(p: dict) -> dict:
    """Le point sur UN chantier, en un appel : chaque tache, sa provenance, ses agents, ses
    livraisons, et les rapprochements (doublons, suites d'une tache reprise depuis)."""
    from bouzecode.web_v2.services.work import bilan_chantier
    reference = _txt(p["macro_id"]) or _txt(p["chantier"])
    if not reference:
        return {"ok": False, "erreur": "chantier_requis",
                "message": "Quel chantier ? Donne `chantier` (titre) ou `macro_id`."}
    return bilan_chantier.vue_ensemble(reference)


def _classer(motif: str):
    """`marquer_faite` / `marquer_doublon` / `marquer_caduque` : classe la tache SANS la lancer,
    avec le commentaire et le lien, signes « assistant » — visibles sur la carte du Bureau."""
    def geste(ident: str, p: dict) -> dict:
        if not _txt(p["commentaire"]):
            return {"ok": False, "erreur": "commentaire_requis",
                    "message": ("Dis pourquoi dans `commentaire` (ou c'est fait, de quoi c'est le "
                                "doublon, pourquoi c'est caduc) : l'utilisateur le lira sur la carte.")}
        reponse = _appel("POST", f"/api/micros/{ident}/classer",
                         {"motif": motif, "commentaire": _txt(p["commentaire"]),
                          "de": _txt(p["de"]), "auteur": "assistant"})
        return _echec(reponse) or {"ok": True, "classement": reponse.get("classement"),
                                   "tache": _resume(reponse.get("micro") or {"id": ident})}
    return geste


def _echec(reponse: dict) -> dict | None:
    """Le refus du serveur (409 agent actif, deja classee...) rendu tel quel, None si c'est passe.
    `error` : corps JSON du refus ; `erreur` : l'echec de transport vu par `_appel`."""
    if not (reponse.get("error") or reponse.get("erreur")):
        return None
    erreur = reponse.get("error")
    if isinstance(erreur, dict):  # forme unique du serveur : {"error": {"code", "message"}}
        return {"ok": False, "erreur": erreur.get("code") or "refus",
                "message": erreur.get("message", "")}
    return {"ok": False, "erreur": reponse.get("code") or reponse.get("erreur") or "refus",
            "message": reponse.get("error") or reponse.get("message", "")}


def _rouvrir(ident: str, p: dict) -> dict:
    """Annule un classement : la tache repart en brouillon, l'historique reste."""
    reponse = _appel("POST", f"/api/micros/{ident}/etat", {"etat": "brouillon", "auteur": "assistant"})
    return _echec(reponse) or {"ok": True, "tache": _resume(reponse.get("micro") or {"id": ident})}


#  Gestes sans tache designee, puis gestes sur UNE tache (`task_id` : id ou titre exact).
_GESTES_LIBRES = {"lister": _lister, "creer": _creer, "repondre": _repondre,
                  "vue_ensemble": _vue_ensemble}
_GESTES_SUR_TACHE = {"modifier": _modifier, "preciser": _preciser, "deplacer": _deplacer,
                     "lancer": _lancer, "relancer": _relancer, "clore": _clore,
                     "marquer_faite": _classer("faite"), "marquer_doublon": _classer("doublon"),
                     "marquer_caduque": _classer("caduque"), "rouvrir": _rouvrir}
ACTIONS_TACHES = ["lister", "vue_ensemble", "creer", "modifier", "preciser", "deplacer",
                  "lancer", "relancer", "clore", "marquer_faite", "marquer_doublon",
                  "marquer_caduque", "rouvrir", "repondre"]


def taches(action: str = "lister", titre: str = "", intent: str = "", corps: str = "",
           task_id: str = "", macro_id: str = "", chantier: str = "", projet_slug: str = "",
           texte: str = "", outcome: str = "fait", mode: str = "", agent_id: str = "",
           decision: bool = False, include_closed: bool = False, statut: str = "",
           interrompre: bool = False, sous_agents: bool = False, commentaire: str = "",
           de: str = "", session_id: str = "", projets: list | None = None,
           cible: str = "", fichiers_non_suivis: dict | None = None, mode_distant: str = "",
           commande_tests: str = "", navigateur: bool | None = None) -> dict:
    """Les TACHES du Bureau — les memes lignes que l'ecran, rangees par chantier.

    `session_id` : la session de l'agent appelant (posée par le registre, jamais par le
    modèle), estampillée sur les lignes créées (`micro_provenance`)."""
    parametres = dict(titre=titre, intent=intent, corps=corps, macro_id=macro_id,
                      chantier=chantier, projet_slug=projet_slug, texte=texte,
                      outcome=outcome, mode=mode, agent_id=agent_id, decision=decision,
                      include_closed=include_closed, statut=statut, interrompre=interrompre,
                      sous_agents=sous_agents, commentaire=commentaire, de=de,
                      session_id=session_id, projets=projets, cible=cible,
                      fichiers_non_suivis=fichiers_non_suivis, mode_distant=mode_distant,
                      commande_tests=commande_tests, navigateur=navigateur)
    geste = (action or "lister").strip().lower()
    if geste in _GESTES_LIBRES:
        return _GESTES_LIBRES[geste](parametres)
    if geste not in _GESTES_SUR_TACHE:
        return {"ok": False, "erreur": "action_inconnue", "attendu": ACTIONS_TACHES}
    micro = _trouver(task_id)
    if micro is None:
        return {"ok": False, "erreur": "not_found", "task_id": task_id}
    return _GESTES_SUR_TACHE[geste](micro["id"], parametres)


def decisions(action: str = "lister", decision_id: str = "",
              answer_key: str = "", answer_text: str = "") -> dict:
    """Les cartes de decision du Bureau : les lire, y repondre.

    Repondre PERSISTE d'abord la reponse ; la livraison a l'agent est un second temps
    dont l'echec est visible dans la file des livraisons ratees (invariant du store).
    """
    from bouzecode.web_v2.services.work import decisions as service

    geste = (action or "lister").strip().lower()
    if geste == "lister":
        return {"ok": True, "decisions": service.open_decisions(limit=200)}
    if geste == "echecs":
        return {"ok": True, "decisions": service.failed_deliveries(limit=50)}
    if geste == "repondre":
        if not str(decision_id or "").strip():
            return {"ok": False, "erreur": "decision_id_manquant"}
        resultat = service.answer(str(decision_id).strip(),
                                  answer_key=str(answer_key or ""),
                                  answer_text=str(answer_text or ""))
        statut = resultat.get("status")
        return {"ok": statut == "ok", "erreur": "" if statut == "ok" else statut,
                "decision": resultat.get("decision")}
    return {"ok": False, "erreur": "action_inconnue",
            "attendu": ["lister", "echecs", "repondre"]}


#  Ce que l'assistant voit d'une carte « A traiter ». Les signalements (outil Signaler) y
#  arrivent avec leur gravite, l'agent, sa profondeur et sa chaine de parents.
_CLES_CARTE = ("type", "titre", "agent_id", "raison", "question", "tache", "signalement_id",
               "gravite", "action_attendue", "profondeur", "parents", "ticket_id", "sous_agent")


def flotte(include_closed: bool = False, attendre_s: int = 0) -> dict:
    """Ce qui attend l'humain (« A traiter ») et les taches qui tournent : l'ecran du Bureau.

    `attendre_s` > 0 : attend d'abord (600 s max) qu'une tache lancee par l'assistant change
    d'etat ou qu'un signalement de sa lignee arrive, et rend ce delta (`bureau_suivi`)."""
    from bouzecode.web_v2.services.work import inbox
    if attendre_s:
        from .bureau_suivi import attendre
        return attendre(_moi().get("parent", ""), int(attendre_s))

    cartes = inbox.construire().get("items") or []
    lignes = [_resume(l) for l in _toutes_les_lignes()]
    en_cours = [l for l in lignes if l["statut"] == "en_cours"]
    rendu = {"ok": True, "a_traiter": [
        {k: c.get(k) for k in _CLES_CARTE if c.get(k) not in (None, "", [])}
        for c in cartes], "en_cours": en_cours,
        "compte": {"a_traiter": len(cartes), "en_cours": len(en_cours)}}
    if include_closed:
        rendu["taches"] = lignes
    return rendu


def lancer_agent(prompt: str = "", project_slug: str = "", typology: str = "",
                 model: str = "", isolation: str = "", defer: bool = False,
                 titre: str = "", macro_id: str = "", session_id: str = "",
                 projets: list | None = None, cible: str = "",
                 fichiers_non_suivis: dict | None = None, mode_distant: str = "",
                 commande_tests: str = "", navigateur: bool | None = None) -> dict:
    """Demarre un agent sur une consigne — TOUJOURS via une tache du Bureau.

    La consigne devient une tache (titre = 1re ligne, brief = le reste), puis la tache est
    lancee : l'agent est relie a une ligne que l'humain voit et peut relancer. Un prompt vide
    est REFUSE : sans consigne, l'agent n'a rien a faire."""
    if not str(prompt or "").strip():
        return {"ok": False, "erreur": "prompt_vide",
                "message": "Dis a l'agent ce qu'il doit obtenir avant de le lancer."}
    from bouzecode.web_v2.services.work import micros

    texte = str(prompt).strip()
    premiere = str(titre or "").strip() or micros.titre_depuis_corps(texte)
    micro = micros.create_micro(titre=premiere, corps=texte, macro_id=str(macro_id or ""),
                                projet_slug=str(project_slug or "").strip(), origine="assistant",
                                session_id=str(session_id or "").strip(), source="assistant")
    corps = {"projet_slug": str(project_slug or "").strip(), **_moi()}
    if typology:
        corps["profil"] = str(typology)
    if isolation:
        corps["isolation"] = str(isolation)
    from .bureau_lancement import execution_depuis, expliquer_injoignable
    corps.update(execution_depuis(projets, cible, fichiers_non_suivis, mode_distant,
                                  commande_tests, navigateur))
    lance = expliquer_injoignable(_appel("POST", f"/api/micros/{micro['id']}/lancer", corps))
    lance["tache_id"] = micro["id"]
    return lance


def _chantier_creer(service, titre: str, corps: str, projets, macro_id: str,
                    projet_slug: str) -> dict:
    try:
        chantier = service.create_macro(str(titre or ""), corps=str(corps or ""),
                                        projets=list(projets or []))
    except service.BriefInsuffisant:
        return {"ok": False, "erreur": "titre_vide",
                "message": ("Un chantier a besoin d'un titre : le RESULTAT visé, "
                            "pas un nom de projet.")}
    return {"ok": True, "chantier": chantier}


def _chantier_ajouter_projet(service, titre: str, corps: str, projets, macro_id: str,
                             projet_slug: str) -> dict:
    if not str(macro_id or "").strip():
        return {"ok": False, "erreur": "macro_id_manquant"}
    try:
        chantier = service.add_projet(str(macro_id).strip(), str(projet_slug or ""))
    except service.BriefInsuffisant:
        return {"ok": False, "erreur": "projet_slug_vide",
                "message": "Quel depot rattacher ? Donne son slug."}
    if chantier is None:
        return {"ok": False, "erreur": "not_found", "macro_id": macro_id}
    return {"ok": True, "chantier": chantier}


def chantiers(action: str = "lister", titre: str = "", corps: str = "",
              projets: list[str] | None = None, macro_id: str = "",
              projet_slug: str = "", etat: str = "") -> dict:
    """Les CHANTIERS (macro-taches) du Bureau : lister, creer, rattacher un depot.

    Un chantier n'est pas un projet : c'est un resultat qui traverse plusieurs depots et
    qui vit des mois.
    """
    from bouzecode.web_v2.services.work import micros as service

    geste = (action or "lister").strip().lower()
    if geste == "lister":
        return {"ok": True, "chantiers": service.list_macros(etat=str(etat or ""))}
    gestes = {"creer": _chantier_creer, "ajouter_projet": _chantier_ajouter_projet}
    if geste not in gestes:
        return {"ok": False, "erreur": "action_inconnue",
                "attendu": ["lister", "creer", "ajouter_projet"]}
    return gestes[geste](service, titre, corps, projets, macro_id, projet_slug)


# --------------------------------------------------------------------------- #
#  Schemas + enregistrement
# --------------------------------------------------------------------------- #

_FENETRE = {"type": "string",
            "description": "Fenetre de temps : '2j', '7j', '30j'. Defaut '7j'."}

#: Le mot-cle, partage par les trois sources. Ajoute parce que retrouver « le mail
#: ZEN/CONDOR » obligeait a derouler 200 apercus a l'oeil. La description dit la LIMITE
#: autant que la fonction : le filtre s'applique a ce qui a ete LU (le plafond `top`
#: coupe AVANT), donc une liste vide ne prouve pas l'absence du mot-cle.
_RECHERCHE_PARAM = {"type": "string", "description": (
    "Optionnel. Mot(s)-cle(s) pour ne garder que ce qui en parle : insensible a la casse "
    "ET aux accents, plusieurs mots separes par des espaces sont combines en ET (« zen "
    "condor » exige les deux). Les identifiants et les liens ne comptent pas comme une "
    "correspondance. ATTENTION a ce que ca ne fait PAS : le filtre s'applique aux "
    "elements effectivement LUS, apres le plafond `top` — si la reponse porte "
    "`tronque: true`, tu n'as cherche que dans un echantillon, et 0 resultat ne prouve "
    "RIEN. Rappelle alors l'outil avec un `top` plus grand avant de conclure. Le retour "
    "porte `total_lus` (avant filtre) a cote de `total` (apres filtre). Ignore quand un "
    "`message_id` / `conversation_id` est fourni : un identifiant designe deja un objet.")}

#: Le plafond, EXPOSE au modele : sans lui, une reponse coupee etait un cul-de-sac (il
#: voyait 50 mails annonces sur 30 jours, sans aucun moyen d'aller chercher le reste).
_TOP_MAILS_PARAM = {"type": "integer", "description": (
    "Optionnel. Nombre MAXIMUM de mails rendus (defaut 50, du plus recent au plus "
    "ancien). Si la reponse revient avec `tronque: true`, c'est que ce plafond a coupe "
    "la fenetre : rappelle l'outil avec un `top` plus grand (150, 300) avant de conclure "
    "quoi que ce soit sur la periode.")}
_TOP_CHATS_PARAM = {"type": "integer", "description": (
    "Optionnel. Nombre MAXIMUM de conversations rendues (defaut 30, les plus recemment "
    "actives). Augmente-le quand la reponse dit `tronque: true` : les conversations "
    "au-dela du plafond sont invisibles, pas vides.")}

def mails(fenetre: str = FENETRE_DEFAUT, top: int = 0, message_id: str = "",
          transport: Any = None, recherche: str = "", timeout: int = 0) -> dict:
    """Les mails Outlook recus sur la fenetre, via Microsoft Graph delegue.

    Un refus de consentement (Mail.Read non accorde) est une REPONSE, pas un crash :
    on la nomme (`erreur="authentification"`) pour que l'assistant le dise a l'humain
    au lieu d'inventer des taches qu'il n'a pas lues.

    `top` est le plafond de mails rendus. Il est EXPOSE au modele depuis le defaut du
    2026-09-09 : la reponse plafonnee a 50 ne couvrait que 3 jours d'une fenetre de 30
    demandee, et l'assistant n'avait aucun moyen ni de le voir ni de creuser. Le retour
    porte maintenant `tronque`, `couverture_debut/fin` et un `avertissement`.

    `message_id` est la porte de sortie OPT-IN vers le corps ENTIER d'un mail. La liste
    ne porte qu'un apercu de ~250 caracteres (budget tokens, pas limite de Graph) : sans
    ce chemin, un agent voyait passer un mail sans pouvoir le citer ni y repondre, et
    demandait a l'humain de recoller le texte (constat du 2026-09-21). Non fourni, rien
    ne change. `transport` n'est PAS expose au modele : point d'injection des tests.
    """
    from bouzecode.web_v2.services.work import ms_activite

    #  `timeout` est expose comme pour `Teams` (2026-10-15) : Mails n'avait que les 90s
    #  par defaut, sans aucun moyen d'insister quand Graph (ou sa connexion) traine.
    pont = transport or ms_activite.ActiviteTransport(
        timeout=int(timeout) if timeout else None)
    try:
        if message_id:
            mail = ms_activite.mail_complet(message_id, transport=pont)
            return {"ok": True, "message_id": message_id, "mail": mail}
        rapport = ms_activite.rapport_mails(
            fenetre, top=int(top) if top else ms_activite.TOP_MAILS,
            transport=pont, recherche=recherche)
    except ms_activite.TeamsAuthError as souci:
        return {"ok": False, "erreur": "authentification", "message": str(souci),
                "consigne": "Dis a l'humain que l'acces a sa boite Outlook n'est pas "
                            "autorise (consentement Mail.Read a accorder). N'invente "
                            "aucune tache."}
    except ms_activite.TeamsTransportError as souci:
        return {"ok": False, "erreur": "transport", "message": str(souci),
                "consigne": "Les mails n'ont PAS ete lus. Le message dit quelle etape "
                            "Graph a expire : si c'est la connexion, dis a l'humain "
                            "qu'une reconnexion Microsoft interactive est requise ; "
                            "sinon relance `Mails` avec un `timeout` plus grand (ex. "
                            "timeout=300). N'invente aucune tache."}
    except ValueError as souci:
        return {"ok": False, "erreur": "fenetre_invalide", "message": str(souci)}
    return rapport


def teams(fenetre: str = FENETRE_DEFAUT_ACTIVITE, conversation_id: str = "",
          message_id: str = "", top: int = 0, timeout: int = 0,
          transport: Any = None, recherche: str = "") -> dict:
    """Les conversations Teams recentes de l'humain et leurs messages sur la fenetre.

    Meme contrat que `mails` : jamais d'exception nue, un refus de consentement
    (Chat.Read) se DIT.
    """
    from bouzecode.web_v2.services.work import ms_activite

    #  `transport` n'est PAS expose au modele (absent du schema) : point d'injection
    #  des tests. `timeout` l'est, lui : sans ce pont, le schema annoncait un timeout
    #  reglable qui ne reglait rien (les 90s par defaut s'appliquaient quand meme).
    pont = transport or ms_activite.ActiviteTransport(
        timeout=int(timeout) if timeout else None)

    if conversation_id:
        #  Le mode liste tronque les corps et laisse des `messages_omis` : sans ce
        #  retour a la source, ce qu'on annonce comme non lu serait definitivement perdu.
        try:
            messages = ms_activite.messages_conversation(
                conversation_id, fenetre=fenetre, message_id=message_id,
                transport=pont)
        except ms_activite.TeamsAuthError as souci:
            return {"ok": False, "erreur": "authentification", "message": str(souci),
                    "consigne": "Dis a l'humain que l'acces a ses conversations Teams "
                                "n'est pas autorise (consentement Chat.Read a accorder)."}
        except ms_activite.TeamsTransportError as souci:
            return {"ok": False, "erreur": "transport", "message": str(souci)}
        except ValueError as souci:
            return {"ok": False, "erreur": "fenetre_invalide", "message": str(souci)}
        return {"ok": True, "conversation_id": conversation_id, "fenetre": fenetre,
                "total": len(messages), "messages": messages}

    try:
        rapport = ms_activite.rapport_chats(
            fenetre, top=int(top) if top else ms_activite.TOP_CHATS,
            transport=pont, recherche=recherche)
    except ms_activite.TeamsAuthError as souci:
        return {"ok": False, "erreur": "authentification", "message": str(souci),
                "consigne": "Dis a l'humain que l'acces a ses conversations Teams n'est "
                            "pas autorise (consentement Chat.Read a accorder). Ne devine "
                            "pas leur contenu."}
    except ms_activite.TeamsTransportError as souci:
        return {"ok": False, "erreur": "transport", "message": str(souci),
                "consigne": "Les conversations Teams n'ont PAS ete lues. Relance `Teams` "
                            "avec un `timeout` plus grand (ex. timeout=300) ou une "
                            "fenetre plus courte, et NE te rabats PAS sur une fenetre "
                            "par defaut sans le dire : annonce a l'humain la periode "
                            "reellement couverte."}
    except ValueError as souci:
        return {"ok": False, "erreur": "fenetre_invalide", "message": str(souci)}
    return rapport


def canaux(fenetre: str = FENETRE_DEFAUT_ACTIVITE, top: int = 0,
           sans_messages: bool = False, timeout: int = 0,
           transport: Any = None, recherche: str = "") -> dict:
    """Les messages des CANAUX d'equipe Teams sur la fenetre (lecture seule).

    Troisieme source, distincte de `mails` et de `teams` : /me/chats ne voit pas les
    canaux, donc une demande postee dans un canal etait invisible partout.
    """
    from bouzecode.web_v2.services.work import ms_activite

    plafond = int(top or 0) or ms_activite.TOP_CANAUX
    #  `transport` n'est PAS expose au modele (absent du schema) : c'est le point
    #  d'injection des tests, exactement comme `ms_activite.rapport_canaux(transport=)`.
    pont = transport or ms_activite.ActiviteTransport(
        timeout=int(timeout) if timeout else None)
    try:
        if sans_messages:
            #  Lister ses equipes et ses canaux ne demande que Team.ReadBasic.All +
            #  Channel.ReadBasic.All : ce chemin repond meme sur un tenant qui refuse
            #  la lecture des messages de canal.
            return ms_activite.rapport_equipes(top=plafond, transport=pont)
        return ms_activite.rapport_canaux(fenetre, top=plafond, transport=pont,
                                          recherche=recherche)
    except ms_activite.TeamsAuthError as souci:
        return {"ok": False, "erreur": "authentification", "message": str(souci),
                "consigne": "Dis a l'humain que la lecture des canaux d'equipe Teams "
                            "n'est pas autorisee (consentement ChannelMessage.Read.All "
                            "a accorder). Precise que les canaux n'ont PAS ete lus et "
                            "n'invente aucune tache."}
    except ms_activite.TeamsTransportError as souci:
        #  Une erreur de transport est le plus souvent un TIMEOUT. Sans consigne,
        #  l'assistant recevait `erreur: transport` nu et bricolait un repli (fenetre
        #  raccourcie sans le dire). On lui dit donc quoi faire ET quoi avouer.
        return {"ok": False, "erreur": "transport", "message": str(souci),
                "consigne": "Les canaux n'ont PAS ete lus. Relance `Canaux` avec un "
                            "`timeout` plus grand (ex. timeout=300) ou une fenetre plus "
                            "courte. Si ca echoue encore, dis a l'humain que les canaux "
                            "d'equipe n'ont pas pu etre lus et n'affirme SURTOUT pas que "
                            "rien n'y a ete demande."}
    except ValueError as souci:
        return {"ok": False, "erreur": "fenetre_invalide", "message": str(souci)}


_TOP_CANAUX_PARAM = {"type": "integer", "description": (
    "Optionnel. Nombre maximum de canaux d'equipe visites (defaut 30). Si la reponse "
    "porte `tronque: true`, rappelle l'outil avec un `top` plus grand : tu n'as pas "
    "tout lu.")}

#  Le timeout est REGLABLE depuis l'outil (2026-09-21) : la plomberie existait
#  (`ActiviteTransport(timeout=...)`) mais rien ne l'alimentait, donc l'assistant ne
#  pouvait que constater l'echec a 90s sans aucun moyen d'insister.
_TIMEOUT_PARAM = {"type": "integer", "description": (
    "Optionnel. Secondes accordees a CHAQUE appel Graph (defaut 90). Quand la reponse "
    "porte des `equipes_non_lues` ou une erreur `transport`, relance avec un timeout "
    "plus grand (ex. 300) ou une fenetre plus courte : les appels sont decoupes par "
    "equipe, donc ce delai s'applique a une equipe a la fois, pas a l'ensemble.")}

_TIMEOUT_MAILS_PARAM = {"type": "integer", "description": (
    "Optionnel. Secondes accordees a l'appel Graph de lecture des mails (defaut 90). "
    "Sur une erreur `transport` qui nomme une requete GET, relance avec un timeout plus "
    "grand (ex. 300) ; si elle nomme la connexion, un timeout plus grand n'y changera "
    "rien : une reconnexion interactive est requise.")}

#  Meme parametre que `_FENETRE`, mais le defaut des SOURCES D'ACTIVITE est 30j.
#  `_FENETRE` reste a 7j car elle sert aussi au reste-a-faire, qui est un autre domaine.
_FENETRE_ACTIVITE = {"type": "string", "description": (
    "Fenetre de temps : '2j', '7j', '30j'. Defaut '30j'.")}

def _adresses(saisie: str) -> list[str]:
    """Decoupe une saisie texte en adresses : le modele ecrit « a@x, b@y »."""
    return [morceau.strip() for morceau in str(saisie or "").replace(";", ",").split(",")
            if morceau.strip()]


def _panne_graph(souci: Exception, quoi: str) -> dict | None:
    """Traduit une panne d'ecriture Graph en REPONSE nommee, jamais en crash.

    Meme contrat que `mails()` : l'agent doit pouvoir REPETER le probleme a l'humain
    (consentement a accorder, panne de transport, saisie a corriger) au lieu de croire
    que le geste a reussi.
    """
    from bouzecode.web_v2.services.work import graph_bureau

    if isinstance(souci, graph_bureau.TeamsAuthError):
        return {"ok": False, "erreur": "authentification", "message": str(souci),
                "consigne": f"Dis a l'humain que {quoi} a echoue faute d'autorisation "
                            "Microsoft (consentement Mail.ReadWrite pour les brouillons, "
                            "Calendars.ReadWrite pour l'agenda). N'affirme PAS que "
                            "c'est fait."}
    if isinstance(souci, graph_bureau.TeamsTransportError):
        return {"ok": False, "erreur": "transport", "message": str(souci)}
    if isinstance(souci, ValueError):
        return {"ok": False, "erreur": "saisie_invalide", "message": str(souci)}
    return None


def brouillon(destinataires: str = "", objet: str = "", corps: str = "",
              cc: str = "") -> dict:
    """Depose un mail dans le dossier Brouillons d'Outlook. N'ENVOIE RIEN.

    C'est la validation humaine demandee : l'humain relit le brouillon dans Outlook et
    clique Envoyer lui-meme. Aucun agent ne peut envoyer un mail -- ni celui-ci, ni un
    autre : il n'existe aucune action d'envoi dans le script PowerShell.
    """
    from bouzecode.web_v2.services.work import graph_bureau

    try:
        charge = graph_bureau.default_transport().deposer_brouillon(
            destinataires=_adresses(destinataires),
            objet=str(objet or ""),
            corps=str(corps or ""),
            cc=_adresses(cc),
        )
    except Exception as souci:  # noqa: BLE001 - traduit puis relance si inconnu
        panne = _panne_graph(souci, "le depot du brouillon")
        if panne is None:
            raise
        return panne
    return {"ok": True, "id": str(charge.get("id") or ""),
            "lien": str(charge.get("webLink") or ""),
            "message": "Brouillon depose dans le dossier Brouillons d'Outlook. "
                       "RIEN n'est parti : dis a l'humain d'aller le relire et de "
                       "l'envoyer lui-meme."}


def creneau(sujet: str = "", debut: str = "", duree_minutes: int = 60) -> dict:
    """Bloque un creneau dans l'agenda : personne n'est invite, rien n'est envoye."""
    from bouzecode.web_v2.services.work import graph_bureau

    try:
        charge = graph_bureau.default_transport().bloquer_creneau(
            sujet=str(sujet or ""), debut=str(debut or ""),
            duree_minutes=int(duree_minutes or 60))
    except Exception as souci:  # noqa: BLE001
        panne = _panne_graph(souci, "le blocage du creneau")
        if panne is None:
            raise
        return panne
    return {"ok": True, "id": str(charge.get("id") or ""),
            "message": "Creneau bloque dans l'agenda (marque occupe, sans participant)."}


def reunion(sujet: str = "", debut: str = "", participants: str = "",
            duree_minutes: int = 30, corps: str = "") -> dict:
    """Cree une reunion Teams et envoie les invitations aux participants."""
    from bouzecode.web_v2.services.work import graph_bureau

    try:
        charge = graph_bureau.default_transport().organiser_reunion(
            sujet=str(sujet or ""), debut=str(debut or ""),
            participants=_adresses(participants),
            duree_minutes=int(duree_minutes or 30),
            corps=str(corps or ""))
    except Exception as souci:  # noqa: BLE001
        panne = _panne_graph(souci, "la creation de la reunion")
        if panne is None:
            raise
        return panne
    en_ligne = charge.get("onlineMeeting") if isinstance(charge.get("onlineMeeting"), dict) else {}
    return {"ok": True, "id": str(charge.get("id") or ""),
            "lien": str(en_ligne.get("joinUrl") or ""),
            "message": "Reunion creee et invitations envoyees."}


BUREAU_TOOL_SCHEMAS = [
    {
        "name": "Brouillon",
        "description": ("Prepare un mail Outlook et le DEPOSE dans le dossier Brouillons : "
                        "il n'envoie RIEN. C'est voulu — l'humain relit le brouillon dans "
                        "Outlook et l'envoie lui-meme, c'est sa validation. Ne dis JAMAIS "
                        "que le mail est envoye ou parti : dis qu'il attend dans les "
                        "brouillons. Destinataires et cc se donnent en texte separe par "
                        "des virgules. Si l'acces est refuse (consentement Mail.ReadWrite "
                        "absent), l'outil te le DIT : repete-le a l'humain."),
        "input_schema": {"type": "object", "properties": {
            "destinataires": {"type": "string",
                              "description": "Adresses separees par des virgules."},
            "objet": {"type": "string", "description": "Objet du mail."},
            "corps": {"type": "string", "description": "Texte du message."},
            "cc": {"type": "string",
                   "description": "Adresses en copie, separees par des virgules (facultatif)."},
        }, "required": ["destinataires", "objet"]},
    },
    {
        "name": "Creneau",
        "description": ("Bloque un creneau dans l'agenda Outlook de l'humain (marque "
                        "occupe, SANS participant, aucune invitation envoyee). Agis "
                        "directement, aucune validation n'est demandee pour ce geste. "
                        "`debut` est une date locale, ex. 2026-09-22T09:00 ; la fin est "
                        "calculee depuis `duree_minutes`. Si l'acces est refuse "
                        "(consentement Calendars.ReadWrite absent), l'outil te le DIT."),
        "input_schema": {"type": "object", "properties": {
            "sujet": {"type": "string", "description": "Ce que le creneau protege."},
            "debut": {"type": "string",
                      "description": "Debut local, ex. 2026-09-22T09:00."},
            "duree_minutes": {"type": "integer",
                              "description": "Duree en minutes (defaut 60)."},
        }, "required": ["sujet", "debut"]},
    },
    {
        "name": "Reunion",
        "description": ("Organise une reunion Teams : cree l'evenement, invite les "
                        "participants et rend le lien de jointure. Les invitations "
                        "PARTENT immediatement, aucune validation n'est demandee pour ce "
                        "geste. `participants` se donne en texte separe par des virgules ; "
                        "`debut` est une date locale, la fin est calculee depuis "
                        "`duree_minutes`."),
        "input_schema": {"type": "object", "properties": {
            "sujet": {"type": "string", "description": "Titre de la reunion."},
            "debut": {"type": "string",
                      "description": "Debut local, ex. 2026-09-23T10:00."},
            "participants": {"type": "string",
                             "description": "Adresses separees par des virgules."},
            "duree_minutes": {"type": "integer",
                              "description": "Duree en minutes (defaut 30)."},
            "corps": {"type": "string",
                      "description": "Ordre du jour (facultatif)."},
        }, "required": ["sujet", "debut", "participants"]},
    },
    {
        "name": "Canaux",
        "description": ("Les messages des CANAUX D'EQUIPE Teams sur la fenetre (lecture "
                        "seule, via Microsoft Graph delegue). C'est la source que `Teams` "
                        "ne couvre PAS : `Teams` lit les chats 1-1 et de groupe, un canal "
                        "d'equipe n'y apparait jamais. Pour « qu'est-ce qu'on m'a demande "
                        "et que je n'ai pas fait », croise TROIS sources : Mails, Teams et "
                        "Canaux. La reponse porte `tronque`, `plafond` et `avertissement` : "
                        "si `tronque` est vrai, elargis `top` avant de conclure. Si l'acces "
                        "est refuse (ChannelMessage.Read.All non consenti), l'outil te le "
                        "DIT — dis-le a l'humain et precise que les canaux n'ont pas ete "
                        "lus, n'invente aucune tache."),
        "input_schema": {"type": "object", "properties": {
            "fenetre": _FENETRE_ACTIVITE, "top": _TOP_CANAUX_PARAM,
            "timeout": _TIMEOUT_PARAM, "recherche": _RECHERCHE_PARAM,
            "sans_messages": {"type": "boolean", "description": (
                "Optionnel. `true` rend la simple LISTE des equipes et des canaux dont "
                "l'humain est membre, sans lire aucun message. C'est le repli quand la "
                "reponse porte `messages_indisponibles: true` : lister un canal ne "
                "demande aucun droit special, en lire les messages demande "
                "ChannelMessage.Read.All. Sers-t'en pour dire a l'humain OU aller "
                "regarder au lieu de lui repondre que tu ne vois rien.")},
        }, "required": []},
    },
    {
        "name": "Mails",
        "description": ("Les mails Outlook RECUS sur la fenetre, PLAFONNES a `top` (defaut 50, "
                        "du plus recent au plus ancien) : quand la reponse porte "
                        "`tronque: true`, des mails de la fenetre MANQUENT — rappelle "
                        "l'outil avec un `top` plus grand et cite `couverture_debut` au "
                        "lieu de la fenetre demandee. "
                        "(lecture seule, via Microsoft "
                        "Graph delegue). Sert a repondre a « quelles taches m'a-t-on donnees "
                        "et que je n'ai pas faites » : tu lis les mails, tu en deduis les "
                        "demandes. Si l'acces est refuse (consentement Mail.Read absent), "
                        "l'outil te le DIT — dis-le a l'humain, n'invente aucune tache. "
                        "La liste ne rend qu'un APERCU de chaque mail (~250 caracteres) : "
                        "pour lire un mail EN ENTIER (le citer, y repondre, en extraire des "
                        "dates), rappelle l'outil avec le `message_id` = l'`id` que la liste "
                        "t'a donne. Ne demande JAMAIS a l'humain de recoller un texte que "
                        "tu peux lire toi-meme ainsi."),
        "input_schema": {"type": "object", "properties": {
            "fenetre": _FENETRE,
            "top": _TOP_MAILS_PARAM,
            "timeout": _TIMEOUT_MAILS_PARAM,
            "recherche": _RECHERCHE_PARAM,
            "message_id": {"type": "string", "description": (
                "Optionnel, et c'est la SEULE facon de lire un mail en entier : l'`id` "
                "d'un mail rendu par la liste. Le corps complet remplace alors l'apercu "
                "tronque, et `fenetre`/`top` n'ont plus d'effet. Non fourni (defaut), tu "
                "obtiens la liste d'apercus comme avant.")},
        }, "required": []},
    },
    {
        "name": "Teams",
        "description": ("Les conversations Teams recentes de l'humain (chats 1-1 et de groupe, "
                        "PAS les canaux d'equipe : pour ceux-la, appelle `Canaux`) "
                        "avec leurs messages sur la fenetre, en lecture seule via Microsoft "
                        "Graph delegue. Meme usage que Mails : reperer ce qu'on lui a demande. "
                        "Si l'acces est refuse (consentement Chat.Read absent), l'outil te le "
                        "DIT — ne devine pas le contenu des conversations. La liste est "
                        "PLAFONNEE : `tronque: true` veut dire que des conversations "
                        "entieres manquent (rappelle avec un `top` plus grand), et "
                        "`messages_omis_total` / `conversations_vides` que des messages ont "
                        "ete rognes (retourne-y avec `conversation_id`). Ne conclus pas "
                        "« rien d'autre ne m'a ete demande » sur une reponse tronquee."),
        "input_schema": {"type": "object", "properties": {
            "fenetre": _FENETRE_ACTIVITE,
            "top": _TOP_CHATS_PARAM,
            "timeout": _TIMEOUT_PARAM,
            "recherche": _RECHERCHE_PARAM,
            "conversation_id": {"type": "string", "description": (
                "Optionnel. L'`id` d'UNE conversation pour en relire les messages a la "
                "demande, au lieu de la liste allegee. A utiliser quand une conversation "
                "annonce `messages_omis` (tu n'as pas tout vu) ou qu'un corps finit par "
                "un `…` (il etait tronque).")},
            "message_id": {"type": "string", "description": (
                "Optionnel, avec `conversation_id`. L'`id` d'un message precis pour "
                "obtenir son contenu COMPLET, sans troncature.")},
        }, "required": []},
    },
    {
        "name": "ResteAFaire",
        "description": ("Ce qu'il RESTE a faire sur les tickets termines de la fenetre, "
                        "lu dans ce que chaque agent a declare en cloturant. Reponds a "
                        "« mes tickets des 2 derniers jours ou il me reste des trucs » "
                        "avec fenetre='2j'."),
        "input_schema": {"type": "object", "properties": {"fenetre": _FENETRE},
                         "required": []},
    },
    {
        "name": "Taches",
        "description": ("Les TACHES du Bureau — exactement les lignes que l'humain voit, rangees "
                        "par chantier. action : 'lister' (defaut ; statut = brouillon, "
                        "a_decider, en_cours, a_repondre, a_relire, en_echec), 'creer' (titre "
                        "obligatoire ; corps = le brief ; macro_id ou chantier ; projet_slug), "
                        "'modifier' (task_id + titre/corps/projet_slug), 'preciser' (task_id + "
                        "texte : ajoute une precision au brief ET la transmet a l'agent qui "
                        "travaille sur la tache — lue a sa prochaine etape ; interrompre=true "
                        "coupe son tour), 'deplacer' (task_id + macro_id "
                        "ou chantier), 'lancer' (task_id, projet_slug si la tache n'a pas de "
                        "depot : lance un agent RELIE a la tache ; projets / cible / fichiers_non_suivis "
                        "= ou et avec quoi il tourne, cf. Projets), 'relancer' (task_id + texte "
                        "= ce qui ne va pas ; mode continuer|nouvel_agent), 'clore' (task_id, "
                        "outcome fait|abandon), 'repondre' (agent_id + texte : repond a la "
                        "question d'un agent). 'vue_ensemble' (chantier ou macro_id) : le point "
                        "sur un chantier en un appel — chaque tache, qui l'a creee et quand, "
                        "brief, agents, livraisons, precisions, rapprochements. "
                        "'marquer_faite' (task_id + commentaire ; de = la tache qui l'a faite), "
                        "'marquer_doublon' (task_id + de + commentaire), 'marquer_caduque' "
                        "(task_id + commentaire) : classe SANS lancer, commentaire visible sur la "
                        "carte ; refuse si un agent y travaille. 'rouvrir' (task_id) annule. "
                        "Annonce toujours l'`id` et le titre de la tache."),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ACTIONS_TACHES},
                "task_id": {"type": "string", "description": (
                    "L'`id` de la tache (rendu par 'lister' ou 'creer'). Le TITRE exact est "
                    "accepte a defaut.")},
                "titre": {"type": "string", "description": (
                    "Une ligne : le resultat vise. « CHANTIER : titre » range la tache sous ce "
                    "chantier (cree s'il n'existe pas).")},
                "corps": {"type": "string", "description": (
                    "Le brief long (markdown) : contexte, fichiers, critere d'acceptation. "
                    "C'est ce que l'agent recevra.")},
                "intent": {"type": "string", "description": "Synonyme de `corps` (historique)."},
                "macro_id": {"type": "string", "description": "Id du chantier (Chantiers lister)."},
                "chantier": {"type": "string", "description": "Titre du chantier, a defaut d'id."},
                "projet_slug": {"type": "string", "description": "Depot vise par la tache."},
                "texte": {"type": "string", "description": (
                    "Precision ('preciser'), retour ('relancer') ou reponse ('repondre').")},
                "mode": {"type": "string", "enum": ["continuer", "nouvel_agent"],
                         "description": "Pour 'relancer' : meme agent ou nouvel agent."},
                "agent_id": {"type": "string", "description": "Pour 'repondre'."},
                "outcome": {"type": "string", "description": "Pour 'clore' : 'fait' ou 'abandon'."},
                "decision": {"type": "boolean", "description": (
                    "Pour 'creer' : vrai = arbitrage humain a trancher, pas un travail d'agent.")},
                "statut": {"type": "string", "description": "Filtre de 'lister'."},
                "include_closed": {"type": "boolean", "description": (
                    "Pour 'lister' : inclure aussi les taches faites ou abandonnees.")},
                "interrompre": {"type": "boolean", "description": (
                    "Pour 'preciser' : couper le tour en cours de l'agent pour qu'il reparte "
                    "AUSSITOT avec la precision. Seulement si elle change la direction du "
                    "travail ; sinon (defaut) il la lit a sa prochaine etape.")},
                "sous_agents": {"type": "boolean", "description": (
                    "Pour 'preciser' : la transmettre aussi a ses sous-agents en cours.")},
                "commentaire": {"type": "string", "description": (
                    "Pour 'marquer_*' : pourquoi, en une phrase que l'utilisateur lira sur la "
                    "carte (ex. « fait dans la tache 84fef31c, tour de retours du 25/09, "
                    "commit 0059681 »).")},
                "de": {"type": "string", "description": (
                    "Pour 'marquer_doublon' (obligatoire) : l'id de la tache qui porte le "
                    "travail ; pour 'marquer_faite' (optionnel) : l'id de la tache qui l'a fait.")},
                **PARAMS_EXECUTION,
            },
            "required": [],
        },
    },
    {
        "name": "Chantiers",
        "description": ("Les CHANTIERS (macro-taches) : un resultat qui traverse "
                        "PLUSIEURS depots et vit des mois, pas un projet et pas une "
                        "tache. action='lister' (defaut), 'creer' (titre obligatoire, "
                        "corps = le brief, projets = slugs des depots concernes), "
                        "'ajouter_projet' (macro_id + projet_slug) pour rattacher un "
                        "depot en cours de route. Un besoin ponctuel = Taches, pas ici."),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["lister", "creer", "ajouter_projet"]},
                "titre": {"type": "string",
                          "description": "Le resultat visé par le chantier, pour 'creer'."},
                "corps": {"type": "string", "description": "Le brief du chantier."},
                "projets": {"type": "array", "items": {"type": "string"},
                            "description": "Slugs des depots concernes."},
                "macro_id": {"type": "string", "description": "Pour 'ajouter_projet'."},
                "projet_slug": {"type": "string",
                                "description": "Depot a rattacher, pour 'ajouter_projet'."},
                "etat": {"type": "string",
                         "description": "Filtre d'etat pour 'lister' (vide = tous)."},
            },
            "required": [],
        },
    },
    {
        "name": "Decisions",
        "description": ("Les cartes de decision qui attendent l'humain. action='lister' "
                        "(defaut), 'echecs' (reponses non livrees), 'repondre' "
                        "(decision_id + answer_key ou answer_text)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["lister", "echecs", "repondre"]},
                "decision_id": {"type": "string"},
                "answer_key": {"type": "string", "description": "Cle de l'option choisie."},
                "answer_text": {"type": "string", "description": "Reponse libre."},
            },
            "required": [],
        },
    },
    {
        "name": "Flotte",
        "description": ("Ce qui attend l'humain (questions d'agents, livraisons a relire, agents "
                        "arretes, decisions, SIGNALEMENTS d'agents avec gravite et lignee) et les "
                        "taches en cours : le haut du Bureau. attendre_s=N (600 max) : attend "
                        "qu'une tache que TU as lancee change d'etat ou qu'un signalement arrive, "
                        "et rend le delta — le moyen de suivre sans boucler."),
        "input_schema": {"type": "object",
                         "properties": {"include_closed": {"type": "boolean"},
                                        "attendre_s": {"type": "integer", "description": (
                                            "Optionnel : attente maximale en secondes (borne "
                                            "600). Rend la main au premier changement.")}},
                         "required": []},
    },
    {
        "name": "LancerAgent",
        "description": ("Demarre un agent sur une consigne (c'est LUI qui codera). La consigne "
                        "devient une TACHE du Bureau puis est lancee : l'humain la voit et peut "
                        "la relancer. prompt obligatoire ; project_slug = le depot (obligatoire "
                        "si la tache n'en a pas par son chantier)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Ce que l'agent doit obtenir."},
                "titre": {"type": "string", "description": "Titre court de la tache (optionnel)."},
                "project_slug": {"type": "string"},
                "macro_id": {"type": "string", "description": "Chantier de rattachement."},
                "typology": {"type": "string", "description": "Profil d'agent."},
                "isolation": {"type": "string",
                              "description": "shared | worktree | worktree+venv"},
                "defer": {"type": "boolean", "description": (
                    "Accepte pour compatibilite ; le lancement rend toujours la main des la "
                    "tache creee (la preparation continue sur le serveur).")},
                **PARAMS_EXECUTION,
            },
            "required": ["prompt"],
        },
    },
]


_PARAMS_LANCER = ("prompt", "project_slug", "typology", "model", "isolation", "defer", "titre",
                  "macro_id", "projets", "cible", "fichiers_non_suivis", "mode_distant",
                  "commande_tests", "navigateur")


def register() -> None:
    """Enregistre les outils de pilotage dans le registry vivant.

    Idempotent en pratique : `register_tool` remplace une definition de meme nom.
    Ces outils ne sont PAS dans FRAMEWORK_ALWAYS_ON, exactement pour qu'un profil
    puisse les autoriser (bureau-assistant) ou les ignorer (tous les autres).
    """
    schemas = {schema["name"]: schema for schema in BUREAU_TOOL_SCHEMAS}
    definitions = [
        #  `top` DOIT etre relaye : l'exposer dans le schema sans le passer au handler
        #  redonnait au modele un levier inoperant (defaut corrige le 2026-09-13).
        #  Ecritures Graph. `Brouillon` est read_only=False mais ne fait RIEN partir :
        #  le mail attend dans Brouillons, ou l'humain valide. La validation ne pouvait
        #  passer ni par les permissions (accept-all rend True) ni par une question posee
        #  par l'outil (seul AskUserQuestion met un tour en pause) : elle est portee par
        #  Outlook lui-meme.
        ToolDef(name="Brouillon", schema=schemas["Brouillon"],
                func=lambda p, c: brouillon(**p),
                read_only=False, concurrent_safe=False),
        ToolDef(name="Creneau", schema=schemas["Creneau"],
                func=lambda p, c: creneau(**p),
                read_only=False, concurrent_safe=False),
        ToolDef(name="Reunion", schema=schemas["Reunion"],
                func=lambda p, c: reunion(**p),
                read_only=False, concurrent_safe=False),
        ToolDef(name="Mails", schema=schemas["Mails"],
                func=lambda p, c: mails(p.get("fenetre") or FENETRE_DEFAUT,
                                        top=int(p.get("top") or 0),
                                        message_id=p.get("message_id") or ""),
                read_only=True, concurrent_safe=True),
        ToolDef(name="Teams", schema=schemas["Teams"],
                func=lambda p, c: teams(**p),
                read_only=True, concurrent_safe=True),
        ToolDef(name="Canaux", schema=schemas["Canaux"],
                func=lambda p, c: canaux(p.get("fenetre") or FENETRE_DEFAUT,
                                         top=int(p.get("top") or 0),
                                         sans_messages=bool(p.get("sans_messages"))),
                read_only=True, concurrent_safe=True),
        ToolDef(name="ResteAFaire", schema=schemas["ResteAFaire"],
                func=lambda p, c: reste_a_faire(p.get("fenetre") or FENETRE_DEFAUT),
                read_only=True, concurrent_safe=True),
        ToolDef(name="Taches", schema=schemas["Taches"],
                #  La session vient de la BOUCLE (`config`), jamais des paramètres du modèle.
                func=lambda p, c: taches(**{**p, "session_id": str(c.get("_session_id") or "")}),
                read_only=False, concurrent_safe=False),
        ToolDef(name="Chantiers", schema=schemas["Chantiers"],
                func=lambda p, c: chantiers(**p),
                read_only=False, concurrent_safe=False),
        ToolDef(name="Decisions", schema=schemas["Decisions"],
                func=lambda p, c: decisions(**p),
                read_only=False, concurrent_safe=False),
        ToolDef(name="Flotte", schema=schemas["Flotte"],
                func=lambda p, c: flotte(bool(p.get("include_closed")),
                                         attendre_s=int(p.get("attendre_s") or 0)),
                read_only=True, concurrent_safe=True),
        ToolDef(name="LancerAgent", schema=schemas["LancerAgent"],
                func=lambda p, c: lancer_agent(**{k: v for k, v in p.items()
                                                  if k in _PARAMS_LANCER},
                                               session_id=str(c.get("_session_id") or "")),
                read_only=False, concurrent_safe=False),
    ]
    for definition in definitions:
        register_tool(definition)
