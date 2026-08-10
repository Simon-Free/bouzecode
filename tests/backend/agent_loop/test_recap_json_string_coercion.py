"""Un récap sérialisé en CHAÎNE JSON (certains modèles, Opus inclus, le font au lieu de
passer un objet) doit être reparse en dict. Sinon le gate le lit comme « tous les champs
manquants » (refus en boucle) PUIS la persistance le jette (`state.recap` reste None car
non-dict) → tous les GET /recap sortent vides. Test du fix _coerce_recap / _final_answer."""
import json

from bouzecode.backend.tools.registration import _coerce_recap, _final_answer


_RECAP = {
    "symptoms": "Besoin d'une fonction human_join qui joint en langage naturel.",
    "explanation": "Fonction pure : virgules puis « et » avant le dernier élément.",
    "tests": "3 tests pytest verts (liste vide, un seul, plusieurs).",
    "changes": [{"file": "src/x.py", "summary": "ajoute human_join"}],
}


class FakeState:
    def __init__(self):
        self.final_answer = None
        self.recap = None
        self.recap_missing = False


def test_coerce_recap_parses_json_string():
    assert _coerce_recap(json.dumps(_RECAP)) == _RECAP


def test_coerce_recap_passthrough_dict_and_none():
    assert _coerce_recap(_RECAP) == _RECAP
    assert _coerce_recap(None) is None


def test_coerce_recap_non_json_string_left_unchanged():
    assert _coerce_recap("pas du json") == "pas du json"
    assert _coerce_recap("[1, 2, 3]") == "[1, 2, 3]"  # JSON valide mais pas un objet → inchangé


def test_final_answer_persists_recap_passed_as_json_string():
    state = FakeState()
    cfg = {"require_recap": True, "recap_expects_object": True, "close_validation": True,
           "_depth": 0, "model": "", "_state": state}

    out = _final_answer("rapport complet", cfg, recap=json.dumps(_RECAP))

    assert "Session closing" in out          # accepté du premier coup (récap complet)
    assert isinstance(state.recap, dict)      # persisté en DICT malgré l'entrée chaîne
    assert state.recap == _RECAP
    assert state.recap_missing is False


def test_final_answer_does_not_persist_recap_for_validator_run(monkeypatch):
    # Un validateur (BOUZECODE_RUN_KIND=validate) peut joindre un recap (prompt hérité du codeur)
    # mais il rend un VERDICT : son récap NE doit PAS être persisté (ni pastille ni concat manager).
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "validate")
    state = FakeState()
    cfg = {"close_validation": True, "_depth": 0, "model": "", "_state": state}
    out = _final_answer("VERDICT: OK", cfg, recap=_RECAP)
    assert "Session closing" in out          # clôture acceptée…
    assert state.recap is None                # …mais AUCUN récap persisté pour un validateur


def test_final_answer_string_recap_incomplete_still_refused():
    # Un récap chaîne INCOMPLET reste refusé (le gate voit bien le dict coercé, pas « tout manquant »).
    state = FakeState()
    cfg = {"require_recap": True, "recap_expects_object": True, "close_validation": True,
           "_depth": 0, "model": "", "_state": state}
    partial = json.dumps({"symptoms": "s", "explanation": "e"})  # tests/changes manquants (coding)

    out = _final_answer("rapport", cfg, recap=partial)

    assert "CLÔTURE REFUSÉE" in out
    assert "changes" in out and "tests" in out   # champs réellement manquants, pas tous
