# [desc] Une image n'entre plus jamais dans un résultat d'outil (Read, capture MCP) : un fichier + une ligne ; ImageQuestion la montre à un modèle dans un appel annexe sans note ni prompt d'agent. [/desc]
"""Images hors du contexte (rapport docs/reduction_tokens §4, correctifs point 6).

- `Read` d'un PNG rendait `__BOUZE_IMAGE__:<mime>:<base64>`, envoyé en TEXTE sur OpenRouter ;
- une capture chrome-devtools MCP partait en `str(dict)` : tout le base64 en texte.
Désormais le résultat est une ligne `[… : <chemin>, WxH, N ko. Pour l'examiner :
ImageQuestion(...)]`, et `ImageQuestion` fait regarder l'image par un appel annexe.
"""
from __future__ import annotations

import base64
import json
import re
import struct
import threading
import zlib
from pathlib import Path

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM


def _png(w: int, h: int) -> bytes:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


_METH = '<tool_use name="Methodology" id="m1"><param name="content">regarder la figure</param></tool_use>'


def test_read_d_une_image_rend_une_ligne_sans_base64(tmp_path):
    figure = tmp_path / "figure.png"
    figure.write_bytes(_png(7, 5))
    mock = MockLLM([
        f'{_METH}<tool_use name="Read" id="r1"><param name="file_path">{figure}</param></tool_use>',
        "Vu.",
    ])

    result = bouzecode(["lis la figure"], mock_llm=mock, config_overrides={"enforce_tests": False})

    lu = next(m["content"] for m in result.messages if m.get("role") == "tool" and m.get("name") == "Read")
    assert lu.startswith(f"[image : {figure}, 7x5, 1 ko.")
    assert f'ImageQuestion(paths=["{figure}"]' in lu
    assert base64.b64encode(figure.read_bytes()).decode()[:40] not in lu
    assert "__BOUZE_IMAGE__" not in lu


class _FauxTransport:
    alive = True

    def __init__(self, reponse: dict) -> None:
        self.reponse = reponse

    def request(self, method: str, params: dict) -> dict:
        return self.reponse


def test_capture_mcp_enregistree_dans_un_fichier_et_rendue_en_une_ligne(monkeypatch):
    from bouzecode.backend.chrome_devtools import launcher

    png = _png(12, 9)
    reponse = {"content": [
        {"type": "text", "text": "Took a screenshot of the current page."},
        {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"},
    ]}
    monkeypatch.setitem(launcher._TRANSPORTS, threading.get_ident(), _FauxTransport(reponse))

    sortie = launcher._make_tool_func("take_screenshot")({}, {})

    assert "Took a screenshot" in sortie
    ligne = re.search(r"\[capture enregistrée : (\S+), 12x9, 1 ko\. Pour l'examiner : "
                      r'ImageQuestion\(paths=\["\1"\], question="…"\)\]', sortie)
    assert ligne, sortie
    assert Path(ligne.group(1)).read_bytes() == png
    assert base64.b64encode(png).decode()[:40] not in sortie


def test_take_screenshot_decrit_le_devenir_de_l_image():
    from bouzecode.backend.chrome_devtools.launcher import _COMPLEMENTS

    assert "ImageQuestion" in _COMPLEMENTS["take_screenshot"]
    assert "take_snapshot" in _COMPLEMENTS["take_screenshot"]


class _FluxOpenRouter:
    ok, status_code, encoding, text = True, 200, "utf-8", ""

    def iter_lines(self, decode_unicode=False):
        yield ('data: {"choices":[{"delta":{"content":"NON : trois barres."},"finish_reason":"stop"}],'
               '"usage":{"prompt_tokens":812,"completion_tokens":9}}')
        yield "data: [DONE]"


class _SessionOpenRouter:
    """Seule couture : la session HTTP que `dispatch` → `stream_openrouter` construit."""
    def __init__(self) -> None:
        self.envois: list[dict] = []

    def post(self, url, **kw):
        self.envois.append(kw["json"])
        return _FluxOpenRouter()


def _espion_de_dispatch(monkeypatch) -> list:
    """Compte les appels qui passent par la voie commune (`loop_turn.stream` = dispatch)."""
    import bouzecode.backend.agent.loop_turn as lt
    appels, reel = [], lt.stream

    def espion(**kw):
        appels.append(kw)
        yield from reel(**kw)
    monkeypatch.setattr(lt, "stream", espion)
    return appels


def _figure(tmp_path, nom="carre.png"):
    figure = tmp_path / nom
    figure.write_bytes(_png(4, 4))
    return figure


def test_image_question_anthropic_par_dispatch_bloc_image_sans_note_ni_prompt(tmp_path, monkeypatch):
    """Vrai pipeline (dispatch → client Anthropic → faux serveur SSE) : un bloc image + la
    question, un system court, ni note Methodology ni prompt d'agent, raisonnement coupé."""
    from tests import cache_conversation_helpers as cch
    from tests.mock_anthropic_server import start_mock_anthropic
    from bouzecode.backend.core.tool_registry import execute_tool
    from bouzecode.backend.context_manager import ContextState

    url, app = start_mock_anthropic(["OUI : un carré rouge occupe toute l'image."])
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(cch, "LIVE_API_ALLOWED", True)  # faux serveur local
    appels = _espion_de_dispatch(monkeypatch)
    figure = _figure(tmp_path)
    note = ContextState()
    note.notes["methodology"] = "NOTE SECRETE DE L'AGENT"

    sortie = execute_tool("ImageQuestion", {"paths": [str(figure)], "question": "Est-ce un carré rouge ?"},
                          {"model": "claude-opus-5", "_context_state": note,
                           "_system_prompt": "PROMPT DE L'AGENT"})

    assert sortie == f"{figure} : OUI : un carré rouge occupe toute l'image."
    assert len(appels) == 1 and appels[0]["config"]["_context_state"] is None
    corps = app.recorded_calls[-1]
    brut = json.dumps(corps, ensure_ascii=False)
    assert "NOTE SECRETE" not in brut and "PROMPT DE L'AGENT" not in brut
    assert "RAPPEL" not in brut and not corps.get("tools")
    assert corps["system"][0]["text"].startswith("Tu examines une image") and corps["max_tokens"] >= 2048
    assert corps.get("thinking", {"type": "disabled"}) == {"type": "disabled"}
    image, question = corps["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == figure.read_bytes()
    assert question == {"type": "text", "text": "Est-ce un carré rouge ?"}


def _question_openrouter(tmp_path, monkeypatch, **config):
    from bouzecode.backend.agent.providers.backends import openrouter_stream
    from bouzecode.backend.agent.state import AgentState
    from bouzecode.backend.core.tool_registry import execute_tool

    session = _SessionOpenRouter()
    monkeypatch.setattr(openrouter_stream, "_build_session", lambda: session)
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    figure = _figure(tmp_path, "barres.png")
    state = AgentState()
    sortie = execute_tool("ImageQuestion", {"paths": [str(figure)], "question": "Quatre barres ?"},
                          {"model": "deepseek-v4-flash", "_state": state, "_main_config_id": 0, **config})
    return sortie, session.envois[-1], state, figure


def _partie_image(figure) -> dict:
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(figure.read_bytes()).decode()}}


