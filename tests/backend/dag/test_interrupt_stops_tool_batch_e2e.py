# [desc] Conversation tests : une interruption posée PENDANT un lot d'outils arrête les outils suivants et clôt le tour. [/desc]
"""Interrompre pendant les outils doit mordre — c'est là que l'agent passe son temps.

Le drapeau d'annulation n'était sondé que pendant le streaming LLM et en tête de tour. Un lot
d'outils ne le regardait jamais : sous BouzéqUI, un Ctrl+C pendant un `pytest` ou une série
d'`Edit` ne produisait RIEN, et `/interrupt` finissait par tuer le process faute de réponse —
donc cold-respawn au message suivant. Le Ctrl+C du TUI, lui, est un signal : il tombe partout.

L'interruption est produite ici comme en vrai : un FICHIER `cancel.flag` qui apparaît dans
l'ipc_dir pendant que le lot tourne — exactement ce qu'écrit `runner.graceful_cancel_agent`.
C'est un outil du lot lui-même qui le pose, ce qui date l'interruption à la milliseconde près
au milieu du lot, sans horloge ni course.

Ces tests sont des conversations mais ne peuvent pas passer par `tests.e2e_harness` :
`bouzecode()` n'expose pas `cancel_check`, qui est justement le sujet. On pilote donc la
boucle avec les mêmes patches, plus le câblage RÉEL de `web_v2.runtime.ipc` (`is_cancelled`
côté peek, `consume_cancel` côté boucle) que `repl` installe en production.
"""
from __future__ import annotations

import tempfile

import pytest

from bouzecode.backend.agent.dag import CANCELLED_BY_USER
from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.state import AgentState, ToolEnd
from bouzecode.backend.core.config import load_config
from bouzecode.web_v2.runtime import ipc
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


def _write(path, tc_id, *, alias="", depends_on=""):
    alias_attr = f' tool_call_alias="{alias}"' if alias else ""
    dep = f'<param name="depends_on">{depends_on}</param>' if depends_on else ""
    return (f'<tool_use name="Write" id="{tc_id}"{alias_attr}>'
            f'<param name="file_path">{path}</param>'
            f'<param name="content">x = 1</param>{dep}</tool_use>')


def _run_with_interruption(monkeypatch, tmp_path, responses):
    """Joue une vraie conversation, outils RÉELS, avec le câblage d'annulation de production.

    Rend `(state, tool_ends, mock)` : l'état pour le motif de clôture, les résultats d'outils
    pour ce que l'utilisateur voit, et le mock pour compter les allers-retours LLM."""
    import bouzecode.backend.agent.loop_turn as lt

    mock = MockLLM(responses)
    monkeypatch.setattr(lt, "stream", mock.stream)
    monkeypatch.setattr(lt, "get_tool_schemas", lambda *a, **k: [])
    monkeypatch.setattr(lt, "is_web_ipc_active", lambda: False)
    monkeypatch.setattr(lt, "_check_permission", lambda tc, c: True)

    paths = ipc.from_dir(tmp_path / "ipc")
    config = load_config()
    config.update({
        "permission_mode": "accept-all",
        "verbose": False,
        "task_classification": False,
        "close_validation": False,
        "_cwd": tempfile.mkdtemp(prefix="bouzecode_interrupt_"),
        # Le câblage exact de repl sous BouzéqUI : on PEEK aux frontières d'outils…
        "_cancel_peek": lambda: ipc.is_cancelled(paths),
    })
    state = AgentState()
    # …et la boucle CONSOMME, elle seule, pour clore le tour.
    events = list(run("go", state, config, "You are a helpful assistant.",
                      cancel_check=lambda: ipc.consume_cancel(paths)))
    return state, [e for e in events if isinstance(e, ToolEnd)], mock


def _tool_end(tool_ends, tc_id):
    matches = [e for e in tool_ends if e.tool_id == tc_id]
    assert matches, f"aucun résultat pour {tc_id} dans {[e.tool_id for e in tool_ends]}"
    return matches[0]


