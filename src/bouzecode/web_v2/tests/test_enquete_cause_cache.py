# [desc] Enquête : un tour dont le cache lu chute affiche sa cause probable, lue dans l'empreinte du préfixe journalisée avec l'appel — préfixe modifié chez nous (quelle partie) ou raté côté fournisseur (préfixe identique). [/desc]
"""Session semée de 5 tours (cache lu / plein tarif, première partie du préfixe changée) :

  T1  0 / 12 000                     premier tour
  T2  12 000 / 5 000   « aucune »    cache servi
  T3  2 048 / 15 538   « aucune »    chute, préfixe identique → raté côté fournisseur (DeepInfra)
  T4  12 500 / 5 000   « note »      la note grossit, mais le cache ne chute pas → aucune cause
  T5  1 000 / 17 000   « tools »     chute, outil ajouté → préfixe modifié chez nous
"""
import json

import pytest

SID = "cause01"
AGENT = "c0ffee000001"
TOURS = [  # (tour, cache lu, plein tarif, prefixe_change)
    (1, 0, 12000, None),
    (2, 12000, 5000, "aucune"),
    (3, 2048, 15538, "aucune"),
    (4, 12500, 5000, "note"),
    (5, 1000, 17000, "tools"),
]


def _journal():
    log = []
    for tour, lu, plein, change in TOURS:
        entree = {"event": "llm_call", "turn": tour, "timestamp": 1000 + tour,
                  "api_input_tokens": plein, "api_output_tokens": 50, "api_cache_read": lu,
                  "api_cache_create": 0, "provider": "DeepInfra"}
        if change:
            entree["prefixe_change"] = change
        log.append(entree)
    return log


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.backend.core import config as config_mod
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.services.sessions import enquete, store

    cfg = tmp_path / "cfg"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", cfg)
    dumps = cfg / "debug_payloads" / SID
    dumps.mkdir(parents=True)
    records = [{"turn": t, "messages": [{"role": "user", "content": f"tour {t}"}],
                "system_blocks": [{"type": "text", "text": "Système stable"}],
                "context_state": {"notes": {}}} for t, *_ in TOURS]
    (dumps / "turns.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    messages = [m for t, *_ in TOURS for m in ({"role": "user", "content": f"tour {t}"},
                                                {"role": "assistant", "content": "."})]
    session_file = tmp_path / f"{AGENT}.session.json"
    session_file.write_text(json.dumps({"session_id": SID, "model": "deepseek-v4.1-flash",
                                        "messages": messages, "system_prompt": "Système stable",
                                        "compaction_log": _journal()}), encoding="utf-8")
    ref = store.SessionRef(key=f"agent/{AGENT}", kind="daily", path=session_file)
    monkeypatch.setattr(store, "resolve", lambda key: ref if key == f"agent/{AGENT}" else None)
    enquete.oublier()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    enquete.oublier()


def _get(client, chemin):
    resp = client.get(f"/api/enquete/{AGENT}{chemin}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_la_frise_donne_la_cause_des_seuls_tours_dont_le_cache_chute(client):
    causes = {t["tour"]: t["cause_cache"] for t in _get(client, "/frise")["tours"]}
    assert causes == {
        1: None, 2: None, 4: None,
        3: "raté côté fournisseur (DeepInfra) : préfixe identique",
        5: "préfixe modifié chez nous : liste des outils",
    }


def test_un_raté_du_fournisseur_est_marqué_cache_raté_et_nommé_dans_le_tour(client):
    frise = {t["tour"]: t for t in _get(client, "/frise")["tours"]}
    assert "cache_rate" in frise[3]["marqueurs"] and frise[3]["anormal"]
    assert "cache_rate" not in frise[4]["marqueurs"]
    assert _get(client, "/tours/3")["cause_cache"] == \
        "raté côté fournisseur (DeepInfra) : préfixe identique"
    assert _get(client, "/tours/5")["cause_cache"] == "préfixe modifié chez nous : liste des outils"
    assert _get(client, "/tours/2")["cause_cache"] is None


def test_une_session_sans_empreintes_dit_que_la_cause_est_inconnue():
    from bouzecode.web_v2.services.sessions.enquete import marqueurs as mq
    avant = {"api_cache_read": 12000, "api_input_tokens": 5000}
    apres = {"api_cache_read": 2048, "api_input_tokens": 15538}
    assert mq.cause_du_rate(apres, avant) == \
        "cause inconnue : empreintes du préfixe non journalisées pour ce tour"
    assert mq.cause_du_rate({**apres, "prefixe_change": "messages"}, avant) == \
        "préfixe modifié chez nous : historique des messages"
