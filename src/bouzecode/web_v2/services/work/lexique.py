# [desc] Lexique UNIQUE de l'écran : une table (LEXIQUE) pour les statuts de tâche, les états d'agent, les motifs d'attente et les statuts de ticket — mot, aide, ton, icône —, servie par /api/lexique et injectée dans chaque page (SPEC §1.1, §1.2). [/desc]
"""Le vocabulaire que l'écran affiche, décidé UNE fois côté serveur.

Avant ce module, chaque surface redérivait son libellé : la sidebar disait « chaud » ce que le
Bureau disait « fini, à relire », et « planté » ce que le panneau disait « terminé ». La SPEC v3
(§1.1, §1.2) fixe un lexique ; ce module le produit à partir des preuves déjà calculées ailleurs
(`store.agent_status`, `liveness.classify_agent`, phase de lancement). Fonctions PURES : aucune
I/O, testables sans parc d'agents.
"""
from __future__ import annotations

#  ---------------------------------------------------------------- LE lexique
#
#  UNE table, et une seule, pour tout mot d'état que l'utilisateur lit : badge d'une tâche
#  (Bureau), état d'un agent (page Agents), motif d'attente (« À traiter »), statut d'un ticket
#  (API). Chaque entrée : `mot` (le libellé court), `aide` (l'infobulle : ce que ça veut dire et
#  quoi faire), `ton` (info | warn | danger | ok | neutral → couleur de ds.css) et `icone` (forme
#  distincte : un état n'est jamais porté par la seule couleur).
#
#  Qui la lit : `libelle_etat` / `libelle_statut` / `libelle_ticket` (serveur : /api/lignes,
#  /api/agents/tree, /api/tickets…), `GET /api/lexique`, et chaque page — `base.html` l'injecte
#  (`<script id="bz-lexique">`) et `static/js/lib/states.js` / `bureau/attention.js` y prennent
#  leurs mots (leurs valeurs par défaut sont tenues ÉGALES à cette table par
#  `tests/test_lexique_unique.py`).
#
#  Règles de rédaction (retour de l'utilisateur, 2026-09-25 : « Brouillon », « Décision à
#  prendre », « En échec », « Planté », « Question » désignaient les mêmes situations sous des
#  mots différents selon l'écran) : un mot par situation, le même partout ; des mots d'action
#  (« À lancer », « À décider », « À vérifier ») plutôt que du jargon ; jamais de mot technique.
_ARRET = "L'agent s'est arrêté sans rendre de réponse finale : fais-le continuer, ou relance un agent neuf."
_QUESTION = "L'agent t'a posé une question et attend ta réponse pour continuer."
_LIVRAISON = "L'agent a rendu sa réponse finale : vérifie son travail, puis clos la tâche ou renvoie-la avec un retour."
_DECISION = "Un agent a fini en te laissant ce choix. Aucun agent n'attend : note ta décision, ou confie-la à un agent."

