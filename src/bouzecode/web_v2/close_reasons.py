# [desc] Table unique close_reason -> livraison prouvée / clôture contrôlée ; `issue_de_fin` en déduit l'issue d'un run (livré, fin sans livraison, arrêté). [/desc]
"""Une seule table, deux questions.

Trois ensembles vivaient dans trois modules et répondaient chacun à sa question sans se
connaître : `runner` décidait du code retour, `wake` de l'avancement du ticket, `liveness`
de la vivacité. Ils divergeaient — `ends_turn_tool` était « propre » pour l'un et « planté »
pour l'autre — et `final_answer_over_failed_tool`, introduit le 2026-07-29, ne figurait dans
AUCUN : un agent ayant clos délibérément était rapporté PLANTÉ et son ticket gelé.

Règle (2026-10-06) : FinalAnswer est le SEUL acte terminal qui livre. La colonne « le ticket
avance » n'existait que pour `text_no_tools` (une réponse en prose valait livraison) ; une
prose sans outil n'étant plus une livraison nulle part, elle coïncidait avec « livraison
prouvée » et a été retirée.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Closure:
    """Ce qu'une raison de clôture prouve, pour les surfaces qui en décident."""

    proves_delivery: bool   # une réponse finale (FinalAnswer) est rendue : livré, rc 0
    controlled: bool        # la boucle a décidé de clore, pas une mort en vol  (liveness)


_DELIVERED = Closure(proves_delivery=True, controlled=True)
_FORCED = Closure(proves_delivery=False, controlled=True)
_CRASH = Closure(proves_delivery=False, controlled=False)

CLOSURES: dict[str, Closure] = {
    # ── Clôtures explicites : FinalAnswer, ou un autre outil `ends_turn`. ──
    "final_answer": _DELIVERED,
    "final_answer_deferred": _DELIVERED,
    "ends_turn_tool": _DELIVERED,
    # 2026-07-29 — réponse rendue APRÈS 3 relances sur un outil refusé. Classée comme une
    # livraison parce qu'elle en était une jusqu'ici : `loop._fire_completion` l'écrasait en
    # "final_answer". La dégrader en crash serait une régression, pas un correctif — c'est au
    # manager ou à l'humain de juger une livraison dont un outil a manqué, pas au classifieur.
    "final_answer_over_failed_tool": _DELIVERED,
    # 2026-08-19 — réponse rendue APRÈS 3 relances alors que la clôture voyageait avec
    # des outils dont le résultat n'est rendu qu'au tour suivant. Même classement que
    # ci-dessus, et pour la même raison : c'est une livraison, à charge de qui la relit
    # de juger ce sur quoi elle s'appuie. La geler ici ne ferait que rouvrir le trou.
    "close_over_unread_results": _DELIVERED,
    # ── Clôture sur prose sans tool call (TUI interactif uniquement). ──
    # Tout run non interactif (web, `-p`, Rundeck) exige FinalAnswer : la boucle relance le
    # modèle puis clôt en `final_answer_never_called`. Une session qui porte encore
    # `text_no_tools` (TUI, ou session d'avant la règle) n'a RIEN livré : fin maîtrisée,
    # sans livraison — `idle_no_delivery`, code de sortie 4.
    "text_no_tools": _FORCED,
    # ── Fins FORCÉES par la boucle : maîtrisées, mais rien n'a été livré. ──
    "final_answer_nudge_exhausted": _FORCED,
    "final_answer_never_called": _FORCED,
    "meta_only_cap": _FORCED,
    # 2026-08-26 — le modèle a renvoyé une complétion VIDE (ni texte, ni thinking, ni
    # tool call) et n'en est pas sorti après relance. `controlled` est VRAI : c'est la
    # boucle qui coupe, délibérément, pour ne pas enchaîner des tours stériles à 0,2 s.
    # Rien n'est livré et le ticket n'avance pas — un run coupé ainsi doit ressortir
    # comme à reprendre (souvent sur un AUTRE modèle : la cause est côté endpoint).
    "empty_completion": _FORCED,
    # Le modèle (ou le filtre de l'endpoint) a REFUSÉ la requête (`loop_turn`, stop_reason
    # `content_filter`) malgré les relances du backend. C'est la boucle qui coupe, délibérément.
    # Le refus est aléatoire (même lecture refusée 2 fois puis acceptée, 2026-10-06) : rien
    # n'est livré ; à relancer, puis sur un autre modèle s'il se répète.
    "content_refusal": _FORCED,
    # 2026-08-13 — plafond de tours enchaînés (loop.MAX_AUTONOMOUS_TURNS). `controlled`
    # est VRAI : c'est bien la boucle qui a décidé d'arrêter, pas une mort en vol. Le
    # bruit vient des deux autres colonnes — rien n'est livré, le ticket n'avance pas —
    # et c'est le classement juste : un agent arrêté au plafond doit ressortir comme un
    # run raté à reprendre, pas comme un crash provider qu'on relancerait à l'identique.
    "max_turns_exceeded": _FORCED,
    "meta_only_text_close": _FORCED,  # cf. LEGACY_CLOSE_REASONS
    # ── Morts en vol : posées par le runner/l'IPC, jamais par la boucle. ──
    "api_error": _CRASH,
    "cancelled": _CRASH,
    "assistant_none": _CRASH,
    "partial_stream": _CRASH,
    # 2026-08-26 — le stream du provider s'est TU (aucun evenement pendant
    # BOUZECODE_STREAM_STALL_TIMEOUT_S, defaut 300 s) et le tour n'a jamais rendu de
    # reponse. `controlled` est FAUX volontairement : ce n'est pas la boucle qui a
    # decide de couper mais l'endpoint qui est mort en vol — meme nature qu'`api_error`
    # /`partial_stream`. Le classer maitrise mentirait a la vue liveness et priverait
    # d'une relance automatique un run tue par un provider muet.
    "stream_stalled": _CRASH,
}

