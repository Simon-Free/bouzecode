# [desc] Vue des tâches du Bureau selon la SPEC v3 : passages (un par agent lancé), statut UI, récap, joignabilité. [/desc]
"""Ce que le Bureau refait (SPEC §1.2, §4.6) a besoin de savoir, par TÂCHE :

* son **statut UI** — brouillon, à trancher, en cours, attend ta réponse, à relire, en échec,
  faite, abandonnée — dérivé des preuves, jamais saisi (sauf faite/abandonnée) ;
* ses **passages** : un par ticket lancé depuis elle, chacun avec l'état de son agent dans le
  lexique unique (`lexique.py`), le récap de sa réponse finale, la branche, l'intégration ;
* si l'agent du dernier passage est **joignable** (défaut « Continuer » de la relance).

Ce module ne remplace pas `bureau_lignes` : il l'enrichit. Tous les index (tickets, agents,
statuts, retours) sont lus UNE fois pour tout l'écran, puis chaque tâche est un lookup mémoire —
même discipline que `bureau_lignes._statuts_des_tickets` (jamais un `load_agent` par ligne).
La seule lecture disque par passage est la session d'un agent FINI (pour son récap), faite une
fois par version du fichier et retenue sur disque (`sessions/empreintes.py`).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from ..sessions import empreintes
from . import lexique

#  Durée de mémorisation de la vue complète. 0 = aucune (les tests la coupent : ils écrivent
#  l'état d'un agent sur disque puis relisent aussitôt).
CACHE_TTL = 3.0
_cache_lock = threading.Lock()
_caches: dict[str, dict] = {}

RESUME_MAX = 1200

ORDRE_STATUT = {"a_repondre": 0, "en_echec": 1, "a_relire": 2, "a_decider": 3,
                "en_cours": 4, "brouillon": 5, "faite": 6, "abandonnee": 7}


def invalider() -> None:
    with _cache_lock:
        _caches.clear()


#  Rafraîchissement EN FOND (`en_fond=True`) : passé `CACHE_TTL`, une valeur de même clé est
#  encore servie telle quelle pendant `PEREMPTION_MAX` s, et recalculée dans un thread (un seul
#  à la fois par emplacement). Au-delà, ou si la clé a changé (une écriture), recalcul
#  synchrone comme avant.
PEREMPTION_MAX = 120.0
_en_cours: set[str] = set()


_ECHEC = object()


def _ranger(emplacement: str, cle, valeur, debut: float, en_fond: bool, cle_rangee=None) -> None:
    """Range une valeur calculée à partir de `debut` (sous la clé `cle_rangee`, défaut `cle`),
    sous `_cache_lock`, SANS écraser une valeur de même clé dont le calcul a commencé plus
    tard : la boîte (synchrone) et les pastilles (en fond) partagent l'emplacement « inbox »,
    et un recalcul de fond parti avant une lecture synchrone ne doit pas remettre l'ancien
    compte par-dessus le nouveau."""
    cle_rangee = cle if cle_rangee is None else cle_rangee
    slot = _caches.get(emplacement)
    if slot is not None and slot["cle"] == cle_rangee and slot.get("debut", float("-inf")) > debut:
        return
    #  En fond, une écriture a pu changer la clé pendant le calcul : on ne l'écrase pas.
    if en_fond and slot is not None and slot["cle"] != cle:
        return
    _caches[emplacement] = {"at": time.monotonic(), "debut": debut, "cle": cle_rangee,
                            "valeur": valeur}


def _recalculer_en_fond(cle, calcul, emplacement: str, cle_apres=None) -> None:
    valeur = _ECHEC
    debut = time.monotonic()
    try:
        valeur = calcul()
    except Exception:  # noqa: BLE001 — l'ancienne valeur reste servie jusqu'à PEREMPTION_MAX
        pass
    finally:
        cle_rangee = cle_apres(cle) if cle_apres and valeur is not _ECHEC else cle
        with _cache_lock:
            _en_cours.discard(emplacement)
            if valeur is not _ECHEC:
                _ranger(emplacement, cle, valeur, debut, en_fond=True, cle_rangee=cle_rangee)


_ABSENTE = object()
#  Un calcul SYNCHRONE à la fois par emplacement. Au premier affichage du Bureau, le navigateur
#  demande d'un coup /api/inbox, /api/nav/counts et /api/lignes : sans ce verrou, la boîte
#  était calculée deux fois en parallèle (et les lignes trois), chacun ralentissant l'autre.
_calculs: dict[str, threading.Lock] = {}


def _servie(cle, calcul, emplacement: str, en_fond: bool, cle_apres=None):
    """La valeur mémorisée servable telle quelle, sinon `_ABSENTE`."""
    with _cache_lock:
        slot = _caches.get(emplacement)
        if not slot or slot["cle"] != cle:
            return _ABSENTE
        age = time.monotonic() - slot["at"]
        if age < CACHE_TTL:
            return slot["valeur"]
        if en_fond and age < PEREMPTION_MAX:
            if emplacement not in _en_cours:
                _en_cours.add(emplacement)
                threading.Thread(target=_recalculer_en_fond,
                                 args=(cle, calcul, emplacement, cle_apres),
                                 name=f"taches_vue-{emplacement}", daemon=True).start()
            return slot["valeur"]
    return _ABSENTE


def _verrou_de_calcul(emplacement: str) -> threading.Lock:
    with _cache_lock:
        return _calculs.setdefault(emplacement, threading.Lock())


def memorise(cle, calcul, emplacement: str = "lignes", en_fond: bool = False, cle_apres=None):
    """Sert la dernière valeur de `emplacement` si elle a moins de `CACHE_TTL` s et la même clé.

    `en_fond` : une valeur de même clé plus vieille que `CACHE_TTL` (mais de moins de
    `PEREMPTION_MAX` s) est servie aussitôt, et recalculée en fond pour l'appel suivant.

    `cle_apres(cle)` : la clé sous laquelle RANGER la valeur une fois calculée (défaut : `cle`),
    pour un calcul qui fait lui-même avancer la clé (cf. `memorise_a_part`)."""
    if CACHE_TTL <= 0:
        return calcul()
    valeur = _servie(cle, calcul, emplacement, en_fond, cle_apres)
    if valeur is not _ABSENTE:
        return valeur
    with _verrou_de_calcul(emplacement):
        #  Un autre thread vient peut-être de la calculer pendant qu'on attendait le verrou (et
        #  de la ranger sous sa clé d'après calcul).
        valeur = _servie(cle_apres(cle) if cle_apres else cle, calcul, emplacement, en_fond=False)
        if valeur is not _ABSENTE:
            return valeur
        debut = time.monotonic()
        valeur = calcul()
        cle_rangee = cle_apres(cle) if cle_apres else cle
        with _cache_lock:
            _ranger(emplacement, cle, valeur, debut, en_fond=False, cle_rangee=cle_rangee)
    return valeur


def cle_courante() -> tuple[int, int]:
    """Clé des vues mémorisées du Bureau : génération des écritures de tâches ET génération du
    parc (`fleet_vue.generation` : un agent apparu, disparu, ou dont l'état MONTRÉ a changé de
    classe). Avec la seule première, un agent qui pose une question ou finit sans écrire de
    tâche laissait la boîte et les pastilles sur leur ancienne valeur (jusqu'à 120 s pour les
    pastilles)."""
    from . import fleet_vue, micros as micros_mod
    return micros_mod.generation(), fleet_vue.generation()


def _cle_apres_calcul(cle_avant: tuple[int, int]) -> tuple[int, int]:
    """Clé de rangement d'une vue qui lit l'arbre des agents (la boîte).

    Lire l'arbre NOTE ce qu'il montre (`fleet_vue.noter`) et fait avancer la génération du parc
    dès qu'un agent a changé de classe : rangée sous la clé d'AVANT, la boîte tout juste calculée
    était déjà périmée, et l'appel suivant (/api/nav/counts) la recalculait en ligne — la
    seconde lente inexpliquée du 2026-09-29. Elle reflète l'arbre qu'elle vient de lire : on la
    range sous la génération de parc d'APRÈS. Pas si une tâche a été écrite pendant le calcul :
    celle-là, la valeur ne l'a peut-être pas vue."""
    cle = cle_courante()
    return cle if cle[0] == cle_avant[0] else cle_avant