LEXIQUE: dict[str, dict[str, str]] = {
    #  Statuts d'une tâche du Bureau (`statut_ui`) — aussi cibles des statuts de ticket.
    "brouillon": {"mot": "À lancer", "aide": "Pas encore lancée : relis le brief, puis lance-la.",
                  "ton": "neutral", "icone": "○"},
    "a_decider": {"mot": "À décider", "aide": _DECISION, "ton": "warn", "icone": "◆"},
    "en_cours": {"mot": "En cours", "aide": "Un agent travaille sur cette tâche.", "ton": "info", "icone": "●"},
    "a_repondre": {"mot": "Attend ta réponse", "aide": _QUESTION, "ton": "warn", "icone": "?"},
    "a_relire": {"mot": "À vérifier", "aide": _LIVRAISON, "ton": "ok", "icone": "✓"},
    "en_echec": {"mot": "Arrêté sans finir", "aide": _ARRET, "ton": "danger", "icone": "!"},
    "faite": {"mot": "Faite", "aide": "Close : le travail est fait.", "ton": "ok", "icone": "✓"},
    "abandonnee": {"mot": "Abandonnée", "aide": "Close sans être faite.", "ton": "neutral", "icone": "–"},
    #  États d'un agent (`etat` des nœuds de /api/agents/tree).
    "preparing": {"mot": "Préparation…", "aide": "L'environnement de l'agent se prépare (copie du dépôt, dépendances, démarrage).",
                  "ton": "info", "icone": "◌"},
    "thinking": {"mot": "Le modèle lit ta demande…", "aide": "La première réponse est la plus lente : le modèle met ton contexte en mémoire.",
                 "ton": "info", "icone": "◌"},
    "running": {"mot": "En cours", "aide": "L'agent travaille.", "ton": "info", "icone": "●"},
    "orchestrating": {"mot": "Attend ses sous-agents", "aide": "L'agent a lancé des sous-agents et attend qu'ils finissent.",
                      "ton": "info", "icone": "●"},
    "awaiting_input": {"mot": "Attend ta réponse", "aide": _QUESTION, "ton": "warn", "icone": "?"},
    "awaiting_plan_validation": {"mot": "Plan à valider", "aide": "L'agent attend que tu valides son plan avant de continuer.",
                                 "ton": "warn", "icone": "?"},
    "crashed": {"mot": "Arrêté sans finir", "aide": _ARRET, "ton": "danger", "icone": "!"},
    "launch_failed": {"mot": "Lancement échoué", "aide": "L'agent n'a jamais démarré (dépôt, git, environnement, API) : corrige la cause, puis relance.",
                      "ton": "danger", "icone": "!"},
    "idle": {"mot": "Terminé", "aide": "L'agent a rendu sa réponse ; il peut encore recevoir un message sans redémarrer.",
             "ton": "ok", "icone": "✓"},
    "finished": {"mot": "Terminé", "aide": "L'agent a rendu sa réponse finale.", "ton": "ok", "icone": "✓"},
    "integre": {"mot": "Terminé — intégré", "aide": "L'agent a rendu sa réponse et son travail est intégré.",
                "ton": "ok", "icone": "✓"},
    "archived": {"mot": "Archivé", "aide": "Retiré de la liste ; restaurable.", "ton": "neutral", "icone": "▪"},
    "missing": {"mot": "Agent introuvable", "aide": "La fiche de l'agent est introuvable : relance un agent neuf.",
                "ton": "danger", "icone": "!"},
    #  États d'un ticket que rien d'autre ne dit (`ticket.state`, cf. `etat_ticket`).
    "bloque": {"mot": "Bloqué", "aide": "L'intégration ou la clôture est bloquée : ouvre l'agent pour voir pourquoi.",
               "ton": "danger", "icone": "!"},
    "integration": {"mot": "Intégration…", "aide": "La branche de l'agent est en train d'être fusionnée dans sa base.",
                    "ton": "info", "icone": "◌"},
    "conflit": {"mot": "Conflit à résoudre", "aide": "La fusion a buté sur un conflit : relance l'agent pour le résoudre, ou abandonne.",
                "ton": "danger", "icone": "!"},
    "conflit_resolu": {"mot": "Conflit résolu", "aide": "Le conflit est résolu dans le worktree : intègre à nouveau la branche.",
                       "ton": "warn", "icone": "◆"},
    #  Motifs d'attente (« À traiter » du Bureau) qui ne sont ni un statut ni un état.
    "arrete": {"mot": "Arrêté par toi", "aide": "Tu as arrêté l'agent : fais-le continuer, relance, ou abandonne la tâche.",
               "ton": "neutral", "icone": "■"},
}

