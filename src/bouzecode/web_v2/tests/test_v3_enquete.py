# [desc] Vue d'enquête : frise et marqueurs, diff d'un tour et premier élément qui casse le préfixe, histoire de la note, saturation, recherche, export — servis par /api/enquete/* sur une session semée. [/desc]
"""Une session de 4 tours, semée avec son journal de payloads :

  T1 note « Faits A »                                   → premier tour
  T2 la note reçoit un Delta + un extrait de code        → rupture sur la note (ajout en fin) ;
     l'outil Bash plante (Traceback)                     → marqueur « erreur »
  T3 message d'ENFORCEMENT, note compactée ; FinalAnswer refusée
  T4 le prompt système de base change ; FinalAnswer acceptée → rupture sur le bloc 0
"""
import json

import pytest

SID = "enq001"
AGENT = "a1b2c3d4e5f6"
BASE_1 = "PRÉFIXE STABLE — règles de l'agent"
BASE_2 = "PRÉFIXE MODIFIÉ — règles de l'agent"
NOTE_1 = "## Faits\nA"
NOTE_2 = NOTE_1 + "\n\n## Delta 2\nB mesuré\n\n## snippet: f.py L1-9\n" + "def f():\n    return 1\n" * 40
NOTE_3 = "## Faits\nA (compacté)"


def _cc():
    return {"type": "ephemeral"}


def _blocs(base, note):
    return [{"type": "text", "text": base, "cache_control": _cc()},
            {"type": "text", "text": f"[METHODOLOGY — mémoire]\n{note}", "cache_control": _cc()},
            {"type": "text", "text": "RÈGLE FINALE volatile"}]


TOURS = [  # (tour, base, note, message d'entrée, in, cache lu)
    (1, BASE_1, NOTE_1, "Fais le travail", 1000, 0),
    (2, BASE_1, NOTE_2, "", 400, 900),
    (3, BASE_1, NOTE_3, "⚠️ ENFORCEMENT : Methodology manquante", 300, 900),
    (4, BASE_2, NOTE_3, "", 1200, 0),
]


def _outil(nom, id_, entree):
    return {"id": id_, "name": nom, "input": entree}


def _resultat(nom, id_, texte):
    return {"role": "tool", "name": nom, "tool_call_id": id_, "content": texte}


MESSAGES = [
    {"role": "user", "content": "Fais le travail"},
    {"role": "assistant", "content": "<thinking>je note</thinking>Je commence.",
     "tool_calls": [_outil("Methodology", "m1", {"content": NOTE_1})]},
    _resultat("Methodology", "m1", "methodology append: ok"),
    {"role": "assistant", "content": ".", "tool_calls": [_outil("Bash", "b1", {"command": "python x.py"})]},
    _resultat("Bash", "b1", "Traceback (most recent call last):\n  File x.py\nValueError: non"),
    {"role": "assistant", "content": ".", "tool_calls": [_outil("FinalAnswer", "f1", {"answer": "fini"})]},
    _resultat("FinalAnswer", "f1", "CLÔTURE REFUSÉE par le validateur — il manque : recap"),
    {"role": "assistant", "content": ".", "tool_calls": [_outil("FinalAnswer", "f2", {"answer": "fini"})]},
    _resultat("FinalAnswer", "f2", "Session closing — final answer delivered: fini"),
]


