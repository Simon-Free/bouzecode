# [desc] Une FinalAnswer refusée se complète sans retaper `answer` : le harnais reprend le texte de la tentative. [/desc]
"""Reprise d'une clôture refusée ou suspendue.

Sessions claude-opus-5-5 du 2026-10-07 : d407d73d (clôture suspendue, même lot qu'un
`del`) et c4fe6829 (refus du validateur : seul `taches_restantes` manquait). Dans les
deux cas le modèle a retapé sa réponse entière — 2 k caractères de sortie plus la
réflexion, payés deux fois — pour corriger un champ ou ne rien changer du tout.

Règle : une FinalAnswer dont `answer` est omis (ou vide) reprend le texte de la dernière
tentative de la session, et chaque champ facultatif omis (`recap`, `parcours_verifies`)
reprend sa valeur. La reprise est écrite DANS l'appel, avant exécution : le validateur,
le transcript, l'interface et l'extraction du rapport voient la réponse complète.
La tentative est oubliée dès qu'une clôture est acceptée — une FinalAnswer vide d'une
demande suivante ne ressuscite jamais la réponse d'avant.
"""
from __future__ import annotations

_TENTATIVE = "_cloture_suspendue"
_CHAMPS_REPRIS = ("answer", "recap", "taches_terminees", "taches_restantes",
                  "parcours_verifies", "related_files")


def _vide(valeur) -> bool:
    return valeur is None or (isinstance(valeur, str) and not valeur.strip())


def reprendre_la_tentative_suspendue(tool_calls: list[dict], config: dict) -> None:
    """Complète chaque FinalAnswer sans `answer` par la tentative précédente, puis la retient."""
    for tc in tool_calls:
        params = tc.get("input")
        if tc.get("name") != "FinalAnswer" or not isinstance(params, dict):
            continue
        tentative = config.get(_TENTATIVE)
        if _vide(params.get("answer")) and tentative:
            for champ, valeur in tentative.items():
                if _vide(params.get(champ)):
                    params[champ] = valeur
        if not _vide(params.get("answer")):
            config[_TENTATIVE] = {champ: params[champ] for champ in _CHAMPS_REPRIS
                                  if champ in params}


def oublier_la_tentative(config: dict) -> None:
    """La clôture est acceptée : plus rien à reprendre."""
    config.pop(_TENTATIVE, None)