#  Motif d'attente (`motif_attente`) → entrée du lexique : le badge d'une tâche qui t'attend dit
#  le MÊME mot que l'état de son agent sur la page Agents.
LEXIQUE_DU_MOTIF = {
    "question": "a_repondre", "plan": "awaiting_plan_validation", "point": "a_decider",
    "lancement": "launch_failed", "plante": "en_echec", "arrete": "arrete",
    "introuvable": "missing", "livraison": "a_relire",
}

#  Statut d'un ticket (`etat_ticket.statut`, mot historique projeté de `ticket.state`, conservé
#  tel quel dans `status` pour les scripts et les agents) → entrée du lexique (`status_ui`).
LEXIQUE_DU_TICKET = {
    "à faire": "brouillon", "en cours": "en_cours", "attend réponse": "a_repondre",
    "en attente des enfants": "orchestrating", "à relire": "a_relire",
    "décision": "a_decider", "terminé": "faite", "planté": "en_echec",
    "lancement échoué": "launch_failed", "préparation": "preparing",
    "merge bloqué": "bloque", "clôture bloquée": "bloque", "livraison non commitée": "bloque",
    "arrêté sans finir": "en_echec", "arrêté": "arrete", "agent introuvable": "missing",
    "intégration": "integration", "conflit": "conflit", "conflit résolu": "conflit_resolu",
    "abandonné": "abandonnee",
}

_ETATS_AGENT = ("preparing", "thinking", "running", "orchestrating", "awaiting_input",
                "awaiting_plan_validation", "crashed", "launch_failed", "idle", "finished",
                "archived", "missing")
LIBELLES_ETAT = {etat: LEXIQUE[etat]["mot"] for etat in _ETATS_AGENT}

#  États où un agent est encore « à l'œuvre » (il occupe sa tâche : pas de second lancement).
ETATS_ACTIFS = frozenset({"preparing", "thinking", "running", "orchestrating",
                          "awaiting_input", "awaiting_plan_validation"})
ETATS_ATTENTE = frozenset({"awaiting_input", "awaiting_plan_validation"})

LIBELLES_STATUT = {statut: LEXIQUE[statut]["mot"] for statut in (
    "brouillon", "a_decider", "en_cours", "a_repondre", "a_relire", "en_echec", "faite", "abandonnee")}

SEGMENT_DU_STATUT = {
    "a_repondre": "a_moi",
    "a_relire": "a_moi",
    "en_echec": "a_moi",
    "a_decider": "a_moi",
    "en_cours": "en_cours",
    "brouillon": "a_lancer",
    "faite": "archivees",
    "abandonnee": "archivees",
}


#  Ce que l'utilisateur doit FAIRE (SPEC §4.2) : chaque tâche ou point qui l'attend a un MOTIF,
#  et chaque motif relève d'UNE catégorie d'action — décider, débloquer à la main, reprendre un
#  agent arrêté avant la fin, vérifier un travail rendu. L'écran titre ses groupes par ces
#  catégories ; le motif donne le mot de la ligne et les gestes proposés.
CATEGORIE_DU_MOTIF = {
    "question": "decider",       # l'agent attend une réponse (AskUserQuestion)
    "plan": "decider",           # l'agent attend la validation de son plan
    "point": "decider",          # un agent a fini en laissant un choix (decision=true)
    "lancement": "debloquer",    # l'agent n'a jamais démarré : dépôt, git, venv, API
    "plante": "reprendre",       # arrêté sans réponse finale (erreur, process mort)
    "arrete": "reprendre",       # arrêté à la demande de l'utilisateur
    "introuvable": "reprendre",  # fiche d'agent ou ticket perdus
    "livraison": "verifier",     # réponse finale rendue
    "signalement": "verifier",   # un agent a signalé un problème (Signaler) et continue
    "signalement_bloquant": "debloquer",  # signalé « bloquant » : une partie attend l'humain
}

RAISON_ARRET_DEMANDE = "Arrêté à ta demande"
#  Arrêt demandé avant que l'agent ait démarré : enregistré comme un échec de lancement, mais ce
#  n'est pas une panne à corriger à la main.
ERREUR_ARRET_PREPARATION = "arrêté à ta demande pendant la préparation"


