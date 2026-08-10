# [desc] Phase COURANTE d'un lancement de ticket : ce que le serveur est en train de faire, écrit à chaque étape. [/desc]
"""Le champ `phase` d'un ticket, et les seuls mots autorisés pour le remplir.

POURQUOI CE MODULE EXISTE. `fleet._node` servait déjà `"phase": ticket.get("phase")` pour
les tickets en cours de lancement, et son commentaire annonçait `provisioning_worktree /
_venv / spawning`. Or AUCUN code de production n'écrivait ce champ — seul un test le posait.
Toute l'attente du lancement se présentait donc comme un unique `provisioning` indifférencié,
alors qu'elle enchaîne des étapes de durées très inégales sur ce poste : `git worktree add`
coûte ~50 s par essai (antivirus temps réel, cf. `worktrees.add_worktree_bounded`) et peut
être rejoué 3 fois, `uv sync --all-extras` court jusqu'à 600 s. L'utilisateur voyait « en
préparation » pendant plusieurs minutes sans pouvoir distinguer un provisionnement lent d'un
serveur bloqué.

Le vocabulaire est FERMÉ et porte son libellé : le serveur est la source unique des mots, si
bien qu'un agent de monitoring lisant l'API et l'interface humaine disent la MÊME chose. Un
libellé rendu ici, plutôt que recopié dans le front, évite exactement la divergence qui
existait déjà (le front commentait un badge « préparation… » qu'il n'implémentait pas).

La phase est un état TRANSITOIRE, jamais une issue : elle est posée avant une étape longue et
retirée par `tickets.add_run` (un agent a démarré) ou `dispatch.record_launch_failure` (le
lancement a échoué). Personne ne doit conclure quoi que ce soit d'une phase — le sort du
ticket se lit dans ses runs, comme avant.
"""
from __future__ import annotations

from . import tickets

# Une entrée par étape LONGUE et OBSERVABLE du lancement. Les étapes instantanées (créer la
# ligne du ticket, résoudre la typologie) n'en ont pas : annoncer une phase qu'on quitte dans
# la milliseconde n'informe personne et ne ferait que du bruit d'écriture dans le store.
PROVISIONING_WORKTREE = "provisioning_worktree"
SYNCING_VENV = "syncing_venv"
SPAWNING = "spawning"
REISOLATING = "reisolating"
VENV_READY = "venv_ready"
VENV_FAILED = "venv_failed"

# Libellés rendus tels quels par l'UI et par les agents de monitoring.
LABELS = {
    PROVISIONING_WORKTREE: "création du worktree",
    SYNCING_VENV: "installation de l'environnement uv",
    SPAWNING: "démarrage de l'agent",
    REISOLATING: "ré-isolation du worktree",
    VENV_READY: "environnement uv prêt",
    VENV_FAILED: "environnement uv en échec",
}

PHASE_KEY = "phase"
PHASE_AT_KEY = "phase_at"
PHASE_DETAIL_KEY = "phase_detail"


def set_phase(slug: str, ticket: dict, phase: str, detail: str = "") -> None:
    """Pose la phase courante du ticket, avec l'heure et un détail libre (branche de base,
    numéro d'essai). L'heure est ce qui rend l'attente LISIBLE : « création du worktree »
    depuis 4 s et depuis 4 min ne racontent pas la même histoire.

    Écriture read-modify-write ATOMIQUE d'une ligne (`_mutate`), comme tout ce qui touche un
    ticket en vol : le provisionnement tourne dans un thread de fond pendant que le watchdog
    et les requêtes de lecture écrivent le même store."""
    def _apply(fresh: dict) -> None:
        fresh[PHASE_KEY] = phase
        fresh[PHASE_AT_KEY] = tickets._now()
        if detail:
            fresh[PHASE_DETAIL_KEY] = detail
        else:
            fresh.pop(PHASE_DETAIL_KEY, None)

    tickets._mutate(slug, ticket["id"], _apply)
    _apply(ticket)  # miroir sur l'objet appelant, comme set_launching/add_run


