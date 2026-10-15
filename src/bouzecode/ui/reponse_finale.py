"""Texte a ecrire dans --result-file / --plan-output a la fin d'un run non interactif.

Un agent qui clot par l'outil FinalAnswer n'a AUCUN texte dans son dernier message assistant
(tout est dans l'appel d'outil) ; avant ce module, --result-file n'etait alors pas ecrit (agent
distant Rundeck, executions 257422-257423 du 2026-10-06 : pas de reponse.md). Ordre :
`config["_final_answer"]` s'il a ete pose sur CE dict (l'outil recoit parfois une copie : mesure
locale), sinon l'argument `answer` du dernier appel FinalAnswer. JAMAIS la prose : seul FinalAnswer
livre (cf. `cloture_cli`, qui n'appelle ce module que pour un run livre).
"""
import json


def _reponse_finalanswer(message: dict) -> str:
    for appel in reversed(message.get("tool_calls") or []):
        fonction = appel.get("function") or {}
        if (appel.get("name") or fonction.get("name")) != "FinalAnswer":
            continue
        arguments = appel.get("input") or appel.get("arguments") or fonction.get("arguments") or {}
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")
        return str(arguments.get("answer") or "")
    return ""


def texte_de_reponse(messages: list[dict], config: dict) -> str:
    if str(config.get("_final_answer") or "").strip():
        return str(config["_final_answer"])
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        reponse = _reponse_finalanswer(message)
        if reponse.strip():
            return reponse
    return ""