def memorise_a_part(emplacement: str, calcul, en_fond: bool = False):
    """Même mémoire courte, clé = `cle_courante()`."""
    return memorise(cle_courante(), calcul, emplacement, en_fond=en_fond,
                    cle_apres=_cle_apres_calcul)


# ------------------------------------------------------------------ récap d'une session

#  Version du calcul `_recap_lu` (récap + rapport rendu) : la changer dès que la forme du récap
#  ou le rendu du rapport change, sinon les empreintes persistées serviraient l'ancienne forme.
_RECAPS = empreintes.Empreintes("recaps_sessions.json", version=3)


_CHAMPS_STRUCTURES = {"taches_terminees": list, "taches_restantes": list, "recap": dict,
                      "related_files": list}


def _decoder(valeur, attendu: type):
    """Un paramètre liste / objet arrive en TEXTE JSON par le protocole XML (l'exécution le
    décode, la session garde le brut) : relu tel quel, une liste était itérée caractère par
    caractère et un `recap` « {} » faisait planter tout /api/lignes."""
    if isinstance(valeur, str):
        try:
            valeur = json.loads(valeur)
        except ValueError:
            return attendu() if attendu is dict else ([valeur] if valeur.strip() else [])
    return valeur if isinstance(valeur, attendu) else attendu()


