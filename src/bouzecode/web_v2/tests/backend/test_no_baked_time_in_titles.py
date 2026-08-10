"""Garde-fou anti-régression : AUCUN titre/libellé généré serveur-side ne doit
contenir une heure cuite (motif HH:MM). L'heure est toujours dérivée côté front
depuis `started_at` (ISO UTC) → une seule vérité, plus d'incohérence UTC/local.
"""
import re

from bouzecode.web_v2.runtime.runner import Agent
from bouzecode.web_v2.services.work import fleet, subagent_events
from bouzecode.web_v2.services import message_view

# HH:MM isolé (pas suivi d'un ':' → on ne matche pas un ISO complet dans data-iso,
# mais on veut détecter tout 23:41 rendu comme TEXTE visible).
HHMM = re.compile(r"\b\d{2}:\d{2}(?!:)")


def _agent(**over):
    base = dict(
        agent_id="a1", prompt="Tu valides…", model="m", cwd="",
        pid=1, started_at="2026-07-06T23:41:00Z",
    )
    base.update(over)
    return Agent(**base)


def test_short_label_ne_contient_pas_d_heure():
    a = _agent(run_kind="validate", profile="coder")
    assert not HHMM.search(fleet._short_label(a)), fleet._short_label(a)


def test_subagent_label_ne_contient_pas_d_heure():
    label = subagent_events._label("validate")
    assert not HHMM.search(label), label


def test_agent_view_label_sans_heure_mais_started_at_iso_present():
    view = subagent_events._agent_view(
        {"agent_id": "x", "kind": "validate", "started_at": "2026-07-06T23:41:00Z"}
    )
    assert not HHMM.search(view["label"]), view["label"]
    assert view["started_at"] == "2026-07-06T23:41:00Z"  # ISO UTC brut exposé


def test_subagent_event_block_ne_cuit_pas_l_heure_visible():
    # Le HTML du marqueur inline ne doit PAS contenir "23:41" en texte : seul
    # data-iso porte l'ISO (hydraté en heure locale par le front).
    agent_view = {
        "label": "Validateur",
        "open_key": "agent/x",
        "started_at": "2026-07-06T23:41:00Z",
        "verdict": "",
        "completed": False,
    }
    html_out = message_view._subagent_event_block(
        {"role": "subagent_event", "subtype": "launch", "count": 1, "agents": [agent_view]}
    )
    # L'ISO est présent (dans data-iso) mais AUCUN HH:MM en texte visible.
    assert 'data-iso="2026-07-06T23:41:00Z"' in html_out
    # On dépouille les attributs data-iso (ISO UTC légitime) avant de chercher
    # une heure cuite : seul le TEXTE visible doit être exempt de HH:MM.
    visible = re.sub(r'data-iso="[^"]*"', "", html_out)
    assert not HHMM.search(visible), visible