def _motif_echec(passages: list[dict]) -> str:
    dernier = passages[0] if passages else {}
    etat = dernier.get("etat")
    if etat == "launch_failed":
        return "arrete" if ERREUR_ARRET_PREPARATION in str(dernier.get("raison_echec") or "") else "lancement"
    if etat != "crashed":
        return "introuvable"
    return "arrete" if dernier.get("raison_echec") == RAISON_ARRET_DEMANDE else "plante"


def _motif_reponse(passages: list[dict]) -> str:
    attente = next((p for p in passages if p.get("etat") in ETATS_ATTENTE), {})
    return "plan" if attente.get("etat") == "awaiting_plan_validation" else "question"


_MOTIF_DU_STATUT = {"a_repondre": _motif_reponse, "a_relire": lambda _passages: "livraison",
                    "en_echec": _motif_echec, "a_decider": lambda _passages: "point"}


def motif_attente(statut: str, passages: list[dict]) -> str:
    """Motif d'attention d'une tâche (`""` si elle n'attend rien). `passages` : du plus récent
    au plus ancien, au format de `taches_vue.passage`."""
    regle = _MOTIF_DU_STATUT.get(statut)
    return regle(passages) if regle else ""


def categorie(motif: str) -> str:
    return CATEGORIE_DU_MOTIF.get(motif, "")


_PHASES = {"demarrage": "preparing", "attente_modele": "thinking"}


def _etat_de_vie(state: str, liveness: str, phase: str) -> str:
    """La mort prouvée, puis le démarrage (lancement, phases), puis le travail en cours."""
    if liveness == "missing":
        return "missing"
    if state == "provisioning":
        return "preparing"
    if state == "launch_failed":
        return "launch_failed"
    if liveness == "crashed":
        return "crashed"
    if phase in _PHASES:
        return _PHASES[phase]
    return {"starting": "preparing", "running": "running"}.get(state, "")


def _etat_de_fin(state: str, enfants_vivants: bool) -> str:
    if state in ("finished", "idle", "cli") and enfants_vivants:
        return "orchestrating"
    return state if state in ("idle", "archived") else "finished"


def etat_agent(state: str, liveness: str = "", phase: str = "",
               enfants_vivants: bool = False) -> str:
    """Clé du lexique pour un agent, à partir des preuves déjà servies ailleurs.

    Ordre de priorité : une question prime sur tout (c'est l'information la plus actionnable),
    puis la mort prouvée, puis les phases de démarrage, puis l'état ordinaire."""
    state = str(state or "")
    if state in ETATS_ATTENTE:
        return state
    return _etat_de_vie(state, liveness, phase) or _etat_de_fin(state, enfants_vivants)


def libelle_etat(etat: str) -> str:
    return LIBELLES_ETAT.get(etat, etat or "")


def libelle_statut(statut: str) -> str:
    return LIBELLES_STATUT.get(statut, statut or "")


def statut_ticket(status: str) -> str:
    """Clé du lexique d'un statut de ticket (`derive_status`) ; `""` s'il est inconnu."""
    return LEXIQUE_DU_TICKET.get(str(status or ""), "")


def libelle_ticket(status: str) -> str:
    """Le mot que l'utilisateur lit pour un statut de ticket (même mot que la tâche)."""
    cle = statut_ticket(status)
    return LEXIQUE[cle]["mot"] if cle else str(status or "")


def table() -> dict:
    """Le lexique complet, tel que servi à l'écran (`GET /api/lexique`, `base.html`)."""
    return {"entrees": LEXIQUE, "motifs": LEXIQUE_DU_MOTIF, "tickets": LEXIQUE_DU_TICKET}


def segment(statut: str) -> str:
    return SEGMENT_DU_STATUT.get(statut, "a_lancer")
