"""Bouzecode test suite.

Every directory below this one carries an `__init__.py`, and that is load-bearing
rather than decorative. The repository keeps flat packages at its root (`tools/`,
`commands/`, `plugin/`, `ui/`, `memory/`, …) whose names are also used by test
directories. With `--import-mode=importlib` (pyproject) plus an UNBROKEN chain of
`__init__.py` up to this package, pytest names every test module by its full
dotted path — `tests.backend.tools.registry.test_x` — which can collide with
nothing. Break the chain anywhere and the modules under that directory fall back
to their bare stem (`test_x`), where two same-named test files silently shadow
each other in `sys.modules`.

So: adding a test directory means adding its `__init__.py`. There is a test that
says so — tests/backend/regression/structure/test_test_packages_are_complete.py.
"""