# ── interruption au milieu d'un lot séquentiel ───────────────────────────────

@pytest.fixture()
def lot_interrompu(monkeypatch, tmp_path):
    """Un lot de trois outils dont le deuxième pose `cancel.flag` : l'utilisateur
    interrompt pile entre les deux Write. Une SEULE réponse LLM est fournie — si la
    boucle repartait pour un tour, MockLLM le dirait en échouant."""
    apres = tmp_path / "temp_apres.py"
    state, tool_ends, mock = _run_with_interruption(monkeypatch, tmp_path, [
        f"{METH}\n"
        f"{_write(tmp_path / 'ipc' / 'cancel.flag', 'ctrl_c')}\n"
        f"{_write(apres, 'apres')}",
    ])
    return state, tool_ends, mock, apres


def test_the_tool_after_the_interruption_never_runs(lot_interrompu):
    """Le cœur : l'outil suivant ne part pas. Avant, tout le lot allait jusqu'au bout."""
    _state, _tool_ends, _mock, apres = lot_interrompu

    assert not apres.exists(), "l'outil d'après l'interruption a quand même tourné"


def test_the_cancelled_tool_gets_a_result_saying_so(lot_interrompu):
    """Il a un résultat ÉCRIT : sans lui la session porterait un tool_call sans réponse
    (invalide pour l'API), et le modèle relirait un trou au lieu d'un motif."""
    _state, tool_ends, _mock, _apres = lot_interrompu

    assert CANCELLED_BY_USER in _tool_end(tool_ends, "apres").result


def test_the_turn_actually_ends_on_the_interruption(lot_interrompu):
    """La conséquence attendue : le tour se CLÔT, motif `cancelled`. Sans elle, arrêter
    les outils ne ferait que rendre l'agent inutile en le laissant tourner."""
    state, _tool_ends, _mock, _apres = lot_interrompu

    assert state.close_reason == "cancelled"


def test_no_further_llm_round_trip_is_paid(lot_interrompu):
    """Interrompre coûte ce qu'il reste du tour, pas un aller-retour LLM de plus."""
    _state, _tool_ends, mock, _apres = lot_interrompu

    assert mock.call_index == 1


# ── interruption entre deux NIVEAUX du DAG ───────────────────────────────────

def test_a_later_dag_level_is_stopped_too(monkeypatch, tmp_path):
    """Autre frontière : l'outil interrompu est dans un niveau SUIVANT (`depends_on`),
    pas dans la même vague séquentielle. Les deux gardes sont nécessaires."""
    apres = tmp_path / "temp_niveau_2.py"
    state, tool_ends, _mock = _run_with_interruption(monkeypatch, tmp_path, [
        f"{METH}\n"
        f"{_write(tmp_path / 'ipc' / 'cancel.flag', 'ctrl_c', alias='stop')}\n"
        f"{_write(apres, 'apres', depends_on='stop')}",
    ])

    assert not apres.exists(), "le niveau suivant du DAG a tourné malgré l'interruption"
    assert CANCELLED_BY_USER in _tool_end(tool_ends, "apres").result
    assert state.close_reason == "cancelled"


# ── CONTRÔLE : sans interruption, rien ne change ─────────────────────────────

def test_without_the_flag_the_whole_batch_runs(monkeypatch, tmp_path):
    """Le même lot, à ceci près que le premier Write vise un fichier ordinaire : tout
    tourne et le tour se clôt normalement. C'est bien le drapeau qui arrête, et non le
    fait d'avoir ajouté un test de plus dans le chemin des outils."""
    apres = tmp_path / "temp_apres.py"
    state, _tool_ends, _mock = _run_with_interruption(monkeypatch, tmp_path, [
        f"{METH}\n"
        f"{_write(tmp_path / 'ipc' / 'anodin.txt', 'pas_ctrl_c')}\n"
        f"{_write(apres, 'apres')}",
        CLOSE,
    ])

    assert apres.exists(), "un lot non interrompu ne va plus au bout"
    assert state.close_reason != "cancelled"
