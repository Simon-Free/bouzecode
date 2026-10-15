"""Lecture UNIFIÉE du Bureau : une seule liste de lignes, rangée par CHANTIER.

Pourquoi ce module existe (brief utilisateur du 2026-09-07) : « je veux merger à faire,
à décider, la todo, c'est la même chose... Il y a juste des trucs archivés, en cours, et
inactifs parce que à faire/décider/etc. » L'écran empilait 4 listes pour le MÊME objet
(« À faire », « À décider », « TO-DO », « Brouillons »), chacune avec son vocabulaire.

Deux axes, et deux seulement :

* **Axe 1 — le regroupement, c'est le chantier** (la macro-tâche du §8.1 de la spec).
  Ce n'est PAS un projet : *Refaire DEMODB sur databricks* traverse `demo_ingestion`,
  `demo_monorepo`, `demo_application`. Le dépôt (`projet_slug`) reste une propriété
  de LANCEMENT d'une ligne, jamais un regroupement d'écran.
* **Axe 2 — le statut, à trois valeurs**, DÉDUIT et jamais saisi : `en_cours` (un ticket
  tourne), `inactif` (+ la RAISON : `a_faire`, `a_decider`, `figee`), `archive`.
  « À faire » et « À décider » cessent d'être des sections : ce sont des raisons.

Ce module ne fait AUCUN accès SQL propre : il compose `micros.list_macros()` et
`micros.list_micros()`. C'est ce qui le rend testable et sans risque pour les données.
Il n'a pas de paramètre de fenêtre temporelle (2j/7j/tout) : une ligne persistante ne
doit pas s'évaporer parce qu'elle a huit jours — c'est ce qui rendait la TO-DO invisible
(0 puce affichée alors que la base en portait).
"""

from __future__ import annotations

from datetime import datetime

from bouzecode.web_v2.services.horodatage import lire_instant, maintenant as horloge

from . import micros as micros_service

#  Une ligne LANCÉE dont le dernier ticket ne donne plus signe de vie est « figée ».
#  Le board des tâches utilise 30 minutes pour son voyant « Figé » ; à l'échelle d'un
#  chantier ce seuil est trop court (un agent peut travailler une heure sans relier de
#  nouveau ticket). 24 h : au-delà, un travail lancé qui n'a rien produit doit sauter aux
#  yeux au lieu de se faire passer pour « en cours ».
FIGEE_APRES_S = 24 * 3600

#  Les états persistés d'une micro-tâche (§8.2) qui signifient « c'est fini ».
ETATS_ARCHIVES = ("faite", "abandonnee")

STATUTS = ("en_cours", "inactif", "archive")
#  `a_relire` compte comme les autres : sans elle, un chantier dont l'agent vient de finir
#  n'affichait AUCUN compteur (le travail fini devenait invisible dans le résumé du chantier).
#  `a_repondre` : un agent de la ligne pose une question à l'humain. C'est la raison la
#  plus actionnable de toutes — elle ne coûte qu'une réponse — et elle était invisible.
RAISONS = ("a_faire", "a_decider", "a_repondre", "figee", "a_relire")

TITRE_NON_RATTACHEES = "Sans chantier"


def _instant(valeur: object) -> datetime | None:
    """Instant UTC conscient d'une date du store (`horodatage.lire_instant`), ou None."""
    return lire_instant(valeur)


def _dernier_signe(ligne: dict) -> datetime | None:
    """Date du dernier ticket relié : le PLUS RÉCENT des instants lisibles.

    Pas le dernier de la liste : `list_micros` trie par `at` en CHAÎNE, et le store mêle des
    dates locales naïves (héritées) et des dates UTC — l'ordre lexical n'est pas chronologique."""
    instants = [i for i in (_instant(t.get("at")) for t in ligne.get("tickets") or []) if i]
    return max(instants) if instants else None


#  Les SEULS statuts de ticket (`etat_ticket.statut`, projection de `ticket.state`) qui veulent
#  dire « ça tourne ». Tous les autres décrivent un travail qui n'avance PLUS et attend un humain.
#  LE statut de ticket qui veut dire « un humain doit répondre avant que ça reprenne ».
STATUT_ATTEND_REPONSE = "attend réponse"

STATUTS_ACTIFS = ("en cours", "préparation", "intégration", STATUT_ATTEND_REPONSE,
                  "en attente des enfants")


