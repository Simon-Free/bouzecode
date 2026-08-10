"""Manager profile prompt tests (no mocks): assert the manager is restricted to
agent-typology + sequencing, and that its token-lean flags actually shrink the
turn-protocol boilerplate. Everything runs on the REAL builtin profile + the REAL
prompt assembler — no unittest.mock."""
from __future__ import annotations

from bouzecode.backend.commands.extensions.agent_switch import _apply
from bouzecode.backend.core.context import build_system_prompt_parts
from bouzecode.backend.profiles.discovery import resolve_agent_profile
# Sources de vérité de PRODUCTION (pas de constantes recopiées dans le test) : le prédicat
# « cet outil peut-il muter l'arbre ? » du garde-fou d'isolation, et les deux jeux de
# typologies qui font que la ligne VERDICT du manager est load-bearing.
from bouzecode.web_v2.services.work.isolation import _tool_writes_working_tree
from bouzecode.web_v2.services.work.tickets import _VERDICT_TYPOLOGIES
from bouzecode.web_v2.services.work.workflow import NON_CODING_TYPOLOGIES


def _manager_config() -> dict:
    """Load the real manager profile and apply it into a fresh session config,
    exactly like the /agent switch does."""
    profile = resolve_agent_profile("manager")
    assert profile is not None, "builtin manager profile must resolve by name"
    config: dict = {}
    _apply(profile, config)
    return config


def test_manager_profile_declares_lean_and_no_enforcement_hooks():
    profile = resolve_agent_profile("manager")
    assert profile is not None
    assert "lean_prompt" in profile.hooks
    assert "no-enforcement" in profile.hooks


def test_apply_sets_token_lean_flags():
    config = _manager_config()
    # lean_prompt hook -> trims the heavy turn-protocol prose
    assert config["lean_turn_protocol"] is True
    # no-enforcement hook -> disables forced Methodology recovery at runtime
    assert config["enforce_methodology"] is False


def test_lean_prompt_drops_heavy_bookkeeping_sections():
    config = _manager_config()
    stable, _ = build_system_prompt_parts(config)
    # The verbose bookkeeping / turn-nudge sections must be gone for the manager.
    assert "# Discipline Methodology" not in stable
    assert "# Pourquoi cette forme" not in stable
    assert "# Avant de penser" not in stable


def test_non_lean_prompt_keeps_full_bookkeeping():
    # Sanity: without the lean flag the heavy sections are still present, proving
    # the trimming is driven by the manager flag and not globally removed.
    stable, _ = build_system_prompt_parts({})
    assert "# Discipline Methodology" in stable
    assert "# Pourquoi cette forme" in stable


def test_manager_role_is_typology_and_sequencing_only():
    config = _manager_config()
    stable, _ = build_system_prompt_parts(config)
    extra = config["_agent_system_prompt_extra"]
    # Role must be present in the assembled prompt.
    assert "# Active agent profile" in stable
    assert extra.strip() and extra.strip() in stable
    low = extra.lower()
    assert "typologie" in low
    # sequencing vocabulary (serie/parallele)
    assert "série" in low or "serie" in low
    assert "parallèle" in low or "parallele" in low


def test_manager_no_longer_codes_or_validates():
    """« Le manager ne code pas et ne valide pas » = il n'en a pas les MOYENS et la
    relecture est déléguée — et surtout PAS « le mot VERDICT est interdit chez lui ».

    L'ancienne assertion `"VERDICT" not in blob` poussait à casser la production pour
    faire verdir un test : le profil DOIT parler de VERDICT. Il réclame `VERDICT: OK|KO`
    à ses enfants et rend le sien, et c'est cette ligne que le serveur parse pour clore
    et router les tickets (`work/tickets.py::_VERDICT_TYPOLOGIES`, `work/wake.py`). La
    propriété réelle est structurelle, donc non contournable par une reformulation.
    """
    profile = resolve_agent_profile("manager")
    assert profile is not None

    # 1. Incapable de coder ET de valider : aucun outil accordé ne peut muter l'arbre,
    # et sans Bash il ne peut pas faire tourner une suite de tests sur un diff. On
    # réutilise le prédicat de PRODUCTION (garde-fou d'isolation) plutôt qu'une liste
    # de noms recopiée : ajouter Edit/Write/Bash/MultiEdit/un outil de plugin mutant
    # fait échouer ce test, même sous un nom que ce fichier ne connaît pas.
    assert profile.tools, "whitelist vide = AUCUNE restriction, donc écrivain"
    mutating = [tool for tool in profile.tools if _tool_writes_working_tree(tool)]
    assert mutating == [], f"le manager doit rester read-only, outils mutants : {mutating}"
    assert "Bash" not in profile.tools

    # 2. Son SEUL levier sur le code est le dispatch : la relecture indépendante d'un
    # enfant passe par un agent validateur qu'il spawne, jamais par lui.
    assert "Agent" in profile.tools

    # 3. Côté serveur, `manager` est une typologie read-only qui ne PRODUIT aucun diff :
    # aucune chaîne test-gate / validation / merge ne s'exécute pour son propre ticket.
    assert "manager" in NON_CODING_TYPOLOGIES

    # 4. Anti-régression du choix de conception : la ligne VERDICT est LOAD-BEARING.
    # La retirer du profil casserait la boucle manager -> codeur -> validateur -> merge.
    blob = profile.description + "\n" + profile.system_prompt_extra
    assert "VERDICT: OK" in blob and "VERDICT: KO" in blob
    assert "manager" in _VERDICT_TYPOLOGIES
