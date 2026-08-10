# [desc] Écritures concurrentes du cache d'index : jamais d'exception, cache final valide. [/desc]
"""Bug prod 2026-06-10 : tmp fixe 'index_cache.tmp' partagé entre threads/instances
→ PermissionError WinError 32 sur le replace → 500 sur /api/sessions."""
import json
import threading

from bouzecode.web_v2.services.sessions import store


def test_save_cache_concurrent_sans_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "index_cache.json")
    errors = []

    def hammer(n):
        for i in range(50):
            try:
                store._save_cache({"writer": n, "i": i})
            except Exception as exc:  # noqa: BLE001 — le test capture pour rapporter
                errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    cached = json.loads((tmp_path / "index_cache.json").read_text(encoding="utf-8"))
    assert set(cached) == {"writer", "i"}
    # pas de tmp orphelin laissé par les courses perdues non plus
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