#  Un ticket sans le moindre run : il est « à faire ». Ce statut ne prouve RIEN sur la ligne —
#  ni qu'elle travaille, ni qu'elle a fini : le compter comme « fini » aurait fabriqué « fini, à
#  relire » sur un ticket que personne n'a jamais lancé.
STATUTS_JAMAIS_DEMARRES = ("à faire",)


def _tickets_encore_actifs(ligne: dict) -> bool | None:
    """Les tickets reliés tournent-ils encore ? `None` quand on n'en sait rien (aucun ticket
    relié, ou aucun statut joint) : l'appelant retombe alors sur la règle de la date."""
    statuts = [str(ticket.get("statut") or "") for ticket in ligne.get("tickets") or []]
    connus = [statut for statut in statuts if statut and statut not in STATUTS_JAMAIS_DEMARRES]
    if not connus:
        return None
    return any(statut in STATUTS_ACTIFS for statut in connus)


def _tickets_situes(vue: dict, statuts: dict | None) -> list[dict]:
    """Les tickets de la vue, chacun porteur de son état (`state`, `statut`, libellé) quand on
    le connaît. Une copie, jamais la liste d'origine (la vue vient du service micros)."""
    tickets = []
    for ticket in vue.get("tickets") or []:
        situe = dict(ticket)
        cle = (str(ticket.get("slug") or ""), str(ticket.get("ticket_id") or ""))
        projection = (statuts or {}).get(cle)
        if projection:
            situe.update(statut=projection["status"], state=projection["state"],
                         state_reason=projection["state_reason"],
                         status_ui=projection["status_ui"],
                         libelle_statut=projection["libelle_statut"])
        tickets.append(situe)
    return tickets


def _statuts_des_tickets(tickets: list | None = None) -> dict[tuple[str, str], dict]:
    """Index `(slug, ticket_id) -> projection de l'état` (`etat_ticket.vue`) pour TOUS les
    tickets du store, en UNE requête (`all_tickets()`). Aucun agent n'est relu : l'état est
    persisté (`ticket.state`)."""
    from bouzecode.web_v2.services.work import _persistence
    from .etat_ticket import vue
    if tickets is None:
        tickets = _persistence.all_tickets()
    return {(str(slug), str(ticket["id"])): vue(ticket)
            for slug, ticket in tickets if ticket.get("id")}


def un_ticket_tourne_encore(micro: dict) -> bool:
    """Un agent travaille-t-il ENCORE sur cette ligne ? (refus de relancement de
    `api_micro_lancer`, contre le CLONAGE d'un travail en cours). Lu sur `ticket.state` : un
    lancement en vol (`provisioning`) compte. Rapprochement par `ticket_id` SEUL : le slug
    écrit dans la ligne n'est pas forcément celui du store, et un faux négatif ici clonerait."""
    from .fsm import etats
    identifiants = {str((lien or {}).get("ticket_id") or "")
                    for lien in (micro.get("tickets") or []) if isinstance(lien, dict)}
    identifiants.discard("")
    if not identifiants:
        return False
    actifs = {ident for (_slug, ident), projection in _statuts_des_tickets().items()
              if projection["state"] in etats.ACTIFS}
    return bool(identifiants & actifs)


def _ticket_qui_attend(ligne: dict) -> dict | None:
    """Le premier ticket relié dont l'agent attend une réponse humaine, sinon `None`.

    On lit le statut DÉJÀ dérivé par `_statuts_des_tickets` : aucune relecture d'agent ici,
    la fonction reste pure et testable sans base.
    """
    for ticket in ligne.get("tickets") or []:
        if str(ticket.get("statut") or "") == STATUT_ATTEND_REPONSE:
            return ticket
    return None


