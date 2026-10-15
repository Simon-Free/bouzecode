"""Regression: concurrent SkillResearch calls raised KeyError('...python312.zip').

``importlib.invalidate_caches()`` -> ``PathFinder.invalidate_caches`` iterates a
snapshot of ``sys.path_importer_cache`` and ``del``s every ``None`` entry (e.g. a
``python312.zip`` sys.path entry missing on disk). Two threads doing it at the
same time delete the same key twice -> KeyError. ``plugin.store._import_root_of``
is reached by skill discovery, so parallel SkillResearch calls hit the race.
"""
from __future__ import annotations

import sys
import threading

from bouzecode.backend.plugin import store


def test_concurrent_import_root_of_does_not_raise_keyerror(tmp_path):
    fake_keys = [str(tmp_path / f"missing{i}.zip") for i in range(50_000)]
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        try:
            for _ in range(3):
                for key in fake_keys:
                    sys.path_importer_cache.setdefault(key, None)
                store._import_root_of("bouzecode-nonexistent-pkg")
        except BaseException as exc:  # noqa: BLE001 - collected for the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        for key in fake_keys:
            sys.path_importer_cache.pop(key, None)

    assert errors == [], f"concurrent invalidate_caches raised: {errors[:3]!r}"
