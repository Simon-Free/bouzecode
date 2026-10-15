# [desc] Deterministic FinalAnswer close gate: recap, mandatory task declarations, proven parcours. [/desc]
"""Closure gate for FinalAnswer, fully deterministic (no LLM call).

The LLM validator that re-read the Methodology against the answer was
decommissioned (2026-10-08): it refused valid closes on free-text guesses.
What remains: `taches_terminees` / `taches_restantes` are ALWAYS required (an
explicit empty list is valid), the structured recap for profiles that set
`require_recap`, and the proven-parcours gate. Disabled by
config['close_validation'] = False."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_RECAP_SECTION_MARKERS = ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.")


def missing_recap_sections(answer: str) -> list[str]:
    """Deterministic (no LLM) check that the FinalAnswer carries the 6 mandatory
    recap section headers `## 1.` .. `## 6.`. Returns the list of missing markers."""
    text = answer or ""
    return [m for m in _RECAP_SECTION_MARKERS if m not in text]


# Retry cap for the structured-recap gate: after this many refusals the close is
# ACCEPTED anyway (with recap_missing=True) so a session is never bricked forever.
RECAP_RETRY_CAP = 3


#  `recap.points_ouverts` a été RETIRÉ (§10.4) : un point que l'agent ne peut pas
#  trancher se déclare dans `taches_restantes` avec `decision=true`. Deux chemins
#  pour la même chose produisaient des doublons silencieux au Bureau.


def missing_taches_fields(taches_terminees: object, taches_restantes: object) -> list[str]:
    """Deterministic (no LLM) check of the two MANDATORY close declarations.

    `taches_terminees` = what the agent declares finished, one string per task.
    `taches_restantes` = what is left, one object per task carrying `titre` (the
    short line, REQUIRED), an optional `corps` (the long brief) and an OPTIONAL
    attachment to a macro-task: `macro_id` when known, else `macro_titre` (a proposal),
    else nothing — the item then inherits the chantier of the ticket that launched the
    agent (cloture_micros). An agent cannot know the ids: requiring one refused valid
    closes in a loop (seen 2026-09-24 on DeepSeek).
    An EXPLICIT empty list is a valid answer (« nothing left »); OMITTING the field
    is not — telling « nothing to do » apart from « I did not answer » is the whole
    point of making these fields required. Returns missing/ill-shaped labels.
    """
    missing: list[str] = []
    if not isinstance(taches_terminees, list):
        missing.append("taches_terminees")
    else:
        for i, item in enumerate(taches_terminees):
            if not isinstance(item, str) or not item.strip():
                missing.append(f"taches_terminees[{i}]")
    if not isinstance(taches_restantes, list):
        missing.append("taches_restantes")
        return missing
    for i, tache in enumerate(taches_restantes):
        if not isinstance(tache, dict):
            missing.append(f"taches_restantes[{i}].titre")
            continue
        if not str(tache.get("titre", "")).strip():
            missing.append(f"taches_restantes[{i}].titre")
        #  Rattachement OPTIONNEL (macro_id, macro_titre, ou rien → chantier hérité du
        #  ticket) : l'exiger refusait des clôtures valides en boucle.
        options = tache.get("options")
        if options is not None and (
            not isinstance(options, list)
            or any(
                not isinstance(opt, dict)
                or not str(opt.get("key", "")).strip()
                or not str(opt.get("label", "")).strip()
                for opt in options
            )
        ):
            missing.append(f"taches_restantes[{i}].options")
    return missing


def missing_recap_fields(recap: object, coding: bool) -> list[str]:
    """Deterministic (no LLM) check that the structured `recap` object carries the
    mandatory fields. Coding sessions require symptoms/explanation/tests/changes
    (changes non-empty, each item carrying file+summary). Non-coding sessions
    (study/question) only require symptoms/explanation. Returns missing-field labels."""
    if not isinstance(recap, dict):
        base = ["symptoms", "explanation"]
        return base + (["tests", "changes"] if coding else [])
    missing: list[str] = []
    for field_name in ("symptoms", "explanation"):
        if not str(recap.get(field_name, "")).strip():
            missing.append(field_name)
    if not coding:
        return missing
    if not str(recap.get("tests", "")).strip():
        missing.append("tests")
    changes = recap.get("changes")
    if not isinstance(changes, list) or not changes:
        missing.append("changes")
    else:
        for i, item in enumerate(changes):
            if not isinstance(item, dict) or not str(item.get("file", "")).strip() \
                    or not str(item.get("summary", "")).strip():
                missing.append(f"changes[{i}].file+summary")
    return missing



def _journal_avec_le_lot(state, config: dict) -> list:
    """Les messages de la session PLUS les résultats déjà rendus par le lot en cours.

    La boucle n'ajoute les résultats d'un lot à `state.messages` qu'une fois le lot fini ; or
    FinalAnswer s'exécute DANS le lot. Essai du 2026-09-25 (racine 6bafe9cd, refus n° 4) : la
    recette `bash /tmp/pe-pw/all.sh 8802` avait tourné juste avant FinalAnswer, dans le même
    lot, et la porte la jugeait « échouée () » faute d'en voir le résultat."""
    messages = list(getattr(state, "messages", None) or [])
    lot = config.get("_resultats_du_lot") or {}
    deja = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    return messages + [{"role": "tool", "tool_call_id": tid, "content": contenu}
                       for tid, contenu in lot.items() if tid not in deja]


