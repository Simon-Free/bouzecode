# [desc] Un ticket enfant créé mais jamais lancé ne bloque ni ne fausse le réveil du manager. [/desc]
"""Le ticket fantôme : créé, puis jamais lancé.

Un dispatch dupliqué ou dévié laisse derrière lui un ticket enfant qui a bien un
worktree mais n'a JAMAIS fait tourner le moindre agent. Le manager parent ne doit ni
rester bloqué à l'attendre indéfiniment, ni s'en voir rapporter le résultat : pour lui
cet enfant n'existe pas.

Décisions déterministes, aucun agent LLM lancé.
"""
from bouzecode.web_v2.services.work import wake
from bouzecode.web_v2.services.work.fsm import etats


def _run(kind, state="finished"):
    return {"agent_id": "a" * 12, "kind": kind, "state": state}


def _ticket(tid, runs, state, code=None, title="t"):
    """Ticket au modèle L2 : l'issue se lit dans `state` (+ `state_reason`)."""
    return {"id": tid, "title": title, "prompt": "p", "runs": runs, "state": state,
            "state_reason": {"code": code} if code else None,
            "worktree": {"worktree": "/w", "base": "develop", "branch": "agent/x",
                         "repo_root": "/r"}}


def _orphan(tid="orphan"):
    """Ticket jamais lancé : worktree provisionné mais AUCUN run (agent jamais spawné)."""
    return _ticket(tid, [], etats.CREATED)


def _terminal_child(tid="1"):
    return _ticket(tid, [_run("work")], etats.CLOSED, "integre")


# ── has_launched ──────────────────────────────────────────────────────────────

def test_orphan_without_run_has_not_launched():
    """Un ticket qui n'a jamais fait tourner d'agent n'est pas considéré comme lancé."""
    assert wake.has_launched(_orphan()) is False


def test_child_with_a_run_has_launched():
    """Un ticket qui a fait travailler un agent est bien considéré comme lancé."""
    assert wake.has_launched(_terminal_child()) is True


def test_has_launched_robust_to_legacy_shapes():
    """Un ticket enregistré dans un ancien format n'est jamais pris pour un ticket lancé."""
    assert wake.has_launched({}) is False
    assert wake.has_launched({"runs": "nope"}) is False


# ── should_wake_parent : l'orphelin est ignoré ─────────────────────────────────

def test_orphan_does_not_block_wake_when_real_children_terminal():
    """Un enfant fantôme n'empêche pas le réveil du manager quand ses vrais enfants ont fini."""
    kids = [_terminal_child("1"), _orphan()]
    sig = wake.children_signature(kids)
    # le vrai enfant est terminal ; l'orphelin ne doit pas empêcher le réveil
    assert wake.should_wake_parent(True, kids, None, sig) is True


def test_no_wake_when_only_orphans():
    """Un manager dont tous les enfants sont des fantômes n'est pas réveillé : rien n'a tourné."""
    kids = [_orphan("o1"), _orphan("o2")]
    sig = wake.children_signature(kids)
    # aucun enfant réel → pas de réveil (rien n'a réellement tourné)
    assert wake.should_wake_parent(True, kids, None, sig) is False


def test_real_child_still_running_blocks_even_with_orphan():
    """Un vrai enfant encore en cours retient le réveil, fantômes ou pas."""
    running = _ticket("1", [_run("work", state="running")], etats.RUNNING)
    kids = [running, _orphan()]
    assert wake.should_wake_parent(True, kids, None, wake.children_signature(kids)) is False


# ── signature & digest : l'orphelin n'y figure pas ─────────────────────────────

def test_orphan_excluded_from_signature():
    """Ajouter un enfant fantôme ne change pas l'état d'avancement vu par le manager."""
    real_only = wake.children_signature([_terminal_child("1")])
    with_orphan = wake.children_signature([_terminal_child("1"), _orphan()])
    assert real_only == with_orphan  # l'orphelin ne pèse pas sur la signature


def test_orphan_excluded_from_digest():
    """Le manager réveillé n'est jamais informé d'un enfant qui n'a jamais tourné."""
    digest = wake.build_wake_digest([_terminal_child("1"), _orphan("d954236f")])
    assert "Ticket 1" in digest
    assert "d954236f" not in digest  # le manager n'est pas informé d'un enfant fantôme