# Raison absente de la table : rien n'est prouvé. Repli délibérément pessimiste — une clôture
# qu'on ne sait pas nommer ne doit ni valider un rc 0 ni faire avancer un ticket.
UNKNOWN = _CRASH

# Raisons que la boucle NE PRODUIT PLUS mais que des sessions sur disque portent encore.
# Les retirer de la table reclasserait ces sessions en « plantées » : `liveness` lit des
# tickets vieux de plusieurs semaines. Déclarées ICI pour que le garde anti-fantôme
# (tests/web_v2/test_close_reasons_table.py) distingue une survivance ASSUMÉE d'un oubli.
LEGACY_CLOSE_REASONS = frozenset({
    "meta_only_text_close",  # l'arme `text_closes` a été retirée (cf. b83ade94)
})

DELIVERY_CLOSE_REASONS = frozenset(r for r, c in CLOSURES.items() if c.proves_delivery)
CONTROLLED_CLOSE_REASONS = frozenset(r for r, c in CLOSURES.items() if c.controlled)
CRASH_CLOSE_REASONS = frozenset(r for r, c in CLOSURES.items() if not c.controlled)


def closure(close_reason: str) -> Closure:
    return CLOSURES.get(close_reason or "", UNKNOWN)


def proves_delivery(close_reason: str) -> bool:
    """rc 0 : une réponse finale est prouvée sur disque."""
    return closure(close_reason).proves_delivery


def is_controlled(close_reason: str) -> bool:
    """La boucle a décidé de clore — par opposition à une mort en vol."""
    return closure(close_reason).controlled


def is_crash(close_reason: str) -> bool:
    """Mort en vol NOMMÉE. Une raison inconnue n'en est pas une : l'appelant la traite déjà
    comme non livrée, mais ne doit pas la libeller « plantée » sur la foi d'un nom qu'il ne
    connaît pas."""
    return close_reason in CLOSURES and not CLOSURES[close_reason].controlled


#: Mort en vol → code de `state_reason` du ticket arrêté (`stopped`).
_CODE_D_ARRET = {"cancelled": "interrupted", "api_error": "api_error"}


def issue_de_fin(close_reason: str, final_answer: bool = False) -> tuple[str, str]:
    """LA table de fin d'un run (spec C14) : `(issue, code)`, issue ∈ `delivered` |
    `idle_no_delivery` | `stopped`, `code` = la `state_reason` posée sur le ticket.

    * une clôture qui PROUVE la livraison (FinalAnswer…) → `delivered` ;
    * une fin MAÎTRISÉE sans livraison (max_turns_exceeded, complétion vide, FinalAnswer jamais
      appelé, refus, prose sans outil…) → `idle_no_delivery` — jamais `delivered` : rien n'a été
      rendu, même si la boucle s'est arrêtée proprement ;
    * une mort en vol (api_error, annulation, stream coupé…) → `stopped` ;
    * une raison absente ou inconnue : `delivered` seulement si une réponse finale est sur
      disque, sinon `stopped` (crash silencieux)."""
    connue = close_reason in CLOSURES
    if connue and CLOSURES[close_reason].proves_delivery:
        return "delivered", close_reason
    if connue and CLOSURES[close_reason].controlled:
        return "idle_no_delivery", close_reason
    if connue:
        return "stopped", _CODE_D_ARRET.get(close_reason, "crashed")
    if final_answer:
        return "delivered", close_reason or "final_answer"
    return "stopped", "crashed"