def _final_answer_input(messages: list[dict]) -> dict:
    """L'`input` du DERNIER appel FinalAnswer d'une session ({} si aucun), champs structurés
    décodés."""
    for message in reversed(messages or []):
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if call.get("name") == "FinalAnswer" and isinstance(call.get("input"), dict):
                fa = dict(call["input"])
                for champ, attendu in _CHAMPS_STRUCTURES.items():
                    if champ in fa:
                        fa[champ] = _decoder(fa[champ], attendu)
                return fa
    return {}


def _texte_item(item) -> str:
    if isinstance(item, dict):
        return str(item.get("titre") or item.get("texte") or item.get("text") or "").strip()
    return str(item or "").strip()


def _restantes(fa: dict) -> tuple[list[str], list[str]]:
    """`taches_restantes` séparées en (reste à faire, à décider)."""
    reste, a_decider = [], []
    for item in fa.get("taches_restantes") or []:
        texte = _texte_item(item)
        if texte:
            (a_decider if isinstance(item, dict) and item.get("decision") else reste).append(texte)
    return reste, a_decider


def _points_ouverts(recap: dict, deja: list[str]) -> list[str]:
    ajouts: list[str] = []
    for point in recap.get("points_ouverts") or []:
        texte = _texte_item(point)
        if texte and texte not in deja and texte not in ajouts:
            ajouts.append(texte)
    return ajouts


def _nb_fichiers(data: dict, recap: dict, fa: dict):
    changements = recap.get("changes") or (fa.get("recap") or {}).get("changes") or []
    if changements:
        return len(changements)
    if isinstance(data.get("file_snapshots"), dict):
        return len(data["file_snapshots"]) or None
    return None


def _resume(reponse: str) -> str:
    return reponse[:RESUME_MAX] + ("…" if len(reponse) > RESUME_MAX else "")


def _corps_des_restantes(fa: dict) -> dict[str, str]:
    """`{libellé normalisé: brief}` des points laissés : « Créer la tâche » en fait le brief."""
    from .suites_cloture import cle
    return {cle(_texte_item(item)): str(item.get("corps") or "").strip()
            for item in fa.get("taches_restantes") or []
            if isinstance(item, dict) and _texte_item(item) and item.get("corps")}


