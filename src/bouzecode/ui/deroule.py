# [desc] Rendu incremental d'une conversation : rejeu (/history, bascule de vue) et suivi en direct d'un sous-agent passent par le MEME rendu, message par message, appel par appel. [/desc]
"""`DerouleConversation` : curseur de rendu sur une liste de messages qui grandit.

Le rejeu (`replay_messages`) et le suivi en direct d'un sous-agent (`EcranAgents`) en
partagent une instance : le rendu apres une bascule de vue est donc indiscernable du rejeu.
Un appel d'outil s'annonce (`print_tool_start`) des que son message arrive ; son resultat
(`print_tool_end`), apparie par `tool_call_id`, s'imprime quand il arrive — souvent un ou
plusieurs ticks plus tard. Les appels suivants du meme message attendent leur tour : l'ordre
imprime est celui du rejeu.

Texte assistant : rendu STATIQUE (Markdown imprime une fois), pas `stream_text` — son
`rich.Live` corromprait l'invite quand le suivi imprime depuis son thread, sous
`patch_stdout`. Le dernier cadre d'un `Live` est ce meme rendu : l'aspect est identique.
"""
from __future__ import annotations

from .ansi import clr
from .rendering import _make_renderable, safe_print
from .replay import (_collect_tool_results, _is_pure_tool_result_message, _normalize_text,
                     _normalize_tool_calls, _strip_tool_xml)
from .tool_display import print_tool_end, print_tool_start


class DerouleConversation:
    def __init__(self) -> None:
        self._curseur = 0            # message en cours de rendu
        self._appel = 0              # prochain appel d'outil de ce message
        self._entete_imprimee = False
        self._appel_annonce = False  # print_tool_start de l'appel courant deja imprime

    def avancer(self, messages: list[dict], fin: bool = False) -> None:
        """Imprime ce qui n'a pas encore ete rendu. `fin` : conversation close, un appel
        sans resultat s'imprime avec un resultat vide (comme le rejeu l'a toujours fait)."""
        resultats = _collect_tool_results(messages)
        while self._curseur < len(messages):
            clos = fin or _assistant_apres(messages, self._curseur)
            if not self._rendre(messages[self._curseur], resultats, clos):
                return
            self._curseur += 1
            self._appel = 0
            self._entete_imprimee = self._appel_annonce = False

    def _rendre(self, message: dict, resultats: dict[str, str], clos: bool) -> bool:
        """Rend `message` (ou sa suite) ; False tant qu'un de ses appels attend son resultat."""
        role = message.get("role")
        if role == "user" and not _is_pure_tool_result_message(message):
            _print_user_header(_normalize_text(message.get("content", "")))
        if role != "assistant":
            return True
        appels = _normalize_tool_calls(message)
        if not self._entete_imprimee:
            _print_assistant_header()
            texte = _normalize_text(message.get("content", ""))
            _print_texte(_strip_tool_xml(texte) if appels else texte)
            self._entete_imprimee = True
        while self._appel < len(appels):
            appel = appels[self._appel]
            if not self._appel_annonce:
                print_tool_start(appel["name"], appel["input"], verbose=False)
                self._appel_annonce = True
            if appel["id"] not in resultats and not clos:
                return False
            print_tool_end(appel["name"], resultats.get(appel["id"], ""), verbose=False,
                           duration=0.0, tool_id=appel["id"], inputs=appel["input"])
            self._appel += 1
            self._appel_annonce = False
        return True


def _assistant_apres(messages: list[dict], index: int) -> bool:
    """Un message assistant posterieur : l'agent est passe outre, le resultat ne viendra plus."""
    return any(m.get("role") == "assistant" for m in messages[index + 1:])


def _print_texte(texte: str) -> None:
    if texte.strip():
        safe_print(_make_renderable(texte), texte)


def _print_user_header(text: str) -> None:
    print()
    print(clr("╭─ you ", "dim") + clr("○", "cyan")
          + clr(" " + "─" * 40, "dim"))
    for line in (text.splitlines() or [""]):
        print(clr("  │ ", "dim") + line)


def _print_assistant_header() -> None:
    print()
    print(clr("╭─ bouzecode ", "dim") + clr("●", "green")
          + clr(" " + "─" * 25, "dim"))
