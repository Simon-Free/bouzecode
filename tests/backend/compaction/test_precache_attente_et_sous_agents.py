# [desc] Compaction avant expiration du cache : minuteur armé à la fin de chaque appel (pause de l'utilisateur comprise), message reçu pendant la passe, sous-agents compactés sans récursion des appels annexes. [/desc]
"""Le minuteur compte depuis la fin du DERNIER appel au modèle (le cache du gateway expire 5 min
après lui) : il couvre l'attente du message humain suivant, pas seulement un lot d'outils.
Un sous-agent (`_depth` >= 1, sa propre note) compacte ; un appel annexe (`_context_state`
à None) jamais — c'est ce qui borne la récursion. Délais de test en dizaines de ms."""
import threading
import time
from types import SimpleNamespace

import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn, StreamStarted
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor
from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.compact_methodology import CHARS_PER_TOKEN, maybe_compact
from bouzecode.backend.context_manager.compact_precache import (
    armer_apres_appel, desarmer_minuteur, precache_compact, should_precache_compact,
    start_precache_watchdog,
)
from bouzecode.backend.context_manager.methodology import append_user_msg_to_methodology


def _session(turn: int = 12):
    return SimpleNamespace(turn_count=turn, compaction_log=[], timing_entries=[])


def _note_state(tokens: int = 31000):
    return SimpleNamespace(notes={"methodology": "x" * int(tokens * CHARS_PER_TOKEN + 10)},
                           allegements=0, last_compact_turn=0)


def _halve(text: str) -> str:
    return text[: len(text) // 2]


def test_le_minuteur_arme_a_la_fin_d_un_appel_compacte_pendant_la_pause():
    """Aucun outil ne tourne : l'agent a fini son tour et attend l'humain."""
    cs, session, fait = _note_state(), _session(), threading.Event()
    config = {"_state": session, "_context_state": cs, "precache_compact_delay_s": 0.05}

    armer_apres_appel(config, passes=lambda t: fait.set() or _halve(t))

    assert fait.wait(2)
    session._minuteur_precache.join(2)
    assert cs.last_compact_turn == 12 and cs.allegements == 1


def test_un_nouvel_appel_au_modele_desarme_le_minuteur():
    cs, session, appels = _note_state(), _session(), []
    config = {"_state": session, "_context_state": cs, "precache_compact_delay_s": 0.3}

    armer_apres_appel(config, passes=lambda t: appels.append(t) or _halve(t))
    premier = session._minuteur_precache
    armer_apres_appel(config, passes=lambda t: appels.append(t) or _halve(t))
    assert premier.finished.is_set(), "réarmer annule le minuteur précédent"
    desarmer_minuteur(session)
    time.sleep(0.5)

    assert not appels and session._minuteur_precache is None


def test_un_message_recu_pendant_la_passe_n_attend_pas_et_n_est_pas_perdu():
    cs, session = _note_state(), _session()
    partie, liberee = threading.Event(), threading.Event()

    def passes_lentes(text):
        partie.set()
        assert liberee.wait(2)
        return "SUMMARY"

    armer_apres_appel({"_state": session, "_context_state": cs,
                       "precache_compact_delay_s": 0.01}, passes=passes_lentes)
    assert partie.wait(2)
    debut = time.monotonic()
    append_user_msg_to_methodology(cs, "nouveau message")
    assert time.monotonic() - debut < 0.5, "l'ajout ne bloque pas sur la passe en cours"
    liberee.set()
    session._minuteur_precache.join(2)

    note = cs.notes["methodology"]
    assert note.startswith("SUMMARY\n\n## User @") and note.endswith("nouveau message")


def test_un_sous_agent_arme_son_minuteur_et_compacte():
    cs, fait = _note_state(), threading.Event()
    config = {"_state": _session(), "_depth": 1, "_context_state": cs,
              "precache_compact_delay_s": 0.05}
    timer = start_precache_watchdog(config, passes=lambda t: fait.set() or _halve(t))
    assert timer is not None and fait.wait(2)
    timer.join(2)
    assert cs.allegements == 1


# ── Absence de récursion : les VRAIS appels annexes de la compaction d'un sous-agent ──

_LIGNE = "     1\tdef entry():\n"


def _note_de_sous_agent() -> str:
    lourd = int(31000 * CHARS_PER_TOKEN / len(_LIGNE)) + 50
    return ("## User\nRefactor the parser.\n"
            f'## snippet: proj/a.py L1-3 — "parser entry"\n' + _LIGNE * lourd
            + "## Tour 3\nLe parser lit d'abord le header.\n")


class AnnexeQuiTenteDeCompacter:
    """Faux gateway : à chaque appel annexe, tente de relancer les deux compactions avec la
    config REÇUE (celle de l'appel annexe) sur la note du sous-agent."""

    def __init__(self, cs):
        self.cs, self.configs, self.tentatives = cs, [], []

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            self.configs.append(config)
            self.tentatives.append((
                maybe_compact(self.cs, "methodology", config),
                should_precache_compact(self.cs, "methodology", config),
                start_precache_watchdog(config),
            ))
            prompt = str(messages[0]["content"])
            yield StreamStarted()
            yield AssistantTurn(text="DROP 1" if "SNIPPETS IN MEMORY" in prompt else "",
                                tool_calls=[], in_tokens=0, out_tokens=0, stop_reason="end_turn")
        return stream


@pytest.fixture
def gateway():
    yield set_stream_interceptor
    set_stream_interceptor(None)


def test_la_compaction_d_un_sous_agent_ne_recurse_pas(gateway):
    cs = ContextState(notes={"methodology": _note_de_sous_agent()})
    faux = AnnexeQuiTenteDeCompacter(cs)
    gateway(faux)
    config = {"_state": _session(), "_depth": 1, "_context_state": cs, "model": "claude-opus-5"}

    retire = precache_compact(cs, "methodology", config)

    assert retire > 0 and "## snippet-dropped:" in cs.notes["methodology"]
    assert faux.configs, "le juge a bien été appelé"
    assert all(c["_context_state"] is None for c in faux.configs)
    assert all(t == (0, False, None) for t in faux.tentatives), "aucune compaction imbriquée"
    assert len(faux.configs) <= 3, "juge + résumé (+ relance) : nombre d'appels borné"