def _records():
    records, log = [], []
    for tour, base, note, entree, inp, cr in TOURS:
        messages = [{"role": "user", "content": entree}] if entree else \
            [{"role": "assistant", "content": "."}, _resultat("Bash", f"r{tour}", f"sortie {tour}")]
        records.append({"turn": tour, "messages": messages, "system_blocks": _blocs(base, note),
                        "context_state": {"notes": {"methodology": note}}})
        log.append({"event": "llm_call", "turn": tour, "timestamp": 1000 + 10 * tour,
                    "api_input_tokens": inp, "api_output_tokens": 50,
                    "api_cache_read": cr, "api_cache_create": 0})
    return records, log


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.backend.core import config as config_mod
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.services.sessions import enquete, store

    cfg = tmp_path / "cfg"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", cfg)
    dumps = cfg / "debug_payloads" / SID
    dumps.mkdir(parents=True)
    records, log = _records()
    (dumps / "turns.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    session_file = tmp_path / f"{AGENT}.session.json"
    session_file.write_text(json.dumps({"session_id": SID, "model": "deepseek-v4.1-flash",
                                        "messages": MESSAGES, "system_prompt": BASE_1,
                                        "compaction_log": log}), encoding="utf-8")
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


def test_la_frise_marque_les_tours_anormaux(client):
    frise = _get(client, "/frise")
    marques = {t["tour"]: set(t["marqueurs"]) for t in frise["tours"]}
    assert "erreur" in marques[2]
    assert {"enforcement", "compaction", "cloture_refusee"} <= marques[3]
    assert "cloture_acceptee" in marques[4] and "cache_rate" in marques[4]
    assert [t["tour"] for t in frise["tours"] if t["anormal"]] == [2, 3, 4]


def test_le_diff_designe_la_note_qui_casse_le_prefixe_par_un_ajout_en_fin(client):
    tour = _get(client, "/tours/2")
    rupture = tour["diff"]["rupture"]
    assert tour["elements"][rupture]["libelle"].startswith("[METHODOLOGY")
    modif = next(m for m in tour["diff"]["modifies"] if m["indice"] == rupture)
    assert modif["nature"] == "ajout_en_fin"
    assert modif["ajoutes"] == len(NOTE_2) - len(NOTE_1)


def test_un_prompt_systeme_modifie_casse_le_prefixe_des_le_premier_bloc(client):
    tour = _get(client, "/tours/4")
    assert tour["diff"]["rupture"] == 0
    modif = next(m for m in tour["diff"]["modifies"] if m["indice"] == 0)
    assert modif["nature"] == "modifie" and modif["position"] == len("PRÉFIXE ")


def test_le_premier_tour_n_a_pas_de_diff_et_la_reponse_separe_la_reflexion(client):
    tour = _get(client, "/tours/1")
    assert tour["diff"]["premier_tour"] is True
    assert tour["reponse"]["reflexion"] == "je note"
    assert tour["reponse"]["texte"] == "Je commence."
    assert tour["reponse"]["appels"][0]["nom"] == "Methodology"


def test_la_note_n_est_pas_comptee_deux_fois(client):
    """Les notes voyagent dans un bloc système : pas d'élément « notes_block » en plus."""
    for n in (1, 3):  # tours avec un message d'entrée : c'est là que l'élément était ajouté
        tour = _get(client, f"/tours/{n}")
        assert [e["genre"] for e in tour["elements"]].count("notes_block") == 0


def test_l_element_integral_et_les_erreurs_404(client):
    tour = _get(client, "/tours/2")
    i = tour["diff"]["rupture"]
    assert NOTE_2 in _get(client, f"/tours/2/elements/{i}")["texte"]
    assert client.get(f"/api/enquete/{AGENT}/tours/99").status_code == 404
    assert client.get(f"/api/enquete/{AGENT}/tours/2/elements/99").status_code == 404
    assert client.get("/api/enquete/inconnu/frise").status_code == 404


def test_l_histoire_de_la_note_montre_ajouts_et_compaction(client):
    histoire = _get(client, "/methodologie")
    assert [p["tour"] for p in histoire["courbe"]] == [1, 2, 3, 4]
    assert histoire["compactions"] == [3]
    t2 = next(e for e in histoire["entrees"] if e["tour"] == 2)
    assert "## Delta 2" in t2["ajoute"]
    filtre = _get(client, "/methodologie?q=delta 2")
    #  Le tour 2 l'a écrit, le tour 3 l'a fait disparaître en compactant.
    assert [(e["tour"], e["compaction"]) for e in filtre["entrees"]] == [(2, False), (3, True)]


def test_la_saturation_separe_prose_et_extraits_de_la_note(client):
    satur = _get(client, "/saturation?tour=2")
    t2 = next(s for s in satur["series"] if s["tour"] == 2)
    assert t2["note_extraits"] > t2["note_prose"] > 0
    assert satur["plus_gros"][0]["libelle"].startswith("Note › snippet")


def test_la_recherche_trouve_le_tour_de_l_erreur_sans_doublons(client):
    res = _get(client, "/recherche?q=traceback")["resultats"]
    assert {(r["tour"], r["ou"]) for r in res} == {(2, "resultat:Bash")}
    assert _get(client, "/recherche?q=a")["resultats"] == []
    prefixe = _get(client, "/recherche?q=règles de l'agent")["resultats"]
    assert [r["tour"] for r in prefixe if r["ou"] == "payload"] == [1, 4]


def test_export_et_page(client):
    resp = client.get(f"/api/enquete/{AGENT}/tours/3/export")
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]
    assert json.loads(resp.get_data(as_text=True))["turn"] == 3
    page = client.get(f"/enquete/{AGENT}")
    assert page.status_code == 200 and f'data-agent="{AGENT}"' in page.get_data(as_text=True)


def _espionner_lectures(monkeypatch):
    from bouzecode.backend.core import payload_view
    from bouzecode.web_v2.runtime.context_viewer import builder
    from bouzecode.web_v2.services.sessions import store
    compte = {"session": 0, "journal": 0}
    vraies = (builder._lire_session, store.load_session_json, payload_view.read_records)

    def session_builder(path):
        compte["session"] += 1
        return vraies[0](path)

    def session_store(path):
        compte["session"] += 1
        return vraies[1](path)

    def journal(*a, **k):
        compte["journal"] += 1
        return vraies[2](*a, **k)

    monkeypatch.setattr(builder, "_lire_session", session_builder)
    monkeypatch.setattr(store, "load_session_json", session_store)
    monkeypatch.setattr(payload_view, "read_records", journal)
    return compte


def test_l_enquete_lit_session_et_journal_une_seule_fois(client, monkeypatch):
    """Construire l'enquête : UNE lecture de la session et UNE du journal (avant : trois et
    deux) ; les requêtes suivantes n'en font plus aucune — avant, chacune décodait la session
    entière rien que pour calculer la clé du cache."""
    from bouzecode.web_v2.runtime.context_viewer import builder
    builder.oublier()
    compte = _espionner_lectures(monkeypatch)
    for _ in range(3):
        for chemin in ("/frise", "/saturation", "/saturation?tour=2", "/tours/2", "/methodologie"):
            _get(client, chemin)
    assert compte == {"session": 1, "journal": 1}


def test_un_tour_ajoute_au_journal_est_vu_par_l_enquete(client, tmp_path):
    import os
    avant = [t["tour"] for t in _get(client, "/frise")["tours"]]
    journal = tmp_path / "cfg" / "debug_payloads" / SID / "turns.jsonl"
    with journal.open("a", encoding="utf-8") as f:
        f.write("\n" + json.dumps({"turn": 5, "messages": [{"role": "user", "content": "encore"}]}))
    st = journal.stat()
    os.utime(journal, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10**9))
    assert [t["tour"] for t in _get(client, "/frise")["tours"]] == avant + [5]
