# [desc] BUG robustesse : un enfant KO-PLAFONNÉ (ou CRASHÉ) doit être vu TERMINAL par le
# réveil du parent, aligné sur reaper.terminal_outcome (jamais divergent). Prédicats purs. [/desc]
"""Régression : `wake.ticket_terminal` déléguait à `workflow.is_terminal`, qui reste False
pour un KO-plafonné (la transition terminale `wake_failed` continue de matcher). Résultat :
`should_wake_parent` exigeant `all(ticket_terminal)` ne réveillait JAMAIS le parent. Fix :
l'autorité du réveil est `reaper.terminal_outcome` (integrated/failed/crashed = terminal),
la MÊME que le faucheur → plus de divergence. Zéro agent LLM."""
from bouzecode.web_v2.services.work import reaper, wake, workflow


def _run(kind, state="finished", verdict=None):
    return {"agent_id": "a" * 12, "kind": kind, "state": state, "verdict": verdict}


def _committed(runs, **extra):
    t = {"id": "1", "title": "T", "prompt": "p", "runs": runs, **extra}
    t["worktree"] = {"state": "committed", "worktree": "/w", "base": "develop",
                     "branch": "agent/x", "repo_root": "/r"}
    return t


def _verdict_ko(tid="1", work_passes=3):
    """Verdict KO : issue terminale 'failed'.

    S'appelait `_ko_capped` et sortait 3 runs `work` pour « atteindre le plafond de passes ».
    `_MAX_WORK_PASSES` a été supprimé avec la boucle d'orchestration p10 : il n'y a plus de
    plafond, un verdict KO est terminal quel qu'en soit le nombre de passes. Le paramètre
    `work_passes` ne sert plus qu'à prouver cette indépendance."""
    runs = [_run("validate", verdict="KO")] + [_run("work") for _ in range(work_passes)]
    return _committed(runs) | {"id": tid}


def _crashed(tid="1"):
    return _committed([_run("work")], crashed=True) | {"id": tid}


def _merged(tid="1"):
    t = _committed([_run("validate", verdict="OK"), _run("work")]) | {"id": tid}
    t["worktree"]["state"] = "cleaned"
    return t


# ── un KO-plafonné est TERMINAL (cœur du bug) ─────────────────────────────────

def test_ko_capped_child_is_terminal():
    t = _verdict_ko()
    assert reaper.terminal_outcome(t) == "failed"
    assert reaper.is_terminal(t) is True
    assert wake.ticket_terminal(t) is True  # <- le fix : n'était jamais True avant


def test_terminal_authority_does_not_diverge():
    """L'autorité du réveil (ticket_terminal) et celle du faucheur (terminal_outcome)
    donnent le MÊME verdict pour un KO-plafonné : plus de divergence."""
    t = _verdict_ko()
    assert wake.ticket_terminal(t) == (reaper.terminal_outcome(t) is not None)


def test_ko_est_terminal_quel_que_soit_le_nombre_de_passes():
    """Le contrat livré : un verdict KO est TERMINAL, avec une passe de travail comme avec
    quatre. Ce test pinnait auparavant la distinction « KO au plafond » / « KO sous le
    plafond » — `_MAX_WORK_PASSES` a été supprimé avec la boucle d'orchestration p10, cette
    distinction n'existe plus. Ce qui compte pour le parent survit et est tenu ici : un
    enfant dont la validation a rendu KO ne le laisse jamais attendre."""
    for passes in (1, 4):
        t = _verdict_ko(work_passes=passes)
        assert reaper.terminal_outcome(t) == "failed", passes
        assert wake.ticket_terminal(t) is True, passes


def test_busy_ticket_is_not_terminal_even_if_crashed_flag_absent():
    t = _committed([_run("validate", state="running"), _run("work")])
    assert wake.ticket_terminal(t) is False


# ── réveil du parent : failed ET crashed débloquent ───────────────────────────

def test_ko_capped_wakes_parent():
    kids = [_verdict_ko()]
    sig = wake.children_signature(kids)
    assert wake.should_wake_parent(True, kids, None, sig) is True


def test_crashed_child_is_terminal_and_wakes_parent():
    c = _crashed()
    assert wake.ticket_terminal(c) is True
    kids = [c]
    sig = wake.children_signature(kids)
    assert wake.should_wake_parent(True, kids, None, sig) is True


def test_mixed_terminal_children_all_wake():
    kids = [_merged("1"), _verdict_ko("2"), _crashed("3")]
    sig = wake.children_signature(kids)
    assert wake.should_wake_parent(True, kids, None, sig) is True


# ── idempotence : même signature → pas de re-réveil ───────────────────────────

def test_ko_capped_wake_is_idempotent():
    kids = [_verdict_ko()]
    sig = wake.children_signature(kids)
    # déjà réveillé avec cette signature (state[parent] == sig) → plus de réveil
    assert wake.should_wake_parent(True, kids, sig, sig) is False


# ── digest : distingue OK / KO(failed) / CRASHED ──────────────────────────────

def test_digest_distinguishes_ok_ko_crashed():
    kids = [
        _merged("1") | {"title": "A"},
        _verdict_ko("2") | {"title": "B"},
        _crashed("3") | {"title": "C"},
    ]
    digest = wake.build_wake_digest(kids)
    assert "Ticket 1 « A » : OK (mergé)" in digest
    assert "Ticket 2 « B » : KO" in digest  # KO (échec, plafond de passes atteint)
    assert "Ticket 3 « C » : CRASHED" in digest


def test_outcome_labels_are_distinct():
    assert wake.ticket_outcome(_merged()) == "OK (mergé)"
    assert wake.ticket_outcome(_crashed()) == "CRASHED"
    assert wake.ticket_outcome(_verdict_ko()).startswith("KO")
