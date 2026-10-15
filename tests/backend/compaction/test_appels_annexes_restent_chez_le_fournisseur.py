# [desc] Les appels annexes (compaction, juge, résumé de réflexion) restent chez le fournisseur de la session [/desc]
"""Session DeepSeek (OpenRouter) sans clé Anthropic, constatée le 2026-09-24 : le juge et la
synthèse de compaction partaient sur ``DEFAULTS["model"]`` (Anthropic, figé à l'import) et
échouaient en 401 à chaque tour ; la note n'était plus compactée et a atteint 393 000
caractères. Ici on observe, au point d'interception officiel des appels au modèle, QUEL
modèle chaque appel annexe demande — et que la note est bel et bien compactée.
"""
from __future__ import annotations

import logging

import pytest

from bouzecode.backend.agent.providers import AssistantTurn, StreamStarted
from bouzecode.backend.agent.providers.registry import resolve_provider
from bouzecode.backend.agent.providers.side_model import modele_annexe
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor
from bouzecode.backend.agent.thinking_summary import summarize_overflow
from bouzecode.backend.context_manager.compact_judge import judge_and_prune
from bouzecode.backend.context_manager.compact_prose import SUMMARY_HEADER, compact_prose
from bouzecode.backend.core.config import DEFAULTS

SESSION_OPENROUTER = "deepseek-v4.1-flash"


class Espion:
    """Répond comme le modèle et note le modèle demandé par chaque appel."""

    def __init__(self, reponse: str, erreur: Exception | None = None):
        self.reponse, self.erreur, self.modeles = reponse, erreur, []

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            self.modeles.append(model)
            if self.erreur is not None:
                raise self.erreur
            yield StreamStarted()
            yield AssistantTurn(text=self.reponse, tool_calls=[], in_tokens=0,
                                out_tokens=0, stop_reason="end_turn")
        return stream


@pytest.fixture
def espion():
    def installer(reponse: str, erreur: Exception | None = None) -> Espion:
        spy = Espion(reponse, erreur)
        set_stream_interceptor(spy)
        return spy
    yield installer
    set_stream_interceptor(None)


class Session:
    def __init__(self):
        self.turn_count = 0
        self.compaction_log: list = []


class Etat:
    def __init__(self):
        self.notes: dict = {}


PROSE = [f"## Tour {n}\n" + f"Constat {n} : le scraper lit la page. " * 12 for n in range(1, 7)]
SNIPPET = ('## snippet: /p/scrape.py L1-3 — "entry"\n     1\tdef f():\n     2\t    return 1\n'
           "     3\t# fin")
NOTE = "\n".join(["## User\nScraper le Kangourou.", *PROSE, SNIPPET])
SYNTHESE = "Mission en cours : scraper le Kangourou.\n- page lue.\n- suite : figures."


def _config(model: str) -> dict:
    return {"model": model, "_state": Session(), "_depth": 0}


def _fournisseurs(spy: Espion) -> set[str]:
    return {resolve_provider(m)[0] for m in spy.modeles}


def test_la_synthese_de_compaction_reste_sur_openrouter_et_compacte_la_note(espion):
    spy = espion(SYNTHESE)
    note, retire = compact_prose(NOTE, Etat(), _config(SESSION_OPENROUTER))
    assert spy.modeles and _fournisseurs(spy) == {"openrouter"}, spy.modeles
    assert retire > 0 and SUMMARY_HEADER in note


def test_le_juge_de_compaction_reste_sur_openrouter(espion):
    spy = espion("DROP 1")
    judge_and_prune(NOTE, Etat(), _config(SESSION_OPENROUTER))
    assert spy.modeles and _fournisseurs(spy) == {"openrouter"}, spy.modeles


def test_le_resume_de_reflexion_reste_sur_openrouter(espion):
    spy = espion("conclusions")
    summarize_overflow("x" * 10_000, {"model": SESSION_OPENROUTER})
    assert _fournisseurs(spy) == {"openrouter"}, spy.modeles


def test_la_compaction_utilise_le_modele_de_la_session_quel_qu_il_soit(espion):
    spy = espion(SYNTHESE)
    compact_prose(NOTE, Etat(), _config("claude-haiku-4-5-20251001"))
    assert spy.modeles == ["claude-haiku-4-5-20251001"] * len(spy.modeles) and spy.modeles


def test_un_echec_d_authentification_n_est_signale_qu_une_fois(espion, caplog, monkeypatch):
    from bouzecode.backend.agent.providers import side_model
    monkeypatch.setattr(side_model, "_deja_signales", set())
    espion("", erreur=RuntimeError("Error code: 401 - Missing Authentication header"))
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            summarize_overflow("x" * 10_000, {"model": "claude-opus-5"})
    avertissements = [r for r in caplog.records if "sans clé" in r.getMessage()]
    assert len(avertissements) == 1


@pytest.mark.parametrize(("config", "attendu"), [
    ({"model": "deepseek-v4.1-flash"}, "deepseek-v4.1-flash"),
    ({"model": "claude-opus-5"}, "claude-opus-5"),     # un seul modèle : pas de bascule vers Sonnet
    ({"model": "glm-5.2", "side_model": "kimi-k3"}, "glm-5.2"),  # aucun second choix de modèle
])
def test_un_seul_modele_pour_tout(config, attendu):
    """Le modèle choisi une fois dans la config sert aussi à tous les appels annexes."""
    assert modele_annexe(config) == attendu
