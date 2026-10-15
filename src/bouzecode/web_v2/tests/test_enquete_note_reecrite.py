# [desc] Enquête : un cache raté dont la note a changé dit si elle a été simplement allongée (préfixe intact → raté côté fournisseur) ou réécrite chez nous (position, extrait, passe de compaction du même intervalle) ; une ancienne session garde la formulation d'origine. [/desc]
"""Session semée (cache lu / plein tarif, première partie du préfixe changée) :

  T1  0 / 12 000                         premier tour
  T2  12 000 / 5 000   note_allongee     cache servi
  T3  2 048 / 30 575   note_allongee     chute, note seulement allongée → fournisseur
  T4  12 000 / 5 000   note_allongee
  T5  2 048 / 20 000   note_reecrite     chute ; purge d'extraits journalisée juste avant
  T6  12 000 / 5 000   note_allongee
  T7  2 048 / 20 000   note_reecrite     chute, réécriture sans passe journalisée
  T8  12 000 / 5 000   note              ancienne session (valeur d'avant)
  T9  2 048 / 20 000   note              chute → formulation d'origine
"""
import json

import pytest

SID = "noteree01"
AGENT = "c0ffee000002"
EXTRAIT = "…calc.py⏎⏎## snippet: /tmp/x.py L1-2 — \"brouillon\"⏎    1  def add…"
TOURS = [  # (tour, cache lu, plein tarif, prefixe_change, détails)
    (1, 0, 12000, None, {}),
    (2, 12000, 5000, "note_allongee", {"note_allongee": True, "note_divergence": None}),
    (3, 2048, 30575, "note_allongee", {"note_allongee": True, "note_divergence": None}),
    (4, 12000, 5000, "note_allongee", {"note_allongee": True, "note_divergence": None}),
    (5, 2048, 20000, "note_reecrite", {"note_allongee": False, "note_divergence": 1548,
                                       "note_perdue": 962, "note_extrait": EXTRAIT,
                                       "note_extrait_nouveau": "…## snippet-dropped: /tmp/x.py…"}),
    (6, 12000, 5000, "note_allongee", {"note_allongee": True, "note_divergence": None}),
    (7, 2048, 20000, "note_reecrite", {"note_allongee": False, "note_divergence": 40,
                                       "note_perdue": 10, "note_extrait": "…## Plan⏎- [ ] lire…",
                                       "note_extrait_nouveau": "…## Plan⏎- [x] lire…"}),
    (8, 12000, 5000, "note", {}),
    (9, 2048, 20000, "note", {}),
]


def _journal():
    log = []
    for tour, lu, plein, change, details in TOURS:
        if tour == 5:  # la passe mécanique a tourné entre l'appel 4 et l'appel 5
            log.append({"phase": "note_snippet_cleanup", "turn": 4, "chars_removed": 900,
                        "dropped": ["/tmp/x.py L1-2"], "merged": 0})
        entree = {"event": "llm_call", "turn": tour, "timestamp": 1000 + tour,
                  "api_input_tokens": plein, "api_output_tokens": 50, "api_cache_read": lu,
                  "api_cache_create": 0, "provider": "DeepInfra", **details}
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


FOURNISSEUR = "note simplement allongée, préfixe intact : raté côté fournisseur (DeepInfra)"
PURGE = f"note réécrite chez nous (à la position 1548 : « {EXTRAIT} ») : purge d'extraits périmés"
INCONNUE = ("note réécrite chez nous (à la position 40 : « …## Plan⏎- [ ] lire… ») : "
            "cause non identifiée (aucune compaction journalisée depuis l'appel précédent)")
ANCIENNE = "préfixe modifié chez nous : note (bloc qui suit le système)"


def test_la_frise_distingue_note_allongee_et_note_reecrite(client):
    causes = {t["tour"]: t["cause_cache"] for t in _get(client, "/frise")["tours"]}
    assert causes == {1: None, 2: None, 4: None, 6: None, 8: None,
                      3: FOURNISSEUR, 5: PURGE, 7: INCONNUE, 9: ANCIENNE}


def test_le_tour_a_la_loupe_nomme_la_passe_qui_a_reecrit_la_note(client):
    assert _get(client, "/tours/5")["cause_cache"] == PURGE
    assert _get(client, "/tours/3")["cause_cache"] == FOURNISSEUR
    assert _get(client, "/tours/9")["cause_cache"] == ANCIENNE


def test_un_marqueur_stale_dans_l_extrait_est_nomme_quand_aucune_passe_n_est_journalisee():
    from bouzecode.web_v2.services.sessions.enquete import marqueurs as mq
    avant = {"api_cache_read": 12000, "api_input_tokens": 5000}
    apres = {"api_cache_read": 2048, "api_input_tokens": 15538, "prefixe_change": "note_reecrite",
             "note_divergence": 812, "note_extrait": "…## snippet-stale: calc.py L1-9 — STALE…"}
    assert mq.cause_du_rate(apres, avant) == (
        "note réécrite chez nous (à la position 812 : « …## snippet-stale: calc.py L1-9 — STALE… ») : "
        "marqueur STALE d'extrait périmé")
