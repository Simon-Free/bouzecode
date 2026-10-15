from bouzecode.backend.agent.providers.registry import calc_cost
from bouzecode.ui.cost_label import session_cost_label


def test_priced_model_shows_dollars_matching_calc_cost():
    model = "claude-sonnet-4-5"
    label = session_cost_label(model, 37_933 + 50_509, 6_683, 478_270, 50_509)
    expected = calc_cost(model, 37_933 + 50_509, 6_683, 478_270, 50_509)
    assert expected > 0
    assert label == f"${expected:,.4f}"


def test_unpriced_model_says_so():
    assert session_cost_label("totally-unknown-model-xyz", 1000, 10) == \
        "cost n/a (totally-unknown-model-xyz unpriced)"


def test_missing_model():
    assert "unpriced" in session_cost_label(None, 1000, 10)


def _state(entree, sortie):
    from types import SimpleNamespace
    return SimpleNamespace(messages=[], total_input_tokens=entree, total_output_tokens=sortie,
                           total_cache_read_tokens=0, total_cache_creation_tokens=0)


def test_total_session_label_adds_sub_agents_cost():
    from bouzecode.backend.multi_agent.en_process.fiche import FicheAgent
    from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
    from bouzecode.ui.cost_label import total_session_label

    model = "claude-sonnet-4-5"
    registre = RegistreAgents()
    registre.declarer_principal(_state(1000, 100), model)
    registre.ajouter(FicheAgent(id="a1", modele=model, state=_state(20_000, 2_000)))

    label = total_session_label(model, 1000, 100, 0, 0, registre)
    main = calc_cost(model, 1000, 100, 0, 0)
    total = main + calc_cost(model, 20_000, 2_000, 0, 0)
    assert f"main ${main:,.4f}" in label
    assert f"total ${total:,.4f}" in label
    assert "partiel" not in label


def test_total_session_label_without_sub_agents_is_main_cost():
    from bouzecode.ui.cost_label import total_session_label
    model = "claude-sonnet-4-5"
    assert total_session_label(model, 1000, 100, 0, 0, None) == session_cost_label(model, 1000, 100, 0, 0)


def test_total_session_label_flags_unpriced_sub_agent():
    from bouzecode.backend.multi_agent.en_process.fiche import FicheAgent
    from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
    from bouzecode.ui.cost_label import total_session_label

    model = "claude-sonnet-4-5"
    registre = RegistreAgents()
    registre.ajouter(FicheAgent(id="a1", modele="totally-unknown-model-xyz", state=_state(5, 5)))
    assert "partiel" in total_session_label(model, 1000, 100, 0, 0, registre)