def recap_de_session(data: dict) -> dict:
    """Résumé structuré d'une session finie : fait / reste / à décider / réponse / fichiers.

    Lu dans l'appel FinalAnswer (champs obligatoires `taches_terminees`, `taches_restantes`)
    et, à défaut, dans le `recap` persisté par la porte de clôture. Fonction PURE."""
    fa = _final_answer_input(data.get("messages") or [])
    recap = data.get("recap") if isinstance(data.get("recap"), dict) else {}
    reste, a_decider = _restantes(fa)
    a_decider += _points_ouverts(recap, a_decider)
    reponse = str(fa.get("answer") or data.get("final_answer") or "").strip()
    return {
        "fait": [t for t in (_texte_item(i) for i in fa.get("taches_terminees") or []) if t],
        "reste": reste,
        "a_decider": a_decider,
        "corps": _corps_des_restantes(fa),
        "resume": _resume(reponse),
        "reponse": reponse,
        "fichiers": _nb_fichiers(data, recap, fa),
        "related_files": related_files_de_session(data, fa),
    }


def related_files_de_session(data: dict, fa: dict | None = None) -> list[dict]:
    """« Fichiers livrés » déclarés : l'appel FinalAnswer d'abord, le champ persisté sinon.
    Sans existence (fonction pure, mise en cache) : l'appelant ajoute `exists` à l'affichage."""
    from bouzecode.backend.agent.related_files import normaliser_related_files
    if fa is None:
        fa = _final_answer_input(data.get("messages") or [])
    return normaliser_related_files(fa.get("related_files") or data.get("related_files"))


def _recap_lu(session: Path) -> dict | None:
    """Récap de la session et son rapport rendu en HTML (le rendu markdown de ~200 rapports
    coûtait 0,3 s à chaque recalcul de l'écran). None pour une session illisible (en cours
    d'écriture) : rien n'est retenu."""
    from ..sessions import store
    from .bureau_lignes import _rapport_html
    data = store.load_session_json(session)
    if data is None:
        return None
    recap = recap_de_session(data)
    return {**recap, "rapport_html": _rapport_html(recap["reponse"])}


def recap_d_agent(agent) -> dict:
    """Récap retenu par version de la session (`empreintes`, persisté) : relire une session de
    plusieurs Mo à chaque rafraîchissement du Bureau — ou à chaque redémarrage du serveur —
    coûterait plus que tout le reste de la vue."""
    chemin = str(getattr(agent, "session_path", "") or "")
    if not chemin:
        return {}
    return _RECAPS.lire(Path(chemin), lambda: _recap_lu(Path(chemin))) or {}


# ------------------------------------------------------------------------- contexte


class Contexte:
    """Les index lus UNE fois pour tout l'écran."""

    def __init__(self):
        from bouzecode.web_v2.runtime.runner import agent_registre

        from . import _persistence, brouillons_integres, classement
        from . import micros as micros_service
        self.tickets: dict[str, tuple[str, dict]] = {}
        for slug, ticket in _persistence.all_tickets():
            ident = str(ticket.get("id") or "")
            if ident:
                self.tickets[ident] = (str(slug), ticket)
        self.agents = {a.agent_id: a for a in agent_registre.list_agents() if getattr(a, "agent_id", "")}
        self.retours = micros_service.tous_les_retours()
        self.retours_du_ticket: dict[str, list[dict]] = {}
        for retours in self.retours.values():
            for retour in retours:
                if retour.get("ticket_id"):
                    self.retours_du_ticket.setdefault(retour["ticket_id"], []).append(retour)
        self.archivages = brouillons_integres.archivages()
        self.classements = classement.historiques()
        self.reouvertures = micros_service.reouvertures()
        self._statuts: dict[str, dict] = {}
        self._sources: dict[str, str] | None = None

    def ticket_source(self, micro_id: str) -> str:
        """Ticket dont la clôture a créé (ou repris) la micro `micro_id` ; "" sinon."""
        if self._sources is None:
            from . import suites_cloture
            self._sources = {}
            for ticket_id, suites in suites_cloture.index().items():
                for suite in suites.values():
                    if suite.get("lien") == "creee" or suite["micro_id"] not in self._sources:
                        self._sources[suite["micro_id"]] = ticket_id
        return self._sources.get(micro_id, "")

    def statut(self, agent) -> dict:
        from ..sessions import store
        if agent.agent_id not in self._statuts:
            self._statuts[agent.agent_id] = store.agent_status(agent) or {}
        return self._statuts[agent.agent_id]