def test_image_question_openrouter_natif_image_url_et_vision_model(tmp_path, monkeypatch):
    appels = _espion_de_dispatch(monkeypatch)

    sortie, envoi, state, figure = _question_openrouter(
        tmp_path, monkeypatch, vision_model="deepseek-v4.1-flash")

    assert sortie == f"{figure} : NON : trois barres."
    assert len(appels) == 1, "l'appel passe par dispatch"
    assert envoi["model"] == "deepseek/deepseek-v4.1-flash", "vision_model prime sur le modèle de session"
    assert envoi["max_tokens"] >= 2048 and "reasoning" not in envoi
    assert envoi["messages"][1]["content"] == [_partie_image(figure), {"type": "text", "text": "Quatre barres ?"}]
    trace = state.compaction_log[-1]
    assert (trace["label"], trace["api_output_tokens"]) == ("image_question", 9), \
        "usage compté par dispatch comme tout appel annexe"


def test_image_question_openai_protocole_xml_garde_l_image(tmp_path, monkeypatch):
    """Chemin OpenAI sans outils natifs (`_messages_to_openai`) : l'image n'est plus aplatie."""
    _sortie, envoi, _state, figure = _question_openrouter(tmp_path, monkeypatch, xml_tools=True)

    assert envoi["messages"][1]["content"] == [_partie_image(figure), {"type": "text", "text": "Quatre barres ?"}]


def test_image_question_ne_construit_aucun_client_http():
    """Tous les appels LLM passent par la voie commune : pas de client ni de requête ici."""
    import inspect
    from bouzecode.backend.tools import image_question

    source = inspect.getsource(image_question)
    for interdit in ("build_anthropic_client", "_build_session", "build_plain_session",
                     "requests", "httpx", ".post(", "Authorization"):
        assert interdit not in source, interdit


def test_image_question_sur_quinze_images_repond_pour_chacune_sans_refus(tmp_path, monkeypatch):
    """Quinze figures en un appel (essai du 2026-09-25) : une réponse par image, dans l'ordre."""
    from bouzecode.backend.agent.providers.backends import openrouter_stream
    from bouzecode.backend.core.tool_registry import execute_tool

    session = _SessionOpenRouter()
    monkeypatch.setattr(openrouter_stream, "_build_session", lambda: session)
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    figures = [_figure(tmp_path, f"q{i:02d}.png") for i in range(1, 16)]

    sortie = execute_tool("ImageQuestion", {"paths": [str(f) for f in figures],
                                            "question": "Quatre barres ?"},
                          {"model": "deepseek-v4-flash"})

    assert not sortie.startswith("Error"), sortie
    assert sortie.splitlines() == [f"{f} : NON : trois barres." for f in figures]
    assert len(session.envois) == 15