def statut_de(ligne: dict, maintenant: datetime | None = None) -> tuple[str, str]:
    """Rend `(statut, raison)` pour une ligne. Fonction PURE, testable sans base.

    La raison n'est renseignée que pour `inactif` et `archive` : un `en_cours` n'a pas
    de raison d'être inactif, et forcer un mot vide plutôt qu'une chaîne vide obligerait
    l'écran à filtrer un cas de plus.
    """
    maintenant = lire_instant(maintenant) or horloge()
    etat = str(ligne.get("etat") or "")
    if etat in ETATS_ARCHIVES:
        return "archive", etat
    if etat == "lancee":
        #  Une question posée à l'humain PRIME sur tout le reste. Signalé le 22/09 : la
        #  conversation remonte une question, la ligne continuait d'afficher « en cours »,
        #  indiscernable d'un agent qui travaille — donc personne ne répondait. Ce n'est
        #  ni « ça tourne », ni « figée » (une question de deux jours reste une question),
        #  ni « à relire » (rien n'est fini). Le TICKET le savait déjà (« attend réponse »,
        #  cf. `_status.derive_status`) : on cesse simplement de l'aplatir sur la ligne.
        if _ticket_qui_attend(ligne) is not None:
            return "inactif", "a_repondre"
        signe = _dernier_signe(ligne)
        if signe is None:
            #  Lancée sans aucun ticket relié : ce n'est pas « ça tourne », c'est un
            #  lancement qui n'a rien produit. Le dire plutôt que le maquiller.
            return "inactif", "figee"
        #  Le statut RÉEL des tickets prime sur la date : un travail dont l'agent a fini
        #  n'est pas « ça tourne », même s'il a signé il y a dix minutes. C'était le bug
        #  du 08/09 — une conversation terminée s'affichait « en cours » pendant 24 h,
        #  puis « figée », faute d'avoir jamais consulté l'état des tickets reliés. On ne
        #  clôt PAS la ligne pour autant : marquer « faite » reste une réponse humaine.
        if _tickets_encore_actifs(ligne) is False:
            return "inactif", "a_relire"
        if (maintenant - signe).total_seconds() > FIGEE_APRES_S:
            return "inactif", "figee"
        return "en_cours", ""
    #  Reste `brouillon` et `prete` : dans les deux cas la ligne attend quelque chose.
    #  Ce qu'elle attend est un ARBITRAGE humain quand elle est marquée `decision`,
    #  et du TRAVAIL sinon. C'est toute la différence entre les anciennes sections
    #  « À décider » et « À faire », désormais réduites à une raison d'inactivité.
    if ligne.get("decision"):
        return "inactif", "a_decider"
    return "inactif", "a_faire"


def _rapport_html(texte: str) -> str:
    """Rend le rapport de l'agent en HTML, parce qu'un rapport EST du markdown.

    Signalé le 08/09 sur /bureau : le rapport s'affichait tel quel, avec ses `##`, ses
    `- [x]` et ses `**gras**` en clair — soit exactement la forme que le modèle produit,
    et la moins lisible à l'écran. On réutilise le renderer DÉJÀ testé du projet plutôt
    que de réintroduire un mini-convertisseur JS (celui de `bureau.js` a été supprimé
    exprès le 08/09). `_md` applique `html.escape` sur CHACUN de ses chemins (texte,
    titres, cellules de table, blocs de code) : le HTML qu'un agent écrirait dans son
    rapport ressort neutralisé, ce qui est la condition sine qua non d'un innerHTML côté
    écran.

    Import LOCAL et HORS `try` : le Bureau ne doit pas charger le runtime de rendu quand
    personne ne le regarde, et un chemin d'import faux doit CRIER (le 08/09, un
    `bouzecode.runtime` inexistant était avalé par un `except` large et le rapport
    disparaissait sans un mot).
    """
    if not texte:
        return ""
    from bouzecode.web_v2.runtime.html_renderer.markdown import _md
    return _md(texte)


def _questions_par_ticket() -> dict[tuple[str, str], dict]:
    """`{(project_slug, ticket_id): question}` pour tous les agents bloqués sur un humain.

    Même forme de clé que `_statuts_des_tickets` : c'est ce qui permet de joindre la
    question à la ligne sans relire un seul agent de plus. Le travail (lecture du
    `.pending.json`, résolution du projet depuis le cwd) est déjà écrit et testé dans
    `awaiting.agents_awaiting_answer()` — on ne le réimplémente pas ici.

    Un parc d'agents illisible ne doit PAS faire tomber tout l'écran Bureau : on rend un
    index vide, la ligne gardera sa raison `a_repondre` sans le texte de la question.
    """
    from . import awaiting
    try:
        rows = awaiting.agents_awaiting_answer()
    except Exception:  # noqa: BLE001 — l'écran passe avant l'exhaustivité
        return {}
    return _index_questions(rows)


