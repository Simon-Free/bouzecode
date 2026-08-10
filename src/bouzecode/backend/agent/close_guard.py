# [desc] Décide si un tour SUPPORTE sa propre clôture : refus d'outils, sous-agent en fond. [/desc]
"""Ce qui autorise une session à se fermer — et ce qui le lui refuse.

Extrait de `loop_turn.py`, qui mêlait cette décision au streaming et à l'exécution
d'outils. Elle vit seule parce qu'elle a sa propre règle, son propre budget de refus et
son propre vocabulaire ; l'y noyer rendait invisible le fait que DEUX chemins très
différents aboutissent au même verdict.
"""
from __future__ import annotations

# Une session ne se ferme que sur un acte de clôture que le tour SUPPORTE réellement.
# Deux façons pour un tour de ne pas supporter sa propre clôture, une seule règle :
#   - la « clôture » n'est que de la prose à côté de la comptabilité
#     (Methodology/Snippet) -> aucun acte ;
#   - la clôture EST explicite (FinalAnswer) mais un outil du même lot n'a jamais
#     tourné -> la réponse s'appuie sur quelque chose qui n'a pas eu lieu.
# Les deux dépensent un tour à dire au modèle exactement pourquoi, sous le budget
# PARTAGÉ ctx.final_answer_nudges (« combien de fois le harnais a-t-il refusé de
# clôturer pour cet agent »), puis ferment avec un close_reason qui garde l'anomalie.
MAX_CLOSE_REFUSALS = 3

# Refus/abandons AU NIVEAU DU HARNAIS — l'outil n'a PAS fait son travail. Comparés
# ANCRÉS EN DÉBUT de résultat : c'est exactement ce qui sépare « le harnais a refusé
# l'appel » de « l'outil a tourné et sa sortie mentionne une erreur ». Un run pytest qui
# rapporte des tests rouges, un log de build, un grep qui tombe sur le mot Error — ce
# sont des appels RÉUSSIS rapportant un vrai résultat, et ils ne doivent jamais bloquer
# une clôture, sans quoi l'agent ne pourrait jamais livrer « les tests échouent parce que
# X ». Le vocabulaire ci-dessous est celui du harnais lui-même, issu de
# tool_registry.execute_tool et des chemins de refus de la boucle ; la carte des gardes
# est docs/investigations/refused_tool_attempts.md.
_TOOL_REFUSAL_PREFIXES = (
    "ERROR parsing your tool call XML:",
    "Error executing ",
    "Error: ",
    "Denied: ",
    "Skipped: a dependency was denied",
    "Cancelled: ",
    "[Plan mode]",
    "BLOCKED:",
)


def _refused_tool_results(tool_calls: list[dict], results: dict) -> list[tuple[str, str]]:
    """(nom d'outil, première ligne du refus) pour chaque appel refusé par le harnais.

    FinalAnswer n'est PAS exempté, et c'est tout l'intérêt : une réponse vide est
    arrêtée par le garde de paramètre requis du registre, qui rend « Error: ... » SANS
    jamais exécuter _final_answer — donc le drapeau `_final_answer_refused` de
    _final_answer n'était jamais posé et la session se fermait sur un livrable vide. Une
    seule règle, aucune exception : un acte de clôture que le harnais a refusé n'est pas
    une clôture.
    """
    refused = []
    for tc in tool_calls:
        raw = results.get(tc["id"])
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if text.startswith(_TOOL_REFUSAL_PREFIXES):
            refused.append((tc["name"], text.splitlines()[0]))
    return refused


def _close_over_failed_tool_nudge(refused: list[tuple[str, str]]) -> str:
    """Ce que lit le modèle quand sa FinalAnswer voyageait avec un outil refusé."""
    details = "\n".join(f"- {name} : {err}" for name, err in refused)
    return (
        "(System Automated Event): ta clôture n'a PAS été acceptée. Dans le tour "
        "où tu as appelé FinalAnswer, un appel d'outil n'a pas fait son travail :\n"
        f"{details}\n"
        "Ta réponse finale s'appuie donc sur un résultat que tu n'as jamais obtenu. "
        "Corrige la cause (ré-émets l'appel correctement, ou utilise un outil dont "
        "tu disposes), PUIS rappelle FinalAnswer. Si l'échec est irrémédiable, "
        "rappelle FinalAnswer en disant EXPLICITEMENT ce qui n'a pas pu être "
        "vérifié — ne présente jamais comme fait ce que l'outil n'a pas confirmé."
    )


def _bg_agent_keeps_turn_open(config: dict, tool_calls: list) -> bool:
    """Un sous-agent lancé EN FOND (outil Agent, mode web, wait=False) pendant ce tour
    signifie que le manager doit continuer SANS que le turn-protocol ne le pousse vers
    FinalAnswer ni ne ferme le tour. Consomme le drapeau (remis à zéro chaque tour) ;
    rend True si et seulement si un Agent de fond a été lancé ET que le manager n'a pas
    AUSSI appelé FinalAnswer explicitement dans le même lot (une FinalAnswer explicite
    est toujours honorée)."""
    launched = config.pop("_bg_agent_launched", False)
    if not launched:
        return False
    has_final_answer = bool(tool_calls) and any(
        tc.get("name") == "FinalAnswer" for tc in tool_calls
    )
    return not has_final_answer
