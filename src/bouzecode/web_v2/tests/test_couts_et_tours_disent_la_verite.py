# [desc] « Coûts & tours » d'une session : taux de cache, statut des blocs, coût total et appels annexes servis par /turns et /costs correspondent aux usages journalisés. [/desc]
"""Ce que lit l'utilisateur dans l'onglet Coûts & tours d'un agent.

Une session de trois appels principaux, sémantique du gateway (input = frais + écrit au cache) :
  T1 écrit tout le préfixe en cache (premier appel)   in=1050 (cc=1000)  cr=0
  T2 relit ce préfixe                                in=60    (cc=10)   cr=1000
  T3 après mutation du 2ᵉ bloc système               in=560   (cc=500)  cr=500
plus UN appel annexe (résumé de réflexion) et un tour dont la sortie a dû être estimée.
"""
import json

import pytest

MODEL = "claude-sonnet-5"                      # tarif COSTS : (2.8, 14.0) par million
IN_PRICE, OUT_PRICE = 2.8, 14.0


def _cc():
    return {"type": "ephemeral"}


BLOCS_T1 = [
    {"type": "text", "text": "PRÉFIXE STABLE", "cache_control": _cc()},
    {"type": "text", "text": "NOTE MÉTHODO v1", "cache_control": _cc()},
    {"type": "text", "text": "# Session Context (volatile)"},
]
BLOCS_T3 = [BLOCS_T1[0], {"type": "text", "text": "NOTE MÉTHODO v2", "cache_control": _cc()},
            BLOCS_T1[2]]

APPELS = [  # (tour, in, out, cache_read, cache_create, blocs, sortie estimée)
    (1, 1050, 200, 0, 1000, BLOCS_T1, False),
    (2, 60, 80, 1000, 10, BLOCS_T1, False),
    (3, 560, 40, 500, 500, BLOCS_T3, True),
]
ANNEXE = {"event": "side_call", "turn": 3, "model": MODEL, "label": "",
          "api_input_tokens": 300, "api_output_tokens": 50,
          "api_cache_read": 0, "api_cache_create": 0}


def _cout(inp, out, cr, cc):
    """Tarif du gateway : l'entrée comprend l'écriture de cache, facturée à part à 1,25×."""
    return ((inp - cc) * IN_PRICE + cr * IN_PRICE * 0.1 + cc * IN_PRICE * 1.25
            + out * OUT_PRICE) / 1_000_000


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.backend.core import config as config_mod
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.services.sessions import store

    cfg = tmp_path / "cfg"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", cfg)
    sid = "couts001"
    messages = [{"role": "user", "content": "Fais le travail"}]
    dumps = cfg / "debug_payloads" / sid
    dumps.mkdir(parents=True)
    log, records = [], []
    for tour, inp, out, cr, cc, blocs, estimee in APPELS:
        entry = {"event": "llm_call", "turn": tour, "timestamp": 1_000 + 10 * tour,
                 "api_input_tokens": inp, "api_output_tokens": out,
                 "api_cache_read": cr, "api_cache_create": cc}
        if estimee:
            entry["api_output_estimated"] = True
        log.append(entry)
        records.append({"turn": tour, "messages": messages, "system_blocks": blocs,
                        "context_state": {"notes": {}}})
    log.append(ANNEXE)
    (dumps / "turns.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps({
        "session_id": sid, "model": MODEL, "messages": messages,
        "system_prompt": "PRÉFIXE STABLE", "compaction_log": log}), encoding="utf-8")

    ref = store.SessionRef(key="agent/couts", kind="daily", path=session_file)
    monkeypatch.setattr(store, "resolve", lambda key: ref)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_le_taux_de_cache_de_chaque_tour_est_la_part_du_prompt_lue_en_cache(client):
    """Prompt total = input (qui contient l'écriture) + lu en cache."""
    tours = client.get("/api/sessions/agent/couts/turns").get_json()["calls"]
    assert [t["cache_hit_pct"] for t in tours] == [0, round(100 * 1000 / 1060), round(100 * 500 / 1060)]


def test_un_bloc_systeme_ecrit_au_premier_appel_n_est_pas_affiche_comme_lu_en_cache(client):
    """Le premier appel ÉCRIT le cache ; un bloc muté est réécrit. Les afficher « caché »
    masquait précisément la perte de cache que la vue sert à diagnostiquer."""
    def statut(tour, texte):
        items = client.get(f"/api/sessions/agent/couts/turns/{tour}").get_json()["items"]
        return next(i["cache_status"] for i in items if i["content"] == texte)

    assert statut(1, "PRÉFIXE STABLE") == "new-cache"
    assert statut(2, "PRÉFIXE STABLE") == "cached"
    assert statut(3, "PRÉFIXE STABLE") == "cached"
    assert statut(3, "NOTE MÉTHODO v2") == "new-cache"


def test_turns_et_costs_annoncent_le_meme_cout_total_appels_annexes_compris(client):
    attendu = sum(_cout(inp, out, cr, cc) for _, inp, out, cr, cc, _, _ in APPELS) + _cout(300, 50, 0, 0)
    turns = client.get("/api/sessions/agent/couts/turns").get_json()
    costs = client.get("/api/sessions/agent/couts/costs").get_json()["total"]

    assert turns["side_calls"]["count"] == 1
    assert costs["side_calls"] == 1 and costs["calls"] == 3
    assert costs["cost"] == pytest.approx(attendu, abs=1e-4)
    assert turns["total_cost"] == pytest.approx(attendu, abs=1e-3)
    assert costs["input_tokens"] == 1050 + 60 + 560 + 300


def test_une_sortie_estimee_est_signalee_au_lieu_d_etre_presentee_comme_mesuree(client):
    tours = client.get("/api/sessions/agent/couts/turns").get_json()["calls"]
    costs = client.get("/api/sessions/agent/couts/costs").get_json()["total"]
    assert [t["output_estimated"] for t in tours] == [False, False, True]
    assert costs["output_estimated_calls"] == 1
