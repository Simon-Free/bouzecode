# [desc] Le plafond de tours enchaînés : ce qui arrête une boucle d'agent qu'aucun modèle n'arrête. [/desc]
"""`while True` ne sortait que si le MODÈLE le décidait.

Tous les compteurs qui bornaient la boucle — meta_only_cap, empty_turn_nudges,
consecutive_no_tool_recoveries, final_answer_nudges — comptent des tours IMPRODUCTIFS,
et un tour qui exécute un vrai outil les remet tous à zéro (loop.py L490-492). Un flux
qui rappelle indéfiniment un outil productif tenait donc la boucle ouverte pour toujours :
4 000 tours en 18,7 s, 13 331 messages, aucune sortie. C'est ce chemin-là qu'on borne ici.

Le plafond n'est pas une fin de travail : ces tests pinnent qu'il se voit — close_reason
FORCÉ, rien de livré, ticket non avancé, et une ligne sur stderr.
"""
from __future__ import annotations

from bouzecode.backend.agent.loop import run, MAX_AUTONOMOUS_TURNS
from bouzecode.backend.agent.providers import AssistantTurn, StreamStarted, TextChunk
from bouzecode.backend.agent.state import AgentState
from bouzecode.web_v2 import close_reasons

WRITE = {"name": "Write", "input": {"file_path": "/tmp/x.txt", "content": "x"}, "id": "w1"}


def _turn(text: str, tool_calls: list[dict]) -> AssistantTurn:
    return AssistantTurn(
        text=text, tool_calls=[dict(tc) for tc in tool_calls],
        in_tokens=1, out_tokens=1, cache_read_tokens=0, cache_creation_tokens=0,
    )


def _endless_stream(served: list, garde: int):
    """Un provider qui ne clôt JAMAIS : chaque tour rappelle un outil productif.

    `garde` est le filet du test lui-même. Si le plafond de production disparaît, ces
    tests doivent ÉCHOUER, pas pendre : un test qui pend pour signaler une boucle sans
    fin reproduit le bug qu'il surveille (c'est ce qui a coûté 26 min de suite ici).
    """
    def fake_stream(model, system, messages, tool_schemas, config):
        assert len(served) < garde, (
            f"{garde} tours joués sans que la boucle s'arrête : le plafond ne mord plus"
        )
        turn = _turn("Working.", [WRITE])
        served.append(turn)
        yield StreamStarted()
        yield TextChunk(turn.text)
        yield turn
    return fake_stream


def _install(monkeypatch, fake_stream):
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.get_tool_schemas", lambda: [])
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: s.messages)
    monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **k: None)
    monkeypatch.setattr("bouzecode.backend.agent.dag.execute_tool", lambda *a, **k: "ok")
    monkeypatch.setattr("bouzecode.backend.core.tool_registry.is_concurrent_safe", lambda n: True)


def _state_and_config(**overrides):
    state = AgentState()
    state.messages.append({"role": "user", "content": "fais la tâche"})
    state.user_loop_count = 1
    config = {"model": "test-model", "permission_mode": "accept-all",
              "recover_memory": False, "enforce_methodology": False}
    config.update(overrides)
    return state, config


def test_un_flux_qui_ne_clot_jamais_est_arrete_par_le_plafond(monkeypatch, capsys):
    """Sans ce plafond, cet appel ne rendrait jamais la main."""
    served: list = []
    _install(monkeypatch, _endless_stream(served, garde=20))
    state, config = _state_and_config(max_turns=5)

    list(run(None, state, config, "system prompt"))

    assert len(served) == 5, "la boucle doit s'arrêter EXACTEMENT au plafond"
    assert state.close_reason == "max_turns_exceeded"
    assert "5" in state.close_detail
    # Bruyant, pas silencieux : la trace existe aussi hors du JSON de session.
    assert "WARNING" in capsys.readouterr().err


def test_le_plafond_atteint_ne_prouve_aucune_livraison(monkeypatch):
    """La clôture est maîtrisée (la boucle a décidé), mais rien n'est livré et le
    ticket n'avance pas — sinon un agent emballé serait rapporté comme ayant fini."""
    assert "max_turns_exceeded" in close_reasons.CLOSURES
    assert not close_reasons.proves_delivery("max_turns_exceeded")
    assert close_reasons.is_controlled("max_turns_exceeded")


def test_le_budget_se_compte_par_appel_pas_sur_la_session(monkeypatch):
    """Ce qu'on borne est la traite AUTONOME. Un utilisateur qui dialogue longtemps
    relance un run() à chaque message : son budget doit repartir entier, sinon le
    garde-fou finirait par couper une conversation légitime au lieu d'un emballement."""
    served: list = []
    _install(monkeypatch, _endless_stream(served, garde=20))
    state, config = _state_and_config(max_turns=3)
    state.turn_count = 900  # 900 tours déjà consommés dans les appels précédents

    list(run(None, state, config, "system prompt"))

    assert len(served) == 3
    assert state.turn_count == 903


def test_une_conversation_qui_se_clot_seule_ne_touche_pas_au_plafond(monkeypatch):
    """Garde-fou du garde-fou : le plafond ne doit jamais être la raison d'une clôture
    normale. Un modèle qui répond sans tool call clôt bien avant."""
    scripted = [_turn("Working.", [WRITE]), _turn("Done.", [])]
    served: list = []

    def fake_stream(model, system, messages, tool_schemas, config):
        turn = scripted[len(served)]
        served.append(turn)
        yield StreamStarted()
        yield TextChunk(turn.text)
        yield turn

    _install(monkeypatch, fake_stream)
    state, config = _state_and_config(max_turns=3)

    list(run(None, state, config, "system prompt"))

    assert state.close_reason == "text_no_tools"
    assert state.close_detail == ""


def test_le_plafond_par_defaut_mord_sans_configuration(monkeypatch):
    """Aucun `max_turns` dans la config : c'est le défaut qui doit borner. Un seuil que
    seul un appelant averti active ne borde rien (cf. BOUZECODE_PARALYSIS_ABORT_AFTER,
    réglable et lu par personne, retiré le 2026-07-29)."""
    served: list = []
    _install(monkeypatch, _endless_stream(served, garde=2 * MAX_AUTONOMOUS_TURNS))
    state, config = _state_and_config()

    list(run(None, state, config, "system prompt"))

    assert len(served) == MAX_AUTONOMOUS_TURNS == 500
    assert state.close_reason == "max_turns_exceeded"