def clear_phase(ticket: dict) -> None:
    """Retire les champs de phase d'un ticket DÉJÀ en cours de mutation.

    Appelée depuis les `_apply` de `tickets.add_run` et `record_launch_failure`, qui écrivent
    la ligne fraîche eux-mêmes : la phase disparaît donc DANS la mutation qui la rend inutile,
    sans seconde écriture ni fenêtre où le ticket porterait à la fois un run et une phase de
    lancement (le node afficherait « démarrage de l'agent » sur un agent qui tourne déjà)."""
    ticket.pop(PHASE_KEY, None)
    ticket.pop(PHASE_AT_KEY, None)
    ticket.pop(PHASE_DETAIL_KEY, None)


def drop_phase(slug: str, ticket: dict) -> None:
    """Retire la phase et la PERSISTE, pour les chemins qui finissent une étape longue sans
    passer par `add_run` (`dispatch.rehome_agent_cwd` : le worktree est reconstruit, mais c'est
    la route de reprise qui respawne l'agent). Sans cela le ticket garderait « ré-isolation du
    worktree » après la fin de la ré-isolation — une phase qui MENT est pire que pas de phase."""
    tickets._mutate(slug, ticket["id"], clear_phase)
    clear_phase(ticket)


def phase_view(ticket: dict) -> dict:
    """La phase d'un ticket telle qu'elle est SERVIE : {phase, phase_label, phase_detail,
    phase_at}. Dict vide si le ticket n'est pas dans une étape de lancement — un champ absent
    dit « rien en cours », là où un `phase: ""` servi sur des centaines de nodes ressemble à
    un signal et n'en porte aucun (même règle que `allow_freetext` dans `fleet._node`)."""
    phase = ticket.get(PHASE_KEY) or ""
    if not phase:
        return {}
    view = {
        "phase": phase,
        "phase_label": LABELS.get(phase, phase),
        "phase_at": ticket.get(PHASE_AT_KEY) or "",
    }
    detail = ticket.get(PHASE_DETAIL_KEY) or ""
    if detail:
        view["phase_detail"] = detail
    return view


LAUNCHING_STATE = "provisioning"


def status_for(ticket_id: str) -> dict | None:
    """Statut SERVI pour une conversation dont l'agent n'existe pas ENCORE, ou None si aucun
    lancement n'est en cours pour ce ticket.

    POURQUOI. Le corps de conversation ne sait lire qu'un `status` (cf. `/blocks`), et pendant
    tout le provisionnement il n'y a AUCUNE session à résoudre : la route répondait 404 et le
    front se rabattait sur un « Préparation de la conversation… » CONSTANT, écrit en dur, qui
    ne bougeait pas d'une lettre pendant les ~20 s (à froid, mesuré) à ~55 s que coûte
    `git worktree add` sur ce poste. La phase était pourtant connue du serveur à la seconde
    près — elle n'atteignait que la sidebar, via l'arbre et son cache.

    On rend donc ici le MÊME dictionnaire que `phase_view`, augmenté du seul état qui a du sens
    tant qu'aucun process n'existe (`provisioning`, déjà le mot de `fleet`). Aucun canal neuf :
    c'est le champ `status.phase` que le corps lit déjà toutes les 1,5 s pour les agents nés."""
    for _slug, ticket in tickets.launching_tickets():
        if ticket.get("id") == ticket_id:
            return {"state": LAUNCHING_STATE, **phase_view(ticket)}
    return None


def attempt_detail(attempt: int, total: int, error: str) -> str:
    """Détail d'un essai de provisionnement RATÉ, à afficher pendant que le suivant tourne.

    `add_worktree_bounded` rejoue un `git worktree add` qui a dépassé son délai, jusqu'à 3
    fois. Ces essais n'allaient QUE dans le log du serveur : côté utilisateur, un ticket
    pouvait rester deux minutes et demie en « préparation » sans que rien ne dise qu'on en
    était au troisième essai."""
    return f"essai {attempt}/{total} échoué ({error[:120]}) — nouvelle tentative"
