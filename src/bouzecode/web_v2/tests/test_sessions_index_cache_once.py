# [desc] Lister les sessions ne lit et n'écrit l'index de méta qu'une seule fois par appel. [/desc]
"""Bug B5 : list_sessions chargeait l'index, puis list_agent_sessions le rechargeait et
le sauvait, puis list_sessions le re-sauvait — deux lectures et deux écritures du JSON
complet à chaque poll du front."""
from bouzecode.web_v2.services.sessions import purge, store
from bouzecode.web_v2.runtime import runner


def _count_index_io(monkeypatch, tmp_path):
    """Compte les lectures/écritures de l'index en déléguant aux vraies fonctions."""
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "index_cache.json")
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    monkeypatch.setattr(runner, "list_agents", lambda: [])
    loads, saves = [], []
    real_load, real_save = store._load_cache, store._save_cache

    def counting_load():
        loads.append(1)
        return real_load()

    def counting_save(cache):
        saves.append(1)
        real_save(cache)

    monkeypatch.setattr(store, "_load_cache", counting_load)
    monkeypatch.setattr(store, "_save_cache", counting_save)
    return loads, saves


def test_lister_les_sessions_ne_touche_lindex_quune_fois(tmp_path, monkeypatch):
    """Un chargement de la liste des conversations ne relit et ne réécrit le fichier
    d'index qu'une seule fois."""
    loads, saves = _count_index_io(monkeypatch, tmp_path)

    store.list_sessions()

    assert len(loads) == 1
    assert len(saves) == 1


def test_lister_les_agents_seuls_gere_toujours_son_index(tmp_path, monkeypatch):
    """Appelée seule (sidebar Conversations), la liste des agents charge et sauve son
    index elle-même."""
    loads, saves = _count_index_io(monkeypatch, tmp_path)

    store.list_agent_sessions()

    assert len(loads) == 1
    assert len(saves) == 1
