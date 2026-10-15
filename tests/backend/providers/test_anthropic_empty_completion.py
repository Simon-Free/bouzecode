"""Le backend Anthropic doit rejouer une complétion dégénérée, et NE PAS rejouer un refus.

claude-opus-5 (modèle par défaut de bouzecode) sort par le backend `anthropic`
(registry.resolve_provider : tout `claude-*` sans "/" -> "anthropic"), pas par
OpenRouter. Le garde-fou anti-complétion-vide n'existait que côté openrouter_stream :
ces tests posent le même contrat ici.
"""
from types import SimpleNamespace

import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn

MODULE = "bouzecode.backend.agent.providers.backends.anthropic_stream"


def _usage(**kw):
    base = dict(input_tokens=100, output_tokens=0,
                cache_read_input_tokens=0, cache_creation_input_tokens=0)
    base.update(kw)
    return SimpleNamespace(**base)


def _events(text, stop_reason="end_turn", out_tokens=2):
    """Un flux Anthropic minimal : message_start, un text_delta, message_delta."""
    evs = [SimpleNamespace(type="message_start",
                           message=SimpleNamespace(usage=_usage()))]
    if text:
        evs.append(SimpleNamespace(type="content_block_delta", index=0,
                                   delta=SimpleNamespace(type="text_delta", text=text)))
    evs.append(SimpleNamespace(type="message_delta",
                               usage=_usage(output_tokens=out_tokens),
                               delta=SimpleNamespace(stop_reason=stop_reason)))
    return evs


class FakeStreamCtx:
    """Context manager renvoyé à la place du stream du SDK Anthropic."""

    def __init__(self, events):
        self._events = events

    def __enter__(self):
        return list(self._events)

    def __exit__(self, *exc):
        return False


class FakeClientFactory:
    """Compte les OUVERTURES de stream = le nombre de requêtes réellement émises."""

    def __init__(self, streams):
        self._streams = list(streams)
        self.call_count = 0

    def __call__(self, client, kwargs):
        self.call_count += 1
        return FakeStreamCtx(self._streams.pop(0))


@pytest.fixture(autouse=True)
def _diagnostics_dans_tmp(monkeypatch, tmp_path):
    """Les tours dégénérés écrivent un diagnostic JSON ; sans redirection il part
    dans le vrai ~/.bouzecode/diagnostics et le garde-fou production_isolation du
    projet fait (à juste titre) échouer le test. DIAGNOSTICS_DIR est lu à
    l'exécution, donc patcher l'attribut de module suffit."""
    monkeypatch.setattr(
        "bouzecode.backend.agent.providers.backends.completion_diagnostics.DIAGNOSTICS_DIR",
        tmp_path / "diagnostics",
    )


@pytest.fixture
def make_streams(monkeypatch):
    def _make(streams):
        factory = FakeClientFactory(streams)
        monkeypatch.setattr(f"{MODULE}.build_anthropic_client",
                            lambda api_key, base_url=None: object())
        monkeypatch.setattr(f"{MODULE}._create_anthropic_stream_with_retry", factory)
        return factory

    return _make


def _run(config=None):
    # tests/conftest.py installe un garde-fou autouse (_llm_network_guard) qui remplace
    # l'attribut `stream_anthropic` du module par un wrapper levant RuntimeError, pour
    # qu'aucun test n'atteigne le gateway réel par accident. Ce wrapper est posé avec
    # functools.wraps EXPRÈS pour rester transparent à l'introspection (cf. son
    # commentaire) : inspect.unwrap récupère la fonction réelle. On la prend donc
    # directement — le stream lui-même est faké (build_anthropic_client et
    # _create_anthropic_stream_with_retry sont monkeypatchés), donc rien ne part sur
    # le réseau, et le test reste déterministe (require_api_key() skipperait, lui,
    # en l'absence de credentials).
    import inspect
    from bouzecode.backend.agent.providers.backends import anthropic_stream as _mod
    stream_anthropic = inspect.unwrap(_mod.stream_anthropic)
    return list(stream_anthropic(
        api_key="sk-ant-fake", model="claude-opus-5", system="",
        messages=[{"role": "user", "content": "hi"}], tool_schemas=[],
        config=config or {},
    ))


def _final_turn(events) -> AssistantTurn:
    return next(e for e in events if isinstance(e, AssistantTurn))


def test_whitespace_only_completion_is_retried_then_succeeds(make_streams):
    """`text` truthy mais `text.strip()` vide : la boucle d'agent le voit vide. Sortie de
    50 tokens : ce n'est pas la signature d'un refus masqué, donc on rejoue."""
    factory = make_streams([_events("  ", out_tokens=50), _events("Hello")])
    turn = _final_turn(_run())
    assert factory.call_count == 2, "une complétion whitespace-only doit être rejouée"
    assert turn.text == "Hello"


