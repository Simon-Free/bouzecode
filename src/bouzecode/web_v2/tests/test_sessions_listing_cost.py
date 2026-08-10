# [desc] Lister les sessions ne re-décode jamais deux fois la même session, et une rafale ne rebâtit la liste qu'une fois. [/desc]
"""Coût de `GET /api/sessions`. Mesuré le 2026-07-28 sur le poste, index de méta vide :
515 sessions, **772 Mo décodés, 55 s** pour UNE requête — parce que sortir `turn_count` et
`close_reason` oblige à décoder le JSON ENTIER de chaque session (jusqu'à 112 Mo).

Ces tests comptent des OPÉRATIONS (décodages de session, reconstructions du listing), jamais
des millisecondes : c'est le nombre de lectures qui explosait, et lui seul est stable.
Ils échouent donc si l'un des trois garde-fous disparaît :
  - le memo de méta (une session décodée une seule fois par process, même si le fichier
    d'index est écrasé par une requête concurrente) ;
  - le cache TTL + single-flight de l'endpoint (une rafale ne paie qu'un calcul) ;
  - `/api/conversations/interrupted` qui ne balaie plus les sessions CLI dont il n'a que faire.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import listing_cache, purge, recovery, store


@pytest.fixture()
def daily_session(tmp_path, monkeypatch):
    """Une session CLI sur disque, un index de méta et une corbeille à soi, aucun agent web."""
    day_dir = tmp_path / "daily" / "2026-07-28"
    day_dir.mkdir(parents=True)
    session_file = day_dir / "session_101010_abcd1234.json"
    session_file.write_text(json.dumps({
        "first_message": "analyse la latence de la liste des sessions",
        "model": "claude-opus-4-8",
        "turn_count": 42,
        "saved_at": "2026-07-28 10:10:10",
        "close_reason": "final_answer",
        "messages": [{"role": "user", "content": "x" * 5000}],
    }), encoding="utf-8")
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "index_cache.json")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    monkeypatch.setattr(runner, "list_agents", lambda: [])
    return session_file


@pytest.fixture()
def session_decodes(monkeypatch):
    """Compte les décodages de JSON de session, puis délègue à la vraie lecture."""
    decoded: list[str] = []
    real_load = store.load_session_json

    def counting_load(path):
        decoded.append(str(path))
        return real_load(path)

    monkeypatch.setattr(store, "load_session_json", counting_load)
    return decoded


def test_une_session_nest_decodee_quune_fois_pour_plusieurs_listings(daily_session,
                                                                    session_decodes):
    """Trois listings de suite ne lisent le JSON d'une session qu'une seule fois."""
    store.list_sessions()
    store.list_sessions()
    store.list_sessions()

    assert session_decodes.count(str(daily_session)) == 1


def test_un_index_ecrase_ne_fait_pas_redecoder_la_session(daily_session, session_decodes):
    """Le fichier d'index effacé sous nos pieds (écriture concurrente) ne fait PAS
    re-décoder la session : le memo du process en garde la méta."""
    store.list_sessions()
    store.CACHE_PATH.unlink()  # ce que faisait une sauvegarde concurrente qui écrasait tout

    listing = store.list_sessions()

    assert session_decodes.count(str(daily_session)) == 1
    assert listing["days"][0]["sessions"][0]["turn_count"] == 42


def test_une_rafale_de_requetes_ne_rebatit_la_liste_quune_fois(daily_session):
    """Six requêtes rapprochées sur la liste des sessions ne déclenchent qu'un calcul."""
    builds: list[bool] = []

    def counting_build(include_tests=False):
        builds.append(include_tests)
        return store.list_sessions(include_tests=include_tests)

    for _ in range(6):
        listing_cache.cached_list_sessions(compute=counting_build)

    assert len(builds) == 1


def test_la_liste_est_recalculee_quand_le_ttl_expire(daily_session):
    """Passé le TTL, la liste est bel et bien reconstruite (le cache n'est pas figé)."""
    builds: list[bool] = []
    clock = [1000.0]

    def counting_build(include_tests=False):
        builds.append(include_tests)
        return store.list_sessions(include_tests=include_tests)

    listing_cache.cached_list_sessions(now=lambda: clock[0], ttl=5.0, compute=counting_build)
    clock[0] += 4.0
    listing_cache.cached_list_sessions(now=lambda: clock[0], ttl=5.0, compute=counting_build)
    clock[0] += 2.0
    listing_cache.cached_list_sessions(now=lambda: clock[0], ttl=5.0, compute=counting_build)

    assert len(builds) == 2


def test_lister_les_interrompus_ne_lit_aucune_session_cli(daily_session, session_decodes):
    """Chercher les conversations interrompues ne touche plus aux sessions CLI : elles ne
    figurent pas dans la réponse, les lire était du pur gaspillage (597 Mo sur le poste)."""
    recovery.list_interrupted()

    assert session_decodes == []
