# [desc] Defines message/streaming types, tool-name sanitization, and adaptive-thinking model checks. [/desc]
from __future__ import annotations
import re

from .registry import bare_model

_VALID_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_INVALID_TOOL_NAME_PLACEHOLDER = "_InvalidToolName"


def sanitize_tool_name(raw_name: str) -> tuple[str, str | None]:
    if raw_name and _VALID_TOOL_NAME_RE.match(raw_name):
        return raw_name, None
    return _INVALID_TOOL_NAME_PLACEHOLDER, raw_name


_ADAPTIVE_THINKING_MODELS = {
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-mythos-preview",
}


def _supports_adaptive_thinking(model: str) -> bool:
    return bare_model(model) in _ADAPTIVE_THINKING_MODELS


class StreamStarted:
    pass


class TextChunk:
    def __init__(self, text): self.text = text


class ThinkingChunk:
    def __init__(self, text): self.text = text


class StreamRestart:
    """Yielded when the backend REPLAYS the whole request after a mid-stream drop.

    Everything streamed by the aborted attempt (thinking, text, tool calls) is void:
    the server regenerates from scratch. Without this signal the consumer kept both
    attempts, and the saved assistant message carried its reasoning twice (« réflexions
    en double », session 3db4403a)."""
    pass


class ToolCallParsed:
    """Yielded mid-stream when the XML parser finishes a tool_use block."""
    def __init__(self, name: str, inputs: dict, tool_id: str):
        self.name = name
        self.inputs = inputs
        self.tool_id = tool_id


class ToolIdRemap:
    """Yielded after stream ends when tool IDs were remapped by uniquify."""
    def __init__(self, remap: dict[str, str]):
        self.remap = remap


class SystemPayload:
    """Yielded before streaming starts — carries the system_blocks sent to the API,
    plus (in native function-calling mode) the OpenAI-format tools list. `tools` is
    None when the XML tool protocol is used (the Anthropic path, or forced XML)."""
    def __init__(self, system_blocks: list, tools: list | None = None,
                 messages: list | None = None, empreinte: dict | None = None):
        self.system_blocks = system_blocks
        self.tools = tools
        # The EXACT wire messages sent to the API this turn, AFTER dispatch's
        # wire-only mutations (audit note, working-memory notes, big-context
        # reminder). None when the backend does not expose them; the loop then
        # falls back to the pre-mutation messages for the payload dump.
        self.messages = messages
        # Empreintes du préfixe (backends/empreinte.py), journalisées avec l'appel.
        self.empreinte = empreinte


class UsageSnapshot:
    """Token usage as known MID-stream.

    Anthropic sends `usage.input_tokens` / cache counters in `message_start`
    and `output_tokens` in `message_delta`, long before the stream ends. This
    event carries that snapshot to the agent loop so that a stream which
    CRASHES (or is interrupted) before its final AssistantTurn still reports
    the tokens it really consumed instead of a hardcoded 0.
    """

    def __init__(self, in_tokens=0, out_tokens=0,
                 cache_read_tokens=0, cache_creation_tokens=0):
        self.in_tokens = in_tokens
        self.out_tokens = out_tokens
        self.cache_read_tokens = cache_read_tokens
        self.cache_creation_tokens = cache_creation_tokens


class AssistantTurn:
    def __init__(self, text, tool_calls, in_tokens, out_tokens,
                 cache_read_tokens=0, cache_creation_tokens=0, stop_reason=None):
        self.text = text
        self.tool_calls = tool_calls
        self.in_tokens = in_tokens
        self.out_tokens = out_tokens
        self.stop_reason = stop_reason
        self.cache_read_tokens = cache_read_tokens
        self.cache_creation_tokens = cache_creation_tokens
        # Vrai quand message_delta n'est jamais arrivé : out_tokens est alors estimé
        # depuis le texte reçu (cf. anthropic_stream), pas lu dans l'usage de l'API.
        self.out_tokens_estimated = False
        # Fournisseur qui a réellement servi (champ `provider` des réponses OpenRouter).
        self.provider = ""
        # Texte que le modèle a bel et bien émis (et fait facturer) mais que le
        # protocole a écarté du transcript — typiquement un wrapper <tool_calls>
        # orphelin. Sans ça le tour passe pour vide sans qu'on sache ce qu'il a dit.
        self.discarded_text = None
        # Tentatives facturées puis écartées avant ce tour (refus content_filter relancé,
        # coupure en vol rejouée) : une entrée par tentative, journalisée dans turns.jsonl.
        self.tentatives_ecartees: list[dict] = []
        # Refus EXPLICITE du modèle (champ `refusal` d'OpenAI, ou finish_reason
        # "content_filter") : distingue un refus DÉTERMINISTE — que relancer à
        # l'identique ne débloquera jamais — d'une complétion vide accidentelle
        # (glitch de provider), qui elle vaut un retry. Texte du refus si fourni,
        # True si seul le finish_reason l'indique, None sinon.
        self.refusal = None


def tentative_ecartee(motif: str, in_tokens: int, out_tokens: int, cache_read_tokens: int,
                      cache_creation_tokens: int) -> dict:
    """Une tentative facturée puis écartée, telle que turns.jsonl la journalise."""
    return {"motif": motif, "in_tokens": in_tokens, "out_tokens": out_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens}