def test_masked_refusal_is_not_retried_and_is_reported(make_streams, tmp_path):
    """Incident claude-opus-5 du 2026-09-28/29 : le proxy LiteLLM du gateway rend un refus
    du classifieur en `end_turn` + texte vide + quelques tokens (12/12 au rejeu, et
    `content_filter` sur sa route /v1/chat/completions). Rejouer est facturé pour rien."""
    import json

    factory = make_streams([_events("", out_tokens=7)] * 3)
    turn = _final_turn(_run())
    assert factory.call_count == 1, "un refus masqué ne doit JAMAIS être rejoué"
    assert turn.refusal and "LiteLLM" in turn.refusal
    dump = json.loads(sorted((tmp_path / "diagnostics").glob("*.json"))[-1].read_text("utf-8"))
    assert dump["reason"] == "masked_refusal"


def test_substantive_completion_is_not_retried(make_streams):
    factory = make_streams([_events("Hello")])
    turn = _final_turn(_run())
    assert factory.call_count == 1
    assert turn.text == "Hello"


def test_orphan_wrapper_only_is_not_retried_but_is_reported(make_streams):
    """Cas mesure en production (claude-opus-5, 2026-09-28) : le modele emet quelques
    tokens qui ne sont QU'un wrapper orphelin (`<tool_calls>` seul). parser.feed le
    retire du transcript (_drop_orphan_wrapper_suffix), donc `text` reste vide alors
    que la sortie a ete facturee.

    Rejouer la requete a l'identique redonne exactement la meme chose (mesure : 3
    tours x 3 tentatives, toutes vides) : c'est DETERMINISTE, pas un glitch reseau.
    Le retry est donc du gaspillage facture ; ce qu'il faut, c'est REMONTER le texte
    ecarte pour que la boucle d'agent nudge (seul geste qui debloque le modele).

    `xml_tools` force le mode XML : sans lui le test dependrait de
    BOUZECODE_ANTHROPIC_NATIVE_TOOLS / de l'endpoint du poste.
    """
    factory = make_streams([_events("<tool_calls>")])
    turn = _final_turn(_run({"xml_tools": True}))
    assert factory.call_count == 1, (
        "un wrapper orphelin est deterministe : rejouer la meme requete redonne le "
        "meme resultat, seul un message user frais debloque le modele"
    )
    assert turn.discarded_text, (
        "le texte emis puis ecarte par le protocole doit etre remonte, sinon la "
        "complétion passe pour vide sans qu'on sache ce que le modele a dit"
    )
    assert "tool_calls" in turn.discarded_text


def test_refusal_is_not_retried_and_is_reported(make_streams):
    """Un refus est déterministe : le rejouer à l'identique rendrait le même refus."""
    factory = make_streams([_events("", stop_reason="refusal")])
    turn = _final_turn(_run())
    assert factory.call_count == 1, "un refus ne doit JAMAIS être rejoué"
    assert turn.refusal, "le refus doit remonter sur l'AssistantTurn"
    assert turn.stop_reason == "refusal"


def test_gives_up_after_retry_budget(make_streams):
    # 50 tokens de sortie : hors signature du refus masqué, la relance s'applique.
    factory = make_streams([_events("", out_tokens=50)] * 3)
    turn = _final_turn(_run())
    assert factory.call_count == 3, "1 tentative + 2 retries, puis on rend la main"
    assert turn.text == ""


def _empty_thinking_events():
    """Le vrai cas claude-opus-5 (2026-09-28) : le gateway renvoie un bloc `thinking`
    au texte VIDE — content_block_start(type=thinking) puis content_block_stop, SANS
    aucun thinking_delta — puis message_delta end_turn. Le modele a ete facture
    (out_tokens>0) mais rien de substantiel n'est produit : chemin empty_completion.

    Ce flux ne contient AUCUN content_block_delta : c'est exactement la sequence
    que l'ancien event_trace laissait tomber (`events: []` dans le dump)."""
    return [
        SimpleNamespace(type="message_start",
                        message=SimpleNamespace(usage=_usage())),
        SimpleNamespace(type="content_block_start", index=0,
                        content_block=SimpleNamespace(type="thinking", thinking="")),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(type="message_delta",
                        usage=_usage(output_tokens=2),
                        delta=SimpleNamespace(stop_reason="end_turn")),
    ]


def test_dump_captures_all_event_types_not_just_deltas(make_streams, tmp_path):
    """La sortie EXACTE du gateway doit etre tracee : un tour degenere fait de blocs
    SANS content_block_delta (thinking vide) laissait `events: []` dans le diagnostic,
    donc on ne pouvait pas voir quel type de bloc etait arrive. Le dump doit enregistrer
    TOUS les etypes recus."""
    import json

    make_streams([_empty_thinking_events()] * 3)
    _run()

    dumps = sorted((tmp_path / "diagnostics").glob("completion-*.json"))
    assert dumps, "un tour degenere doit ecrire un diagnostic"
    record = json.loads(dumps[-1].read_text(encoding="utf-8"))
    events = record["events"]
    assert events, (
        "le diagnostic doit enregistrer les events du flux, meme sans content_block_delta "
        "(c'est le trou mesure sur claude-opus-5 : events: [])"
    )
    etypes = [e.get("type") for e in events]
    assert "message_start" in etypes
    assert "content_block_start" in etypes
    assert "message_delta" in etypes
    # Le type du bloc (thinking/text/tool_use) doit etre visible, c'est LUI qui
    # explique le tour vide.
    start = next(e for e in events if e.get("type") == "content_block_start")
    assert start.get("block_type") == "thinking"
