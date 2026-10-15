# [desc] L'index de méta n'est lu qu'une fois par process, et réécrit seulement quand un listing a bâti une méta. [/desc]
"""Bug B5 : list_sessions chargeait l'index, puis list_agent_sessions le rechargeait et
le sauvait, puis list_sessions le re-sauvait — deux lectures et deux écritures du JSON
complet à chaque poll du front. Puis, même réduit à une lecture par listing, le fichier
(5,9 Mo) était encore relu à chaque recalcul de l'arbre des agents (toutes les 10 s) alors
qu'il ne pouvait rien apprendre au process qui l'avait rempli (2026-09-29)."""
import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_registre
from bouzecode.web_v2.services.sessions import meta_index, purge, store


@pytest.fixture()
def io_index(monkeypatch, tmp_path):
    """Compte les lectures et écritures du fichier d'index en déléguant aux vraies fonctions."""
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "index_cache.json")
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    monkeypatch.setattr(agent_registre, "list_agents", lambda: [])
    jour = tmp_path / "daily" / "2026-09-29"
    jour.mkdir(parents=True)
    (jour / "session_101010_abcd.json").write_text(json.dumps({
        "first_message": "bonjour", "model": "m", "turn_count": 2, "saved_at": "2026-09-29 10:10:10",
    }), encoding="utf-8")
    lectures, ecritures = [], []
    vraie_lecture, vraie_ecriture = meta_index.read_file, meta_index.merge_into_file

    def lecture(path):
        if path == store.CACHE_PATH:
            lectures.append(1)
        return vraie_lecture(path)

    def ecriture(path, fresh):
        ecritures.append(1)
        #  La relecture faite par l'écriture elle-même (fusion) n'est pas une lecture d'index.
        monkeypatch.setattr(meta_index, "read_file", vraie_lecture)
        vraie_ecriture(path, fresh)
        monkeypatch.setattr(meta_index, "read_file", lecture)

    monkeypatch.setattr(meta_index, "read_file", lecture)
    monkeypatch.setattr(meta_index, "merge_into_file", ecriture)
    return lectures, ecritures


def test_lister_les_sessions_ne_lit_l_index_qu_une_fois_par_process(io_index):
    lectures, _ = io_index

    store.list_sessions()
    store.list_sessions()
    store.list_agent_sessions()

    assert len(lectures) == 1


def test_l_index_n_est_reecrit_que_si_une_meta_a_ete_batie(io_index):
    _, ecritures = io_index

    store.list_sessions()
    assert len(ecritures) == 1  # la session CLI, inconnue, a été décodée puis retenue
    store.list_sessions()
    assert len(ecritures) == 1  # rien de neuf : pas de réécriture du fichier


def test_un_process_neuf_reprend_les_meta_du_fichier(io_index):
    """Après un redémarrage (memo vide), les méta viennent du fichier : aucune réécriture."""
    _, ecritures = io_index
    store.list_sessions()
    meta_index.reset_memo()

    listing = store.list_sessions()

    assert len(ecritures) == 1
    assert listing["days"][0]["sessions"][0]["turn_count"] == 2
