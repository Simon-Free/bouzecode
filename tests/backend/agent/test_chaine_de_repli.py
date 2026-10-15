# [desc] Chaîne de repli sur refus : opus-5-5 -> sonnet-5-5 -> opus-5, une tentative par marche et par tour, collage sur la dernière marche qui a répondu, fermeture en content_refusal une fois la chaîne épuisée, aucune boucle. [/desc]
"""Session 28738fd0 (2026-10-12, bouzecode 3.5.120) : opus-5-5 refuse au tour 5, sonnet-5-5 sert
les tours 6 à 10 puis refuse aux tours 11 et 12 — le run fermait en content_refusal sans
tenter claude-opus-5. Chaque modèle est scripté séparément par l'intercepteur de flux
officiel ; la boucle bouzecode, le repli et le collage sont le vrai code."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_harness import bouzecode  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

from bouzecode.backend.agent.providers import registry  # noqa: E402
from bouzecode.backend.agent.refusal_fallback import MAX_MARCHES_DE_REPLI, refusal_chain  # noqa: E402
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor  # noqa: E402

OPUS_5_5, SONNET_5_5, OPUS_5 = "claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5"
PRODUCTIF = ('<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
             '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>')
REFUSE = ("", "content_filter")
CLES = {"model": OPUS_5_5, "gateway_preprod_api_key": "cle-de-test", "anthropic_api_key": "cle-de-test"}


@pytest.fixture(autouse=True)
def _isolation(monkeypatch, tmp_path):
    """Dumps sous tmp_path ; aucune surcharge de repli héritée ; intercepteur retiré."""
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", tmp_path)
    monkeypatch.delenv("BOUZECODE_REFUSAL_FALLBACK", raising=False)
    monkeypatch.delenv("BOUZECODE_ALLOWED_PROVIDERS", raising=False)
    yield
    set_stream_interceptor(None)


def _par_modele(scripts: dict[str, list]) -> list[str]:
    """Chaque modèle répond depuis sa propre file ; rend la liste ordonnée des appels."""
    mocks = {modele: MockLLM(reponses) for modele, reponses in scripts.items()}
    appels: list[str] = []

    def stream(model, system, messages, tool_schemas, config):
        if (config or {}).get("_depth", 0) == 0:
            appels.append(model)
        yield from mocks[model].stream(model, system, messages, tool_schemas, config)

    set_stream_interceptor(lambda _raw: stream)
    return appels


def _evenements(result, nom: str) -> list[dict]:
    return [e for e in result.state.compaction_log if e.get("event") == nom]


def test_opus_5_5_refuse_et_sonnet_5_5_repond():
    appels = _par_modele({OPUS_5_5: [REFUSE], SONNET_5_5: [PRODUCTIF, "Fini."], OPUS_5: []})

    result = bouzecode(["fais le travail"], mock_llm=MockLLM([]), mock_tools=True,
                  config_overrides=dict(CLES))

    assert appels == [OPUS_5_5, SONNET_5_5, SONNET_5_5]
    assert result.state.close_reason != "content_refusal"
    assert result.state.repli_collant["repli"] == SONNET_5_5


def test_sonnet_colle_refuse_et_opus_5_repond_sans_retenter_opus_5_5():
    """opus-5-5 aurait répondu plus tard, mais sonnet-5-5 est collé : il n'est pas retenté.
    Quand sonnet refuse, le tour glisse sur opus-5, où le collage se déplace."""
    appels = _par_modele({
        OPUS_5_5: [REFUSE, PRODUCTIF, "Fini."],
        SONNET_5_5: [PRODUCTIF, "Fini.", "Bonjour.", REFUSE],
        OPUS_5: [PRODUCTIF, "Fini.", "Encore."],
    })

    result = bouzecode(["fais le travail", "salut", "continue", "et ensuite"], mock_llm=MockLLM([]),
                  mock_tools=True, config_overrides=dict(CLES))

    assert appels == [OPUS_5_5, SONNET_5_5, SONNET_5_5, SONNET_5_5,
                      SONNET_5_5, OPUS_5, OPUS_5, OPUS_5]
    assert result.state.close_reason != "content_refusal"
    assert result.state.repli_collant["repli"] == OPUS_5
    rejeux = [(e["model"], e["fallback"], e["fallback_refused"], e["marche"])
              for e in _evenements(result, "refusal_fallback")]
    assert rejeux == [(OPUS_5_5, SONNET_5_5, False, 1), (SONNET_5_5, OPUS_5, False, 2)]
    assert [e["fallback"] for e in _evenements(result, "repli_collant_arme")] == [SONNET_5_5, OPUS_5]


def test_les_trois_refusent_et_le_run_ferme_en_content_refusal():
    appels = _par_modele({OPUS_5_5: [REFUSE], SONNET_5_5: [REFUSE], OPUS_5: [REFUSE, *([""] * 5)]})

    result = bouzecode(["fais le travail"], mock_llm=MockLLM([]), mock_tools=True,
                  config_overrides=dict(CLES))

    assert appels == [OPUS_5_5, SONNET_5_5, OPUS_5]  # une tentative par marche
    assert result.state.close_reason == "content_refusal"
    assert [e["fallback_refused"] for e in _evenements(result, "refusal_fallback")] == [True, True]
    tour_un = [e["model"] for e in _evenements(result, "llm_call") if e.get("turn") == 1]
    assert tour_un == [OPUS_5_5, SONNET_5_5, OPUS_5]  # chaque tentative facturée est comptée
    assert not result.state.repli_collant


def test_chaine_epuisee_depuis_le_collage_le_message_suivant_repart_de_la_tete():
    """Cas du tour 12 : sonnet collé refuse, opus-5 aussi -> content_refusal et collage
    levé ; le message suivant de l'utilisateur repart d'opus-5-5."""
    appels = _par_modele({
        OPUS_5_5: [REFUSE, PRODUCTIF, "Fini."],
        SONNET_5_5: [PRODUCTIF, "Fini.", REFUSE],
        OPUS_5: [REFUSE],
    })

    result = bouzecode(["fais le travail", "continue", "reprends"], mock_llm=MockLLM([]),
                  mock_tools=True, config_overrides=dict(CLES))

    assert appels == [OPUS_5_5, SONNET_5_5, SONNET_5_5,
                      SONNET_5_5, OPUS_5,
                      OPUS_5_5, OPUS_5_5]
    assert [e["raison"] for e in _evenements(result, "repli_collant_leve")] == ["chaine epuisee"]
    assert not result.state.repli_collant


def test_une_table_cyclique_ne_boucle_pas(monkeypatch):
    monkeypatch.setitem(registry.REFUSAL_FALLBACK, OPUS_5, OPUS_5_5)
    appels = _par_modele({OPUS_5_5: [REFUSE], SONNET_5_5: [REFUSE], OPUS_5: [REFUSE, *([""] * 5)]})

    result = bouzecode(["fais le travail"], mock_llm=MockLLM([]), mock_tools=True,
                  config_overrides=dict(CLES))

    assert appels == [OPUS_5_5, SONNET_5_5, OPUS_5]
    assert result.state.close_reason == "content_refusal"
    assert refusal_chain(OPUS_5, CLES) == [OPUS_5_5, SONNET_5_5]


def test_la_chaine_est_bornee_et_sans_doublon():
    surcharge = {**CLES, "refusal_fallback": [OPUS_5_5, SONNET_5_5, SONNET_5_5, OPUS_5,
                                              "claude-opus-4-8", "claude-sonnet-5"]}
    chaine = refusal_chain(OPUS_5_5, surcharge)
    assert chaine == [SONNET_5_5, OPUS_5, "claude-opus-4-8"]
    assert len(chaine) == MAX_MARCHES_DE_REPLI


def test_une_surcharge_d_un_seul_modele_garde_l_ancien_comportement():
    assert refusal_chain(OPUS_5_5, {**CLES, "refusal_fallback": OPUS_5}) == [OPUS_5]
    assert refusal_chain(OPUS_5_5, {**CLES, "refusal_fallback": f"{OPUS_5}, {SONNET_5_5}"}) \
        == [OPUS_5, SONNET_5_5]
    assert refusal_chain(OPUS_5_5, {**CLES, "refusal_fallback": "none"}) == []


def test_une_marche_sans_cle_est_sautee(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY_PP", raising=False)
    sans_gateway_preprod = {"model": OPUS_5_5, "anthropic_api_key": "cle-de-test"}
    assert refusal_chain(OPUS_5_5, sans_gateway_preprod) == [OPUS_5]
