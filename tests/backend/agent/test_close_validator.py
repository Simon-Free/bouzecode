"""close_validator is fully deterministic: no LLM call, and the two task
declarations (taches_terminees / taches_restantes) are always required — an
explicit empty list is valid, omitting them is not."""
from bouzecode.backend.agent import close_validator as cv


def test_no_llm_validator_left():
    for name in ("dispatch_stream", "_should_validate", "_VALIDATOR_SYSTEM"):
        assert not hasattr(cv, name), name


def test_omitted_taches_restantes_refuses():
    ok, feedback = cv.validate_close("done", {"model": "m"}, taches_terminees=["x"])
    assert not ok
    assert "taches_restantes" in feedback


def test_empty_lists_accept():
    ok, feedback = cv.validate_close(
        "done", {"model": "m"}, taches_terminees=[], taches_restantes=[]
    )
    assert ok, feedback


def test_required_for_sub_agents_too():
    ok, _ = cv.validate_close("done", {"model": "m", "_depth": 2})
    assert not ok


def test_close_validation_false_disables_gate():
    ok, _ = cv.validate_close("done", {"model": "m", "close_validation": False})
    assert ok
