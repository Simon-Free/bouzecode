"""Deterministic recap-gate on close: profiles with require_recap MUST deliver a
FinalAnswer carrying the 6 mandatory sections (## 1. .. ## 6.). The check runs
BEFORE any LLM validation, so it fires regardless of the model backend."""
import bouzecode.backend.agent.close_validator as cv


_SIX_SECTIONS = (
    "## 1. Résumé\nLe bug.\n\n"
    "## 2. Cause / plan (vulgarisé)\nExplication simple.\n\n"
    "## 3. Tests ajoutés pour reproduire / valider\nUn test.\n\n"
    "## 4. Modifications (ordre logique)\n1. edit.\n\n"
    "## 5. Diffs des fichiers de code\n(diff)\n\n"
    "## 6. Nouveaux tests / corrections (test_*.py)\n(diff test)\n"
)


def _base_config(**over):
    cfg = {"require_recap": True, "close_validation": True, "_depth": 0, "model": ""}
    cfg.update(over)
    return cfg


def test_missing_recap_sections_detects_missing():
    assert cv.missing_recap_sections("no sections here") == list(
        ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.")
    )


def test_missing_recap_sections_all_present():
    assert cv.missing_recap_sections(_SIX_SECTIONS) == []


def test_missing_recap_sections_partial():
    partial = "## 1. Résumé\n## 2. Cause\n## 3. Tests"
    assert cv.missing_recap_sections(partial) == ["## 4.", "## 5.", "## 6."]


def test_validate_close_refuses_answer_without_recap(monkeypatch):
    # Le check déterministe doit rejeter AVANT tout appel LLM.
    def _boom(*a, **k):
        raise AssertionError(
            "dispatch_stream ne doit PAS être appelé : "
            "le check déterministe doit court-circuiter"
        )

    monkeypatch.setattr(cv, "dispatch_stream", _boom, raising=False)

    accepted, feedback = cv.validate_close(
        "Rapport de routage : j'ai dispatché les sous-tâches.",
        _base_config(require_recap=True),
    )
    assert accepted is False
    assert "sections manquantes" in feedback


def test_validate_close_skips_recap_when_not_required(monkeypatch):
    # require_recap absent → pas de check récap ; sans model natif, _should_validate
    # est False → accepte sans appeler le LLM.
    def _boom(*a, **k):
        raise AssertionError("dispatch_stream ne doit PAS être appelé")

    monkeypatch.setattr(cv, "dispatch_stream", _boom, raising=False)

    accepted, feedback = cv.validate_close(
        "n'importe quoi sans sections",
        _base_config(require_recap=False),
    )
    assert accepted is True
    assert feedback == ""


def test_validate_close_recap_present_passes_gate(monkeypatch):
    # 6 sections présentes → le check récap NE bloque pas ; sans model natif
    # _should_validate=False → accepte sans appel LLM.
    def _boom(*a, **k):
        raise AssertionError("dispatch_stream ne doit PAS être appelé")

    monkeypatch.setattr(cv, "dispatch_stream", _boom, raising=False)

    accepted, feedback = cv.validate_close(
        _SIX_SECTIONS,
        _base_config(require_recap=True),
    )
    assert accepted is True


# --- T7: structured recap object gate --------------------------------------

_FULL_RECAP = {
    "symptoms": "Le bug X cassait la clôture.",
    "explanation": "Cause racine : Y n'était pas vérifié. Correctif : ajout du check.",
    "tests": "3 tests unit verts couvrant le gate recap.",
    "changes": [
        {"file": "src/bouzecode/backend/agent/close_validator.py",
         "summary": "Ajoute le gate objet recap."},
    ],
}


def _no_llm(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("dispatch_stream ne doit PAS être appelé")
    monkeypatch.setattr(cv, "dispatch_stream", _boom, raising=False)


def test_missing_recap_fields_coding_all_missing():
    assert cv.missing_recap_fields(None, coding=True) == [
        "symptoms", "explanation", "tests", "changes"
    ]


def test_missing_recap_fields_non_coding_only_two():
    assert cv.missing_recap_fields(None, coding=False) == [
        "symptoms", "explanation"
    ]


def test_missing_recap_fields_full_recap_ok():
    assert cv.missing_recap_fields(_FULL_RECAP, coding=True) == []


def test_missing_recap_fields_changes_item_incomplete():
    recap = {**_FULL_RECAP, "changes": [{"file": "a.py"}]}  # summary manquant
    assert cv.missing_recap_fields(recap, coding=True) == ["changes[0].file+summary"]


def test_missing_recap_fields_non_coding_ignores_tests_changes():
    recap = {"symptoms": "s", "explanation": "e"}  # pas de tests/changes
    assert cv.missing_recap_fields(recap, coding=False) == []


def test_recap_object_gate_rejects_then_accepts_on_second_try(monkeypatch):
    # Boucle rejet -> 2e essai : 1er FinalAnswer sans recap objet -> REFUS ;
    # 2e essai avec recap complet -> ACCEPTÉ. Aucun LLM appelé (check déterministe).
    _no_llm(monkeypatch)
    cfg = _base_config(require_recap=True, recap_expects_object=True)

    accepted, feedback = cv.validate_close("un rapport texte", cfg, recap=None)
    assert accepted is False
    assert "champs manquants" in feedback

    accepted, feedback = cv.validate_close("un rapport texte", cfg, recap=_FULL_RECAP)
    assert accepted is True
    assert feedback == ""


def test_recap_object_gate_retry_cap_never_bricks(monkeypatch):
    # Au-delà du plafond de retries, la clôture est ACCEPTÉE quand même
    # avec config["_recap_missing"]=True (ne jamais bloquer indéfiniment).
    _no_llm(monkeypatch)
    cfg = _base_config(require_recap=True, recap_expects_object=True)

    for _ in range(cv.RECAP_RETRY_CAP):
        accepted, _fb = cv.validate_close("txt", cfg, recap=None)
        assert accepted is False
    accepted, feedback = cv.validate_close("txt", cfg, recap=None)
    assert accepted is True
    assert cfg.get("_recap_missing") is True