# ------------------------------------------------------------------------- passage

#  Un passage se lit sur `ticket.state` : `taches_passage` (ré-export de l'API historique).
from .taches_passage import passage  # noqa: E402,F401


def _statut_lancee(dernier: dict | None) -> tuple[str, str]:
    if dernier is None:
        return "en_echec", "Lancée sans agent : aucun ticket n'est relié à cette tâche"
    if dernier["etat"] in ("crashed", "launch_failed", "missing"):
        return "en_echec", dernier["raison_echec"] or "L'agent s'est arrêté sans finir"
    return "a_relire", ""


def _statut_ui(ligne: dict, passages: list[dict], rouverte: bool = False) -> tuple[str, str]:
    """`(statut_ui, raison_echec)` — SPEC §1.2. `passages` du plus récent au plus ancien.

    Une tâche restée `brouillon` alors qu'un agent y a travaillé (tâche v1 migrée avec ses
    tickets, origine `cloture_agent`) se lit comme lancée : « Brouillon » dans « À lancer »
    avec un bouton Lancer mentait sur un passage livré ou planté. Seule une tâche ROUVERTE
    (`rouverte`, retour voulu en brouillon) reste un brouillon malgré ses vieux passages."""
    etat = str(ligne.get("etat") or "")
    dernier = passages[0] if passages else None
    if etat in ("faite", "abandonnee"):
        return etat, ""
    if any(p["etat"] in lexique.ETATS_ATTENTE for p in passages):
        return "a_repondre", ""
    if dernier is not None and dernier["etat"] in lexique.ETATS_ACTIFS:
        return "en_cours", ""
    if etat == "lancee" or (etat == "brouillon" and dernier is not None and not rouverte):
        return _statut_lancee(dernier)
    return ("a_decider" if ligne.get("decision") else "brouillon"), ""


def _question_de_la_ligne(ligne: dict, passages: list[dict]) -> dict:
    """La question du passage qui attend, au format de la ligne (`question`, `options`…)."""
    attente = next(p for p in passages if p["etat"] in lexique.ETATS_ATTENTE)
    question = dict(ligne.get("question") or {})
    question.update({"question": attente["question"]["texte"],
                     "options": attente["question"]["options"],
                     "allow_freetext": attente["question"]["allow_freetext"],
                     "agent_id": attente["agent_id"], "ticket_id": attente["ticket_id"]})
    return question


def _passages(ligne: dict, ctx: Contexte) -> list[dict]:
    """Les passages de la tâche, du plus récent au plus ancien (numérotés dans l'ordre)."""
    liens = list(ligne.get("tickets") or [])
    passages = [passage(ctx, str(l.get("slug") or ""), str(l["ticket_id"]), str(l.get("at") or ""),
                        numero)
                for numero, l in enumerate(liens, start=1) if l.get("ticket_id")]
    passages.reverse()
    return passages


