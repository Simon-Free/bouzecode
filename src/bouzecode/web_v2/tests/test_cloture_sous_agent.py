"""Un SOUS-AGENT qui clôture n'alimente plus la TODO du Bureau.

Mesuré (2026-10-15) : chaque sous-agent déversait ses `taches_restantes` dans le Bureau,
plusieurs centaines de lignes. Désormais seule la clôture d'un agent RACINE crée des
micro-tâches ; le reste d'un sous-agent figure dans le rapport que lit son parent.
Les deux déclarations (`taches_terminees`, `taches_restantes`) restent OBLIGATOIRES pour
un sous-agent : elles vont à son parent, jamais à la TODO.
Le test passe par l'outil enregistré puis par l'acceptation de la clôture, comme la boucle.
"""
from types import SimpleNamespace

from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.multi_agent.profondeur import ENV_PROFONDEUR
from bouzecode.backend.tools import registration
from bouzecode.web_v2.services.work import micros

FAIT = ["corrigé le bouton"]
RESTE = [{"titre": "Câbler l'onglet export", "corps": "le bouton existe, pas la route"}]
_TOUT = object()


def _cloturer(monkeypatch, profondeur, terminees=_TOUT, restantes=_TOUT):
    monkeypatch.setenv(ENV_PROFONDEUR, str(profondeur))
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "work")
    monkeypatch.delenv("BOUZECODE_TICKET_ID", raising=False)
    monkeypatch.delenv("BOUZECODE_TICKET_SLUG", raising=False)
    registration._register_builtins()
    state = SimpleNamespace(final_answer=None, recap=None, related_files=None,
                            taches_terminees=None, taches_restantes=None,
                            taches_declarees=False, recap_missing=False,
                            cloture_en_attente_des_enfants=None)
    config = {"_depth": 0, "model": "", "_state": state, "_session_id": "s-test"}
    params = {"answer": "Travail livré."}
    if terminees is not None:
        params["taches_terminees"] = FAIT if terminees is _TOUT else terminees
    if restantes is not None:
        params["taches_restantes"] = RESTE if restantes is _TOUT else restantes
    rendu = get_tool("FinalAnswer").func(params, config)
    if not config.get("_final_answer_refused"):
        registration.ouvrir_micros_de_cloture_acceptee(config)
    return rendu, state, config


def _titres():
    return [m.get("titre") for m in micros.list_micros()]


def test_sous_agent_sans_les_deux_listes_est_refuse(monkeypatch):
    avant = _titres()
    for terminees, restantes in ((None, None), (None, _TOUT), (_TOUT, None)):
        rendu, state, config = _cloturer(monkeypatch, 1, terminees, restantes)
        assert config.get("_final_answer_refused"), rendu
        assert state.final_answer is None
    assert _titres() == avant


def test_sous_agent_listes_vides_acceptees(monkeypatch):
    avant = _titres()
    rendu, state, config = _cloturer(monkeypatch, 1, terminees=[], restantes=[])
    assert not config.get("_final_answer_refused"), rendu
    assert state.taches_declarees is True
    assert _titres() == avant


def test_sous_agent_ne_touche_pas_la_todo_mais_le_parent_lit_tout(monkeypatch):
    avant = list(micros.list_micros())
    rendu, state, config = _cloturer(monkeypatch, profondeur=1)
    assert not config.get("_final_answer_refused"), rendu
    assert list(micros.list_micros()) == avant
    for texte in (state.final_answer, rendu):
        assert "Câbler l'onglet export" in texte
        assert "corrigé le bouton" in texte
    assert state.taches_restantes == RESTE
    assert state.taches_terminees == FAIT


def test_agent_racine_cree_les_taches_comme_avant(monkeypatch):
    rendu, state, config = _cloturer(monkeypatch, profondeur=0)
    assert "Câbler l'onglet export" in _titres()
    assert state.final_answer == "Travail livré."


def test_agent_racine_sans_les_listes_est_refuse(monkeypatch):
    rendu, state, config = _cloturer(monkeypatch, 0, terminees=None, restantes=None)
    assert config.get("_final_answer_refused"), rendu