def _index_questions(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Indexe les questions par TOUTES les clés plausibles. Fonction PURE.

    MESURÉ le 22/09 sur le parc réel : `project_slug` est VIDE pour un agent de ticket,
    parce que `projects.project_for_cwd` ne reconnaît pas son cwd — un agent tourne dans
    `~/.bouzecode/worktrees/<projet>/<nom>`, pas dans le dossier du projet enregistré.
    La ligne du Bureau, elle, porte le slug du TICKET (`demo`). N'indexer que sur
    `(project_slug, ticket_id)` ratait donc 100 % des jointures : l'écran affichait bien
    « on me demande une réponse » mais JAMAIS le texte de la question.

    On pose donc toutes les clés, la plus fiable d'abord (`ticket_slug` vient de l'agent
    lui-même), plus un repli `("", ticket_id)` : un ticket_id est unique dans le parc, il
    suffit à retrouver la question quand aucun slug ne concorde. `setdefault` garantit que
    la première (la plus fiable) gagne si deux agents visent le même ticket.
    """
    index: dict[tuple[str, str], dict] = {}
    for row in rows:
        ticket_id = str(row.get("ticket_id") or "")
        if not ticket_id:
            continue  # question d'un agent hors ticket : rien à rattacher à une ligne
        for slug in (str(row.get("ticket_slug") or ""),
                     str(row.get("project_slug") or ""), ""):
            index.setdefault((slug, ticket_id), row)
    return index


def _ligne(vue: dict, maintenant: datetime,
           statuts: dict[tuple[str, str], dict] | None = None,
           questions: dict[tuple[str, str], dict] | None = None,
           ctx=None) -> dict:
    """Enrichit la vue rendue par le service micros, sans lui retirer une seule clé.

    L'écran actuel lit `texte` et `prompt` : les supprimer casserait `micros.js` sans
    rien apporter. On AJOUTE `statut`, `raison` et `dernier_signe`.

    `statuts` est l'index rendu par `_statuts_des_tickets`. Les tickets sont situés AVANT
    l'appel à `statut_de` — c'est tout l'objet du correctif : sans leur statut, la ligne
    n'était jugée que sur la DATE du dernier ticket, et une conversation terminée
    s'annonçait « ça tourne » pendant 24 h.
    """
    enrichie = dict(vue)
    enrichie["tickets"] = _tickets_situes(vue, statuts)
    statut, raison = statut_de(enrichie, maintenant)
    enrichie["statut"] = statut
    enrichie["raison"] = raison
    #  Une ligne qui attend une réponse doit dire LAQUELLE.
    #  Afficher « on te demande quelque chose » sans la question obligeait à retrouver la
    #  conversation à la main — le trajet signalé comme cassé le 22/09.
    if raison == "a_repondre":
        ticket_attendant = _ticket_qui_attend(enrichie) or {}
        cle = (str(ticket_attendant.get("slug") or ""),
               str(ticket_attendant.get("ticket_id") or ""))
        #  Repli par ticket_id seul : le slug du ticket et celui déduit du cwd de l'agent
        #  ne concordent pas toujours (cf. `_index_questions`), et une question retrouvée
        #  vaut mieux qu'une étiquette muette.
        question = (questions or {}).get(cle) or (questions or {}).get(("", cle[1]))
        if question:
            enrichie["question"] = {**question, "slug": cle[0], "ticket_id": cle[1]}
    signe = _dernier_signe(vue)
    enrichie["dernier_signe"] = signe.isoformat(timespec="seconds") if signe else ""
    #  Le nombre de notes se lit sur la ligne repliée : c'est ce qui dit « il y a du
    #  brief là-dedans » sans avoir à déplier.
    enrichie["notes"] = len(vue.get("precisions") or [])
    #  Champs de la SPEC v3 (statut UI, passages, joignabilité…), cf. taches_vue.
    if ctx is not None:
        from . import taches_vue
        taches_vue.enrichir(enrichie, ctx)
    return enrichie


def _rang(ligne: dict) -> tuple:
    if "statut_ui" in ligne:
        from . import taches_vue
        return taches_vue.rang(ligne)
    return _rang_historique(ligne)


def _rang_historique(ligne: dict) -> tuple:
    """Ordre DANS un chantier : ce qui tourne d'abord, ce qui est archivé en dernier.

    À statut égal, les arbitrages passent devant le travail : une ligne qui attend une
    décision humaine bloque tout ce qui pourrait en découler.
    """
    poids_statut = {"en_cours": 0, "inactif": 1, "archive": 2}
    #  `a_relire` est explicitement en dernier des inactifs (même valeur que le défaut) :
    #  relire un travail fini attend moins qu'un arbitrage ou qu'un travail jamais commencé.
    poids_raison = {"figee": 0, "a_decider": 1, "a_faire": 2, "a_relire": 3}
    return (
        poids_statut.get(ligne["statut"], 3),
        poids_raison.get(ligne["raison"], 3),
        str(ligne.get("created_at") or ""),
    )


def _chantier(macro: dict, lignes: list[dict]) -> dict:
    return {
        "macro_id": macro["id"],
        "titre": macro.get("titre") or "",
        "corps": macro.get("corps") or "",
        "projets": list(macro.get("projets") or []),
        "etat": macro.get("etat") or "active",
        "lignes": sorted(lignes, key=_rang),
        "compte": _compte(lignes),
        **({"compte_ui": _compte_ui(lignes)} if all("statut_ui" in l for l in lignes) else {}),
    }


def _compte_ui(lignes: list[dict]) -> dict:
    from . import taches_vue
    return taches_vue.compte_ui(lignes)


def _compte(lignes: list[dict]) -> dict:
    compte = {statut: 0 for statut in STATUTS}
    for raison in RAISONS:
        compte[raison] = 0
    for ligne in lignes:
        compte[ligne["statut"]] = compte.get(ligne["statut"], 0) + 1
        if ligne["raison"] in compte:
            compte[ligne["raison"]] += 1
    return compte


def _suivre_transmissions() -> None:
    """Une précision transmise et pas encore lue : sa lecture se constate MAINTENANT (file de
    l'agent), pas au prochain tick du watchdog — la carte dit « lue » dès que c'est vrai."""
    from . import file_messages, micros as micros_mod
    for agent_id in micros_mod.agents_a_suivre():
        file_messages.lister(agent_id)


#  --------------------------------------------------- liste légère / détail à la demande
#  Mesuré sur les vraies données (475 lignes) : le payload complet fait 2504 Ko, dont 1688 Ko
#  de `passages` (1302 Ko de `rapport_html` + 318 Ko de `recap`). Or le Bureau ne lit ces
#  passages QUE lorsqu'une tâche est DÉPLIÉE, et son poller retélécharge la liste toutes les
#  5 à 15 s. La liste sert donc ce que l'état REPLIÉ affiche ; le reste est servi ligne par
#  ligne par `GET /api/lignes/<id>` (routes/work/micros/) au moment du dépli.
#  `corps` (le brief) reste dans la liste : la recherche du Bureau (`bureau/filtre.js`,
#  `correspond`) cherche dans le titre ET le brief de CHAQUE tâche, repliée ou non — sans lui,
#  une tâche repliée ne se retrouvait plus par un mot de son brief. ~92 Ko sur 475 lignes.
CHAMPS_DETAIL = ("prompt", "tickets", "texte", "transitions", "macro", "notes",
                 "retours", "rapport", "rapport_html", "classements", "categorie", "lancable")
#  Ce que l'état replié lit d'un passage : l'agent en cours et son intégrabilité (bureau/
#  tache.js), jamais son récap ni son rapport.
CHAMPS_PASSAGE_LISTE = ("numero", "ticket_id", "agent_id", "etat", "libelle_etat",
                        "integre", "integrable", "question", "ticket_state",
                        "ticket_state_reason", "ticket_status_ui", "libelle_ticket")


def _ligne_legere(ligne: dict) -> dict:
    leger = {cle: valeur for cle, valeur in ligne.items() if cle not in CHAMPS_DETAIL}
    passages = ligne.get("passages") or []
    #  `passages_total` garde l'infobulle « N passages » EXACTE sans servir les N récaps.
    leger["passages"] = [{cle: p.get(cle) for cle in CHAMPS_PASSAGE_LISTE if cle in p}
                         for p in passages[:1]]
    leger["passages_total"] = len(passages)
    #  Marqueur lu par le front : une ligne LÉGÈRE se fait recoller son détail (cache du
    #  dépli) ; une ligne servie COMPLÈTE (`?detail=`) prime et rafraîchit ce cache.
    leger["_leger"] = True
    return leger


def projeter_liste(payload: dict, complets: set[str] | None = None) -> dict:
    """La même structure (`chantiers`, `non_rattachees`, `stats`), lignes allégées.

    `complets` : les ids servis ENTIERS malgré l'allègement — les tâches DÉPLIÉES à
    l'écran, dont les passages doivent rester vivants d'un poll au suivant.

    Copie : le payload mémorisé par `taches_vue` ne doit JAMAIS être mutilé, sinon l'appel
    suivant (inbox, détail d'une ligne) servirait une vue amputée."""
    gardees = {str(identifiant) for identifiant in (complets or ())}

    def projeter(ligne: dict) -> dict:
        return ligne if str(ligne.get("id")) in gardees else _ligne_legere(ligne)

    return {**payload,
            "chantiers": [{**chantier,
                           "lignes": [projeter(ligne)
                                      for ligne in (chantier.get("lignes") or [])]}
                          for chantier in payload.get("chantiers") or []],
            "non_rattachees": [projeter(ligne)
                               for ligne in payload.get("non_rattachees") or []]}


def ligne_complete(micro_id: str) -> dict | None:
    """Une ligne enrichie ENTIÈRE (brief, précisions, tickets, tous ses passages).

    Passe par la vue mémorisée : le détail d'une ligne ne reconstruit rien."""
    payload = collect_lignes()
    cible = str(micro_id)
    for ligne in payload.get("non_rattachees") or []:
        if str(ligne.get("id")) == cible:
            return ligne
    for chantier in payload.get("chantiers") or []:
        for ligne in chantier.get("lignes") or []:
            if str(ligne.get("id")) == cible:
                return ligne
    return None


def collect_lignes(maintenant: datetime | None = None, leger: bool = False,
                   complets: set[str] | None = None) -> dict:
    """Vue mémorisée quelques secondes (cf. `taches_vue.CACHE_TTL`), jetée à chaque écriture
    sur les chantiers et les tâches et à chaque changement d'état d'agent (`cle_courante`).
    `maintenant` explicite (tests) court-circuite la mémoire.

    `leger=True` rend la liste PROJETÉE (cf. `projeter_liste`) : c'est ce que sert
    `/api/lignes`. Sans argument, le payload reste COMPLET — l'inbox et le détail d'une
    ligne en dépendent."""
    from . import taches_vue
    _suivre_transmissions()
    if maintenant is not None:
        payload = _collect_lignes(maintenant)
    else:
        payload = taches_vue.memorise(("lignes", taches_vue.cle_courante()),
                                      lambda: _collect_lignes(None))
    return projeter_liste(payload, complets) if leger else payload


def _collect_lignes(maintenant: datetime | None = None) -> dict:
    """Rend `{chantiers, non_rattachees, stats}` : TOUTE la matière de l'écran Bureau.

    Un chantier sans aucune ligne est rendu quand même : c'est un chantier qu'on vient
    de créer, et le faire disparaître donnerait l'impression que la création a échoué.
    """
    maintenant = lire_instant(maintenant) or horloge()
    from . import taches_vue
    ctx = taches_vue.contexte()
    statuts = _statuts_des_tickets(tickets=[(slug, t) for slug, t in ctx.tickets.values()])
    #  Les questions en attente sont relevées UNE fois pour tout l'écran, comme les statuts :
    #  jamais un appel par ligne (`list_agents()` coûte 15 s à froid sur ~500 runs).
    questions = _questions_par_ticket()
    lignes = [_ligne(vue, maintenant, statuts, questions, ctx)
              for vue in micros_service.list_micros()]
    #  Chaque point « reste à faire / à décider » d'un récap désigne sa tâche : APRÈS
    #  l'enrichissement, pour que le statut de la tâche désignée soit connu.
    from . import suites_cloture
    suites_cloture.relier(lignes, suites_cloture.index())
    par_macro: dict[str, list[dict]] = {}
    non_rattachees: list[dict] = []
    for ligne in lignes:
        macro_id = str(ligne.get("macro_id") or "")
        if macro_id:
            par_macro.setdefault(macro_id, []).append(ligne)
        else:
            non_rattachees.append(ligne)
    chantiers = [_chantier(macro, par_macro.pop(macro["id"], []))
                 for macro in micros_service.list_macros()]
    #  Un `macro_id` qui ne correspond à aucune macro connue ne doit pas faire
    #  DISPARAÎTRE la ligne de l'écran : elle retombe dans les non rattachées.
    for orphelines in par_macro.values():
        non_rattachees.extend(orphelines)
    non_rattachees.sort(key=_rang)
    #  Récaps et clôtures lus pour cet écran : une seule écriture de leurs empreintes.
    from ..sessions import empreintes
    empreintes.ecrire_tout()
    return {
        "chantiers": chantiers,
        "non_rattachees": non_rattachees,
        "titre_non_rattachees": TITRE_NON_RATTACHEES,
        "stats": {
            "lignes": len(lignes),
            "chantiers": len(chantiers),
            **_compte(lignes),
            "non_rattachees": len(non_rattachees),
            "compte_ui": _compte_ui(lignes),
        },
    }
