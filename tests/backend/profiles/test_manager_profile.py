"""User-centric checks on the built-in `manager` profile.

The manager is a pure dispatcher/router: its ONLY job is to characterize the
agent TYPOLOGY per ticket and decide the SEQUENCING (series vs parallel). It
must not code/validate/review, and its per-turn Methodology/Snippet bookkeeping
(plus the empty-turn nudge) must be disabled via the `no-enforcement` hook.

No mocks: we load the REAL YAML profile and apply it through the REAL
SubAgentManager, then assert on the resulting effective config and prompt.
"""
import re
from pathlib import Path

import bouzecode.backend.profiles as profiles_pkg
from bouzecode.backend.profiles.loader import load_profile_from_path
from bouzecode.backend.multi_agent.manager import SubAgentManager

MANAGER_YAML = Path(profiles_pkg.__file__).parent / "builtin" / "manager.yaml"

# Épingler une formulation EXACTE (« tu ne codes pas ») casse au premier reformulage sans
# rien prouver de plus : le profil dit aujourd'hui « Tu n'écris ni code ni tests ». On
# accepte donc une FAMILLE de tournures par rôle interdit, et on exige qu'au moins une
# reste présente. La preuve STRUCTURELLE de ces mêmes propriétés (aucun outil capable de
# muter l'arbre, typologie non-codante côté serveur) vit dans
# tests/backend/prompts/test_manager_prompt.py::test_manager_no_longer_codes_or_validates.
_FORBIDDEN_IN_PROMPT = {
    "coder": (r"tu ne codes? (?:pas|jamais)",
              r"tu n['’](?:é|e)cris (?:ni|pas de|aucun)[^.\n]{0,40}code",
              r"tu ne corriges (?:pas|jamais)",
              r"tu n['’]as pas d['’]outil d['’](?:é|e)dition"),
    "valider le travail des agents": (r"tu ne valides? (?:pas|jamais)",
                                      r"la validation[^.\n]{0,60}pas (?:par )?toi"),
    "relire le travail des agents": (r"tu ne relis (?:pas|jamais)",
                                     r"tu ne (?:fais|effectues)[^.\n]{0,25}relecture"),
}
_FORBIDDEN_IN_DESCRIPTION = {
    "coder": (r"ne code (?:pas|jamais)", r"n['’](?:é|e)crit (?:ni|pas de|aucun)[^.\n]{0,40}code",
              r"read.?only", r"lecture seule"),
    "valider le travail des agents": (r"ne valide (?:pas|jamais)",),
}


def _load_manager():
    return load_profile_from_path(MANAGER_YAML)


def _states_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Le texte porte-t-il AU MOINS UNE des tournures acceptées pour ce rôle ?"""
    return any(re.search(pattern, text) for pattern in patterns)


def test_manager_yaml_exists():
    assert MANAGER_YAML.is_file(), f"missing builtin profile: {MANAGER_YAML}"


def test_manager_role_is_typology_and_sequencing_only():
    """The prompt must scope the manager to typology + sequencing, nothing else."""
    profile = _load_manager()
    prompt = profile.system_prompt_extra.lower()
    desc = profile.description.lower()

    # Core mission keywords present.
    assert "typologie" in prompt
    assert "séquencement" in prompt
    assert "série" in prompt and "parallèle" in prompt
    assert "typologie" in desc and "séquencement" in desc

    # Rôles explicitement interdits — vérifiés par FAMILLE de formulations (cf. plus haut) :
    # la propriété tenue est « le prompt interdit ce rôle », pas « le prompt contient cette
    # phrase-là ». Un rôle qui disparaît du prompt échoue ; un reformulage ne casse pas.
    for role, patterns in _FORBIDDEN_IN_PROMPT.items():
        assert _states_any(prompt, patterns), f"le prompt du manager n'interdit plus : {role}"
    for role, patterns in _FORBIDDEN_IN_DESCRIPTION.items():
        assert _states_any(desc, patterns), f"la description du manager n'interdit plus : {role}"


def test_manager_hook_disables_methodology_enforcement():
    """`no-enforcement` must flip enforce_methodology off (kills the bookkeeping
    + turn-protocol nudge) while leaving other flags untouched."""
    profile = _load_manager()
    assert "no-enforcement" in profile.hooks

    eff_config: dict = {}
    SubAgentManager()._apply_profile(profile, eff_config, "BASE")

    assert eff_config["enforce_methodology"] is False
    # We did NOT disable loop detection / test enforcement — those stay default
    # (absent from eff_config since no hook toggled them).
    assert "detect_loops" not in eff_config
    assert "enforce_tests" not in eff_config


def test_manager_is_readonly_dispatcher():
    """The manager owns no write/edit tools — it only reads, routes, dispatches."""
    profile = _load_manager()
    assert "Agent" in profile.tools
    assert "Edit" not in profile.tools
    assert "Write" not in profile.tools
    assert profile.plan_mode is False


# Le manager `31b01ead` a dispatché SIX enfants pour DEUX livrables : trois écrivains sur le
# même (trois implémentations concurrentes, deux jetées) et zéro sur l'autre. Le profil ne
# disait rien du découpage — ni « un seul écrivain par livrable », ni « couvre tout », ni la
# différence entre investiguer et implémenter. Ces trois propriétés sont désormais exigées.

def test_manager_requires_one_implementation_ticket_per_deliverable():
    """La règle qui manquait : un livrable = un écrivain, ni deux ni zéro."""
    prompt = _load_manager().system_prompt_extra.lower()

    assert _states_any(prompt, (r"un seul ticket d['’]impl(?:é|e)mentation par livrable",
                                r"un livrable[^.\n]{0,20}un (?:seul )?(?:é|e)crivain"))
    assert _states_any(prompt, (r"jamais deux (?:é|e)crivains", r"deux (?:é|e)crivains sur le m(?:ê|e)me")), \
        "le profil n'interdit plus le doublon d'écrivains"
    assert _states_any(prompt, (r"jamais z(?:é|e)ro (?:é|e)crivain", r"z(?:é|e)ro (?:é|e)crivain sur un livrable")), \
        "le profil n'exige plus qu'aucun livrable ne reste sans écrivain"


def test_manager_separates_investigation_from_implementation():
    """Trois investigations sur un sujet ne remplacent pas l'implémentation manquante."""
    prompt = _load_manager().system_prompt_extra.lower()

    assert "investigation" in prompt and "implémentation" in prompt
    assert _states_any(prompt, (r"investigation[^.\n]{0,80}(?:ne construit rien|rend un chiffre)",
                                r"deux r(?:ô|o)les")), \
        "le profil ne distingue plus investiguer et implémenter"


def test_manager_is_told_that_a_prose_read_only_mandate_provisions_nothing():
    """`e6846ab5`, brieffé READ-ONLY mais typé `coder`, a écrit du code de production et une
    migration : la prose n'ôte aucun outil. Le profil doit le dire, comme il le dit déjà de
    `work_branch`."""
    prompt = _load_manager().system_prompt_extra.lower()

    assert _states_any(prompt, (r"read.?only[^.\n]{0,60}ne provisionne rien",
                                r"« read-only »[^.\n]{0,60}ne provisionne rien"))
    # La consigne doit être ACTIONNABLE : nommer le levier réel (la typologie).
    assert _states_any(prompt, (r"mandat de lecture seule se provisionne par la \*\*typologie",
                                r"se provisionne par la \*\*typologie",
                                r"choisis[^.\n]{0,60}typologie dont les outils ne peuvent pas (?:é|e)crire"))
