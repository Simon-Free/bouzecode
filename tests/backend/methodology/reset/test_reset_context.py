# [desc] ResetContext : archive identique à la note, ## User et ## Harnais gardés, travail retiré, archives chaînées à côté de la session, reason obligatoire, outil exposé au modèle. [/desc]
"""ResetContext — le modèle nettoie lui-même sa note quand la tâche change."""
from __future__ import annotations

from pathlib import Path

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.context_manager.methodology import reconstruct_methodology_from_timeline
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from bouzecode.backend.tools.registration import enabled_tools_for_profile, execute_tool

OLD_NOTE = (
    "## User @2026-10-07 10:00:00\nCorrige le bug de bail.\n\n"
    "### T1\n\nconstat : bug dans lease.py L42\n\n"
    "## Harnais @2026-10-07 10:05:00\n[harnais] Tu travailles désormais dans le worktree "
    "C:/wt/solo-3, branche agent/solo-3.\n- Récolte : commite sur agent/solo-3.\n\n"
    "### T2\n\ndécision : patcher compute_lease()\n\n"
    "## snippet: C:/src/lease.py :: compute_lease\ndef compute_lease(): ...\n\n"
    "## User @2026-10-07 11:00:00\nÉcris maintenant la doc de la CLI."
)


def _config(tmp_path: Path) -> dict:
    state = AgentState()
    state.context_state.notes[METHODOLOGY_NOTE] = OLD_NOTE
    return {"_context_state": state.context_state, "_state": state,
            "_session_file": str(tmp_path / "a1b2c3.session.json")}


def _reset(config: dict, **params) -> str:
    return execute_tool("ResetContext", params, permission_mode="accept-all", config=config)


def _note(config: dict) -> str:
    return config["_context_state"].notes[METHODOLOGY_NOTE]


def _archive_of(note: str) -> Path:
    ligne = next(l for l in note.splitlines() if l.startswith("Ancienne note archivée dans : "))
    return Path(ligne.split(" : ", 1)[1].strip())


def test_reset_archive_la_note_entiere_et_garde_user_et_harnais(tmp_path):
    config = _config(tmp_path)
    reponse = _reset(config, reason="passage du bug de bail à la doc CLI",
                     summary="bug corrigé dans compute_lease()")
    note = _note(config)

    archive = _archive_of(note)
    assert archive == tmp_path / "a1b2c3.session.context_1.md"
    assert archive.read_text(encoding="utf-8") == OLD_NOTE
    assert str(archive) in reponse and "## Contexte archivé @" in note

    assert note.count("## User @") == 2 and "Écris maintenant la doc de la CLI." in note
    assert "## Harnais @2026-10-07 10:05:00" in note and "Récolte : commite sur agent/solo-3." in note
    for travail in ("constat : bug dans lease.py", "décision : patcher", "## snippet:", "### T"):
        assert travail not in note
    assert "passage du bug de bail à la doc CLI" in note
    assert "bug corrigé dans compute_lease()" in note
    assert note.index("Corrige le bug") < note.index("## Harnais @") < note.index("Écris maintenant")


def test_reset_journalise_la_timeline_et_lache_le_cache(tmp_path):
    config = _config(tmp_path)
    context_state = config["_context_state"]
    context_state._methodology_cache_snapshot = OLD_NOTE
    _reset(config, reason="autre sujet")
    assert context_state._methodology_cache_snapshot is None
    assert reconstruct_methodology_from_timeline(config["_state"].notes_timeline) == _note(config)


def test_deux_resets_chainent_les_archives(tmp_path):
    config = _config(tmp_path)
    _reset(config, reason="premier changement")
    premiere = _archive_of(_note(config))
    config["_context_state"].notes[METHODOLOGY_NOTE] += "\n\n### T3\n\nnouveau travail"
    reponse = _reset(config, reason="second changement")
    seconde = _archive_of(_note(config))

    assert seconde == tmp_path / "a1b2c3.session.context_2.md"
    assert premiere.read_text(encoding="utf-8") == OLD_NOTE
    assert str(premiere) in seconde.read_text(encoding="utf-8")
    assert str(seconde) in reponse
    assert "nouveau travail" not in _note(config) and str(premiere) not in _note(config)


def test_sans_reason_erreur_sans_rien_ecrire(tmp_path):
    config = _config(tmp_path)
    reponse = _reset(config, summary="x")
    assert reponse.startswith("Error")
    assert _note(config) == OLD_NOTE
    assert list(tmp_path.iterdir()) == []


def test_outil_expose_au_modele():
    from bouzecode.backend.core.tool_registry import FRAMEWORK_ALWAYS_ON, get_tool_schemas
    assert "ResetContext" in FRAMEWORK_ALWAYS_ON
    schema = next(s for s in get_tool_schemas() if s["name"] == "ResetContext")
    assert schema["input_schema"]["required"] == ["reason"]
    for profil in ("default", "coder", "azure-deployer", "databricks-deployer"):
        assert "ResetContext" in enabled_tools_for_profile(profil)


def test_la_consigne_est_dans_le_system_prompt():
    prompt = (Path(__file__).parents[4] / "src" / "system_prompts"
              / "01_main_system_prompt.txt").read_text(encoding="utf-8")
    assert "`ResetContext(reason, summary)` en premier dans le lot" in prompt


def test_la_compaction_ne_resume_pas_le_renvoi_vers_l_archive(tmp_path):
    """Résumé, le bloc perdrait le chemin de l'archive : il est hors des candidats comme
    les blocs ## Harnais."""
    from bouzecode.backend.context_manager.compact_prose import _candidates, _units
    config = _config(tmp_path)
    _reset(config, reason="autre sujet")
    units = _units(_note(config) + "\n\n## prose\nun ajout ordinaire")
    candidats = [units[i] for i in _candidates(units)]
    assert not any(u.startswith(("## Contexte archivé", "## Harnais @")) for u in candidats)
    assert any(u.startswith("## prose") for u in candidats)
