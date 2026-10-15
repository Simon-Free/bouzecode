# [desc] Tests that the loop detector tells apart calls differing only by their query or code. [/desc]
"""Signature de boucle : requête SQL et code comptent (audit Focus du 2026-09-29).

Les 65 « Loop detected » de Focus en 30 jours étaient TOUS des faux positifs : la
signature ignorait `queries` (execute_sql) et `code` (execute_python), si bien que trois
requêtes différentes se réduisaient au seul nom d'outil. Et une valeur tronquée à 200
caractères confondait deux requêtes au même début.
"""
from bouzecode.backend.agent.loop_detector import ToolCallLoopDetector


def _three_turns(inputs: list[dict], name: str):
    detector = ToolCallLoopDetector()
    warning = None
    for params in inputs:
        warning = detector.record_and_check([{"name": name, "input": params}])
    return warning


def test_different_sql_queries_are_not_a_loop():
    queries = [{"queries": f'SELECT * FROM "D_TRAIN" WHERE "ID_TRAIN" = {n}'} for n in (1, 2, 3)]
    assert _three_turns(queries, "execute_sql") is None


def test_different_python_code_is_not_a_loop():
    codes = [{"code": f"print({n})"} for n in (1, 2, 3)]
    assert _three_turns(codes, "execute_python") is None


def test_queries_sharing_a_long_prefix_are_not_a_loop():
    prefix = "SELECT " + ", ".join(f'"COL_{i}"' for i in range(60))
    queries = [{"sql": f"{prefix} WHERE x = {n}"} for n in (1, 2, 3)]
    assert _three_turns(queries, "run_sql") is None


def test_the_same_query_three_times_is_still_a_loop():
    same = [{"queries": 'SELECT 1'}] * 3
    warning = _three_turns(same, "execute_sql")
    assert warning is not None and warning.tools == ["execute_sql"]