def _agent_delegue() -> bool:
    """Lancé par un autre agent (et non par l'utilisateur ou un dispatcher du serveur) ?

    Une tâche du Bureau lancée par l'assistant a un parent (qui est prévenu de sa fin) mais son
    prompt est la tâche de l'humain, pas un brief : `BOUZECODE_BRIEF_HUMAIN` (posé par
    `runner._ticket_env`) la traite comme un lancement par l'utilisateur."""
    import os
    if os.environ.get("BOUZECODE_BRIEF_HUMAIN") == "1":
        return False
    parent = os.environ.get("BOUZECODE_PARENT", "").strip()
    return bool(parent) and not parent.startswith("dispatcher:")


def validate_close(
    answer: str,
    config: dict,
    recap: object = None,
    taches_terminees: object = None,
    taches_restantes: object = None,
    parcours_verifies: object = None,
) -> tuple[bool, str]:
    """Return (accepted, feedback). Accepts on any failure, with a warning log.

    When `recap` (a structured object) is provided the deterministic gate validates
    that OBJECT (symptoms/explanation/tests/changes). When it is absent the gate
    falls back to the legacy 6-section markdown check on `answer` (backward compat).
    A retry cap (RECAP_RETRY_CAP) prevents bricking a session forever: past the cap
    the close is accepted and config['_recap_missing'] is flagged."""
    if config.get("close_validation", True) is not False:
        missing: list[str] = []
        label = "champs manquants"
        if config.get("require_recap") and config.get("_depth", 0) == 0:
            coding = config.get("recap_coding", True)
            if recap is not None or config.get("recap_expects_object"):
                missing = missing_recap_fields(recap, coding)
            else:
                missing = missing_recap_sections(answer)
                label = "sections manquantes"
        #  Les deux DÉCLARATIONS de clôture sont exigées pour tout profil et toute
        #  profondeur : ce qui n'est pas déclaré n'existe pas, et aucun LLM ne relit
        #  la réponse pour le deviner. Une liste vide [] est valide, l'omission non.
        #  EXCEPTION : un profil `require_taches: false` (bureau-assistant, qui tient
        #  déjà la TODO via les outils Taches) peut les omettre ; fournies, elles
        #  restent validées et consommées comme pour les autres profils.
        if config.get("require_taches", True) is not False or (
            taches_terminees is not None or taches_restantes is not None
        ):
            missing += missing_taches_fields(taches_terminees, taches_restantes)
        if missing:
            retries = int(config.get("_recap_retry_count", 0)) + 1
            config["_recap_retry_count"] = retries
            if retries > RECAP_RETRY_CAP:
                # Never brick a session: accept after the cap, flag recap as missing.
                config["_recap_missing"] = True
                logger.warning(
                    "close_validator: close still incomplete after %d retries "
                    "(%s: %s) — accepting close with recap_missing=True",
                    retries - 1, label, " ; ".join(missing),
                )
                return True, ""
            return False, (
                f"récap incomplet — {label} : " + " ; ".join(missing) + "\n"
                "Fournis chaque champ nommé ci-dessus. Une liste vide [] est une "
                "réponse VALIDE (« rien ne reste ») ; l'omettre ne l'est pas. "
                "Chaque tâche restante porte un `titre` (la ligne courte, OBLIGATOIRE), "
                "un `corps` optionnel (le brief long), éventuellement son chantier — `macro_id` "
                "si tu le connais, sinon `macro_titre` ; sans rien, elle rejoint le chantier "
                "de ta tâche — et "
                "decision:true quand elle attend un arbitrage humain plutôt qu'un agent."
            )
    return True, ""