def enrichir(ligne: dict, ctx: Contexte) -> dict:
    """Ajoute à une ligne de `bureau_lignes` les champs de la SPEC v3 (contrat §2.1)."""
    ligne["retours"] = list(ctx.retours.get(str(ligne.get("id") or ""), []))
    passages = ligne["passages"] = _passages(ligne, ctx)
    statut, raison = _statut_ui(ligne, passages,
                                rouverte=str(ligne.get("id") or "") in ctx.reouvertures)
    dernier = passages[0] if passages else {}
    ligne.update(statut_ui=statut, libelle_statut=lexique.libelle_statut(statut),
                 segment=lexique.segment(statut), raison_echec=raison,
                 activite=dernier.get("activite", "") if statut == "en_cours" else "",
                 joignable=bool(dernier.get("joignable")),
                 agent_actif=dernier.get("etat") in lexique.ETATS_ACTIFS,
                 projet_defaut=projet_defaut(ligne))
    motif = lexique.motif_attente(statut, passages)
    #  Une tâche archivée automatiquement (brouillon de fusion d'une branche intégrée) le dit.
    auto = ctx.archivages.get(str(ligne.get("id") or "")) \
        if statut in ("faite", "abandonnee") else None
    ligne.update(motif=motif, categorie=lexique.categorie(motif), archive_auto=auto,
                 **_classement(ctx, str(ligne.get("id") or ""), statut))
    if statut == "a_repondre":
        ligne["question"] = _question_de_la_ligne(ligne, passages)
    if statut == "a_decider":
        source = decision_source(str(ligne.get("id") or ""), ctx)
        if source:
            ligne["decision_source"] = source
    return ligne


def decision_source(micro_id: str, ctx: Contexte) -> dict:
    """La FinalAnswer de l'agent dont la clôture a laissé ce choix (`micro_suites`).

    `{}` si la tâche n'est pas née d'une clôture (créée à la main) ou si le ticket source
    a disparu : l'écran garde alors son texte générique."""
    ticket_id = ctx.ticket_source(micro_id)
    if not ticket_id:
        return {}
    slug, ticket = ctx.tickets.get(ticket_id, ("", {}))
    source = {"ticket_id": ticket_id, "slug": slug,
              "titre": str(ticket.get("title") or ticket.get("titre") or ""),
              "agent_id": "", "resume": "", "rapport_html": ""}
    travail = next((r for r in ticket.get("runs") or [] if isinstance(r, dict)
                    and r.get("kind") in ("work", "merge_fix")), None)
    agent = None
    if travail is not None:
        source["agent_id"] = str(travail.get("agent_id") or "")
        agent = ctx.agents.get(source["agent_id"])
    if agent is not None:
        try:
            recap = recap_d_agent(agent)
        except Exception:  # noqa: BLE001 — une session illisible ne casse pas le Bureau
            recap = {}
        source["resume"] = str(recap.get("resume") or "")
        source["rapport_html"] = str(recap.get("rapport_html") or "")
    return source


def _classement(ctx: Contexte, micro_id: str, statut: str) -> dict:
    """Pourquoi une tâche classée l'a été (fait ailleurs, doublon, caduque) + l'historique."""
    historique = ctx.classements.get(micro_id, [])
    dernier = historique[-1] if historique else None
    actif = dernier if dernier and not dernier["rouvert_at"] and statut in ("faite", "abandonnee") \
        else None
    return {"classement": actif, "classements": historique}


def projet_defaut(micro: dict) -> str:
    """Le dépôt qui servira au lancement : celui de la tâche, sinon le 1er du chantier."""
    propre = str(micro.get("projet_slug") or "").strip()
    if propre:
        return propre
    macro = micro.get("macro") or {}
    projets = list(macro.get("projets") or [])
    return str(projets[0]) if projets else ""


def contexte() -> Contexte:
    return Contexte()


def compte_ui(lignes: list[dict]) -> dict:
    compte = {statut: 0 for statut in ORDRE_STATUT}
    segments = {"a_moi": 0, "en_cours": 0, "a_lancer": 0, "archivees": 0}
    for ligne in lignes:
        compte[ligne["statut_ui"]] = compte.get(ligne["statut_ui"], 0) + 1
        segments[ligne["segment"]] = segments.get(ligne["segment"], 0) + 1
    return {**compte, "segments": segments}


def rang(ligne: dict) -> tuple:
    return (ORDRE_STATUT.get(ligne.get("statut_ui", ""), 9), str(ligne.get("created_at") or ""))
