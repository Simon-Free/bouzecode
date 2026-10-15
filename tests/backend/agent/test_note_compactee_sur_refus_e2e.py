# [desc] Sur refus content_filter, le tour est d'abord rejoué avec la note compactée sur le même modèle ; encore refusé, il glisse sur la marche suivante avec la note compactée. Une tentative par variante et par tour. [/desc]
"""Session 28738fd0 (2026-10-12, gateway préprod) : le refus est déterministe pour un contexte
donné et vient de la note Methodology accumulée ; la note compactée (## User, snippets et
deux derniers ### Tn gardés) le fait tomber, 12/12 -> 0/10. Chaque modèle est scripté par
l'intercepteur de flux officiel ; la boucle bouzecode, la compaction et le repli sont le vrai code."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_harness import bouzecode  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

from bouzecode.backend.context_manager.methodology import reconstruct_methodology_from_timeline  # noqa: E402
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE, resolve_context_state  # noqa: E402
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor  # noqa: E402

OPUS_5_5, SONNET_5_5, OPUS_5 = "claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5"
REFUSE = ("", "content_filter")
CLES = {"model": OPUS_5_5, "gateway_preprod_api_key": "cle-de-test", "anthropic_api_key": "cle-de-test"}
SNIPPET = ('<tool_use name="Snippet" id="s1"><param name="file_path">{chemin}</param>'
           '<param name="ranges">[[1,2]]</param><param name="label">en-tete</param></tool_use>')


def productif(n: int, avec_snippet: str = "") -> str:
    """Un tour qui note son avancement (### Tn posé par le harnais) puis lance une commande."""
    return (f'<tool_use name="Methodology" id="m{n}"><param name="content">etape {n} : '
            f'avancement numero {n} du travail demande</param></tool_use>'
            + (SNIPPET.format(chemin=avec_snippet) if avec_snippet else "")
            + f'<tool_use name="Bash" id="b{n}"><param name="command">echo {n}</param></tool_use>')


@pytest.fixture(autouse=True)
def _isolation(monkeypatch, tmp_path):
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", tmp_path)
    monkeypatch.delenv("BOUZECODE_REFUSAL_FALLBACK", raising=False)
    monkeypatch.delenv("BOUZECODE_ALLOWED_PROVIDERS", raising=False)
    yield
    set_stream_interceptor(None)


def _par_modele(scripts: dict[str, list]) -> list[tuple[str, str]]:
    """Chaque modèle répond depuis sa file ; rend (modèle, note envoyée) pour chaque appel."""
    mocks = {modele: MockLLM(reponses) for modele, reponses in scripts.items()}
    appels: list[tuple[str, str]] = []

    def stream(model, system, messages, tool_schemas, config):
        if (config or {}).get("_depth", 0) == 0:
            note = resolve_context_state(config).notes.get(METHODOLOGY_NOTE, "")
            appels.append((model, note))
        yield from mocks[model].stream(model, system, messages, tool_schemas, config)

    set_stream_interceptor(lambda _raw: stream)
    return appels


def _evenements(result, nom: str) -> list[dict]:
    return [e for e in result.state.compaction_log if e.get("event") == nom]


def test_le_rejeu_a_note_compactee_repond_sur_le_meme_modele(tmp_path):
    """opus-5-5 refuse le tour 4 ; rejoué avec la note compactée, il répond : pas de repli."""
    source = tmp_path / "source_gardee.py"
    source.write_text("PREMIERE = 1\nSECONDE = 2\n", encoding="utf-8")
    appels = _par_modele({
        OPUS_5_5: [productif(1, avec_snippet=source.as_posix()), productif(2), productif(3),
                   REFUSE, productif(4), "Fini."],
        SONNET_5_5: [], OPUS_5: [],
    })

    result = bouzecode(["fais le travail"], mock_llm=MockLLM([]),
                  config_overrides=dict(CLES))

    assert [modele for modele, _ in appels] == [OPUS_5_5] * 6
    note_refusee, note_rejouee = appels[3][1], appels[4][1]
    assert "### T1" in note_refusee and "### T1" not in note_rejouee
    assert "## User" in note_rejouee, "la demande de l'utilisateur reste"
    assert "## snippet: " in note_rejouee and "PREMIERE = 1" in note_rejouee, "le snippet reste"
    assert "### T2" in note_rejouee and "### T3" in note_rejouee, "les deux derniers tours restent"
    assert "etape 1 :" not in note_rejouee
    assert not _evenements(result, "refusal_fallback")
    [rejeu] = _evenements(result, "refus_note_compactee")
    assert (rejeu["model"], rejeu["refused"], rejeu["tours_retires"]) == (OPUS_5_5, False, [1])
    tour_4 = [e.get("model") for e in _evenements(result, "llm_call") if e.get("turn") == 4]
    assert len(tour_4) == 2 and tour_4[0] == OPUS_5_5, "la tentative refusée est comptée"
    assert result.state.close_reason != "content_refusal"
    assert not result.state.repli_collant


def test_compacte_encore_refuse_le_tour_glisse_sur_la_marche_suivante_avec_la_note_compactee():
    """Refus, rejeu compacté refusé : sonnet-5-5 reçoit la note compactée, et la compaction
    n'est pas retentée (une tentative par variante et par tour)."""
    appels = _par_modele({
        OPUS_5_5: [productif(1), productif(2), productif(3), REFUSE, REFUSE],
        SONNET_5_5: [productif(4), "Fini."], OPUS_5: [],
    })

    result = bouzecode(["fais le travail"], mock_llm=MockLLM([]),
                  config_overrides=dict(CLES))

    assert [modele for modele, _ in appels] == [OPUS_5_5] * 5 + [SONNET_5_5] * 2
    note_du_repli = appels[5][1]
    assert "### T1" not in note_du_repli and "### T3" in note_du_repli
    assert [e["refused"] for e in _evenements(result, "refus_note_compactee")] == [True]
    assert [(e["model"], e["fallback"]) for e in _evenements(result, "refusal_fallback")] \
        == [(OPUS_5_5, SONNET_5_5)]
    tour_4 = [e.get("model") for e in _evenements(result, "llm_call") if e.get("turn") == 4]
    assert tour_4 == [OPUS_5_5, OPUS_5_5, SONNET_5_5]
    assert result.state.repli_collant["repli"] == SONNET_5_5


def test_rien_a_compacter_pas_de_rejeu_et_la_chaine_reprend():
    """Au tour 1 la note n'a aucun ### Tn ancien : rejouer serait le même payload."""
    appels = _par_modele({OPUS_5_5: [REFUSE], SONNET_5_5: [productif(1), "Fini."], OPUS_5: []})

    result = bouzecode(["fais le travail"], mock_llm=MockLLM([]),
                  config_overrides=dict(CLES))

    assert [modele for modele, _ in appels] == [OPUS_5_5, SONNET_5_5, SONNET_5_5]
    assert not _evenements(result, "refus_note_compactee")


def test_les_blocs_retires_restent_dans_la_timeline():
    """La note compactée devient l'état de la session ; la timeline la reconstruit, et ses
    deltas antérieurs gardent les tours retirés."""
    _par_modele({OPUS_5_5: [productif(1), productif(2), productif(3), REFUSE, productif(4),
                            "Fini."], SONNET_5_5: [], OPUS_5: []})

    result = bouzecode(["fais le travail"], mock_llm=MockLLM([]),
                  config_overrides=dict(CLES))

    note = result.state.context_state.notes[METHODOLOGY_NOTE]
    assert "etape 1 :" not in note and "etape 4 :" in note
    assert reconstruct_methodology_from_timeline(result.state.notes_timeline) == note
    ajoutes = [b for e in result.state.notes_timeline for b in e["delta"]["added"]]
    assert any("etape 1 :" in b for b in ajoutes)
