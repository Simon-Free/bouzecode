"""Point 3 du ticket 7fb5f816 : un parent qui ATTEND SON ENFANT n'est pas un agent planté.

`multi_agent.attente_web._wait_for_child` bloque le parent aussi longtemps que travaille l'enfant,
sans le moindre battement : la vue le classait `running` + `stale`, comme un process mort.
Deux des trois alertes du 2026-08-25 étaient ces parents-là. Tout est testable sans réseau :
`describe` et `children_index` sont purs.
"""
import time

from bouzecode.web_v2.services.work.activity import (
    STALE_AFTER_SECONDS, children_index, describe,
)


def _status_silencieux(now: float, tools: list[str]) -> dict:
    """Un `running` muet depuis 20 minutes — bien au-delà du seuil de silence."""
    return {"state": "running", "last_event_at": now - 1200, "tools": tools}


def test_parent_en_attente_est_decrit_comme_tel_et_pas_stale():
    now = time.time()
    view = describe(_status_silencieux(now, ["Agent"]), {}, now=now,
                    waiting_for=["7fb5f816", "9afa2536"])
    assert view["activity"] == "waiting_for_child"
    assert view["stale"] is False, "le silence d'une attente est ATTENDU"
    assert view["waiting_for"] == ["7fb5f816", "9afa2536"]
    assert "7fb5f816" in view["activity_label"]
    assert view["idle_seconds"] >= STALE_AFTER_SECONDS


def test_meme_silence_sans_enfant_reste_signale():
    """Sans enfant à attendre, le silence long reste ce qu'il était : à regarder."""
    now = time.time()
    view = describe(_status_silencieux(now, ["Bash"]), {}, now=now)
    assert view["activity"] == "Bash"
    assert view["stale"] is True
    assert "waiting_for" not in view


def test_enfant_connu_mais_outil_courant_different_nest_pas_une_attente():
    """Le parent a relancé un enfant en arrière-plan puis s'est remis au travail."""
    now = time.time()
    view = describe(_status_silencieux(now, ["Bash"]), {}, now=now,
                    waiting_for=["7fb5f816"])
    assert view["activity"] == "Bash"
    assert view["stale"] is True


def test_dernier_outil_agent_seulement_enregistre_ne_suffit_pas():
    """`meta.last_tool` n'est pas une preuve d'attente EN COURS (live=False)."""
    now = time.time()
    status = {"state": "running", "last_event_at": now - 1200}
    view = describe(status, {"last_tool": "Agent"}, now=now, waiting_for=["7fb5f816"])
    assert view["activity"] != "waiting_for_child"


def test_children_index_correle_parents_et_enfants():
    index = children_index([("papa", "enfant-1"), ("papa", "enfant-2"),
                            ("", "orphelin"), ("autre", "")])
    assert index == {"papa": ["enfant-1", "enfant-2"]}
