# [desc] Le magasin des décisions du Bureau : dédup, invariants I1-I4, comptage par tâche. [/desc]
"""Ce que la table `decisions` doit garantir (SPEC_BUREAU_WEBV2 §4.2).

Aucune fixture ici : `tests/conftest.py` porte l'autouse `_isolate_production_state`
qui redirige `_persistence.TICKETS_DIR` vers un `tmp_path`, et `decisions._tx()`
ré-dérive `_db_path()` à chaque bloc — chaque test a donc sa vraie base SQLite
neuve. Vraie base, vrai SQL, zéro mock.
"""
from __future__ import annotations

from bouzecode.web_v2.services.work import decisions


def _ask(**over):
    """Une question d'agent en attente, telle que l'ingest la posera."""
    champs = dict(
        source="agent_question",
        situation="agent_question",
        question="Faut-il intégrer la branche ?",
        asked_at="2026-08-25T10:00:00",
        task_id="t-1",
        project_slug="demo",
        ticket_id="tk-1",
        agent_id="ag-1",
        context="22 commits non intégrés",
        options=[{"key": "integrer", "label": "Intégrer"},
                 {"key": "abandonner", "label": "Abandonner"}],
        allow_freetext=True,
        recommended="integrer",
        urgency=1,
    )
    champs.update(over)
    source = champs.pop("source")
    situation = champs.pop("situation")
    question = champs.pop("question")
    return decisions.upsert(source, situation, question, **champs)


def test_upsert_pose_une_carte_lisible_et_la_relit_par_id():
    row = _ask()
    assert row["created"] is True
    assert row["urgency"] == 1
    assert row["answered_at"] == ""
    #  `_options` normalise TOUTE option en `key`+`label`+`consequence` : une question posée
    #  sans conséquence ressort avec une conséquence VIDE, visible comme un manque (`_manque`
    #  la signale) plutôt que silencieusement perdue. Le test suit ce contrat.
    assert row["options"] == [{"key": "integrer", "label": "Intégrer", "consequence": ""},
                              {"key": "abandonner", "label": "Abandonner", "consequence": ""}]
    assert row["allow_freetext"] is True
    relu = decisions.get(row["id"])
    assert relu["question"] == "Faut-il intégrer la branche ?"
    assert relu["recommended"] == "integrer"


def test_le_meme_tick_rejoue_ne_duplique_pas_la_carte():
    """Le watchdog rejoue toutes les 8 s : deux cartes = un Bureau illisible."""
    premier = _ask()
    second = _ask(context="23 commits non intégrés", urgency=2)
    assert second["created"] is False
    assert second["id"] == premier["id"]
    assert second["context"] == "23 commits non intégrés"  # volatile : rafraîchi
    assert second["urgency"] == 2
    assert len(decisions.open_decisions()) == 1


def test_une_situation_derivee_ne_se_duplique_pas_quand_l_heure_bouge():
    """`bucket=""` : la carte d'une situation dérivée est UNE par (situation, ticket),
    même si `asked_at` est recalculé à chaque tick."""
    _ask(situation="uncommitted_work", source="situation", asked_at="2026-08-25T10:00:00", bucket="")
    _ask(situation="uncommitted_work", source="situation", asked_at="2026-08-25T10:00:08", bucket="")
    assert len(decisions.open_decisions()) == 1


def test_deux_tickets_distincts_ont_deux_cartes():
    _ask(ticket_id="tk-1", agent_id="ag-1")
    _ask(ticket_id="tk-2", agent_id="ag-2")
    assert len(decisions.open_decisions()) == 2


def test_les_decisions_ouvertes_sortent_par_urgence_puis_anciennete():
    _ask(ticket_id="a", urgency=2, asked_at="2026-08-25T09:00:00")
    _ask(ticket_id="b", urgency=0, asked_at="2026-08-25T11:00:00")
    _ask(ticket_id="c", urgency=0, asked_at="2026-08-25T08:00:00")
    ordre = [d["ticket_id"] for d in decisions.open_decisions()]
    assert ordre == ["c", "b", "a"]


def test_repondre_ferme_la_carte_et_arme_la_livraison():
    """I4 : une réponse est en attente de livraison à l'agent, jamais perdue."""
    row = _ask()
    res = decisions.answer(row["id"], answer_key="integrer", answer_text="vas-y")
    assert res["status"] == "ok"
    assert res["decision"]["answer_key"] == "integrer"
    assert res["decision"]["answer_text"] == "vas-y"
    assert res["decision"]["answered_at"] != ""
    assert res["decision"]["delivery"] == "pending"
    assert res["decision"]["delivery_error"] == ""
    assert decisions.open_decisions() == []


def test_repondre_deux_fois_ne_reecrit_pas_la_premiere_reponse():
    row = _ask()
    decisions.answer(row["id"], answer_key="integrer")
    encore = decisions.answer(row["id"], answer_key="abandonner")
    assert encore["status"] == "already_answered"
    assert decisions.get(row["id"])["answer_key"] == "integrer"


def test_repondre_une_carte_inconnue_le_dit_au_lieu_de_planter():
    assert decisions.answer("nexiste-pas", answer_key="x")["status"] == "not_found"


def test_un_tick_ne_reecrit_jamais_une_carte_deja_repondue():
    """I2 : la réponse de l'humain est intouchable, même si la situation persiste."""
    row = _ask()
    decisions.answer(row["id"], answer_key="integrer", answer_text="vas-y")
    _ask(question="Question réécrite par le tick", urgency=3)
    relu = decisions.get(row["id"])
    assert relu["question"] == "Faut-il intégrer la branche ?"
    assert relu["urgency"] == 1
    assert relu["answer_key"] == "integrer"


def test_une_livraison_echouee_reste_visible_et_compte_ses_tentatives():
    """I3 : un échec de livraison ne disparaît pas en silence."""
    row = _ask()
    decisions.answer(row["id"], answer_key="integrer")
    decisions.mark_delivery(row["id"], "failed", error="agent_missing", bump_attempt=True)
    echecs = decisions.failed_deliveries()
    assert [d["id"] for d in echecs] == [row["id"]]
    assert echecs[0]["delivery_error"] == "agent_missing"
    assert echecs[0]["attempts"] == 1
    decisions.mark_delivery(row["id"], "delivered")
    assert decisions.failed_deliveries() == []


def test_une_reponse_livrable_est_reprise_tant_qu_elle_n_a_pas_epuise_ses_essais():
    row = _ask()
    decisions.answer(row["id"], answer_key="integrer")
    assert [d["id"] for d in decisions.pending_for_retry()] == [row["id"]]
    for _ in range(5):
        decisions.mark_delivery(row["id"], "pending", bump_attempt=True)
    assert decisions.pending_for_retry(max_attempts=5) == []


def test_une_question_devenue_sans_objet_est_classee_sans_etre_effacee():
    """I1 : on ne SUPPRIME jamais une décision, on la rend `moot` avec sa trace."""
    row = _ask()
    decisions.make_moot(row["id"], "agent mort avant la réponse")
    relu = decisions.get(row["id"])
    assert relu is not None
    assert relu["delivery"] == "moot"
    assert "agent mort" in relu["delivery_error"]
    assert decisions.open_decisions() == []


def test_classer_par_situation_touche_toutes_les_cartes_du_ticket():
    _ask(situation="uncommitted_work", ticket_id="tk-1", bucket="")
    _ask(situation="uncommitted_work", ticket_id="tk-2", bucket="")
    n = decisions.make_moot_where("uncommitted_work", "tk-1", "travail récolté entre-temps")
    assert n == 1
    restantes = [d["ticket_id"] for d in decisions.open_decisions()]
    assert restantes == ["tk-2"]


def test_une_situation_qui_revient_rouvre_la_carte_classee():
    """Un agent ressuscité repose sa question : la carte `moot` redevient à traiter."""
    row = _ask()
    decisions.make_moot(row["id"], "agent injoignable")
    revenue = _ask()
    assert revenue["id"] == row["id"]
    assert revenue["delivery"] == "pending"
    assert [d["id"] for d in decisions.open_decisions()] == [row["id"]]


def test_le_bureau_compte_les_decisions_ouvertes_par_tache():
    _ask(task_id="t-1", ticket_id="tk-1")
    _ask(task_id="t-1", ticket_id="tk-2")
    repondue = _ask(task_id="t-2", ticket_id="tk-3")
    decisions.answer(repondue["id"], answer_key="ok")
    assert decisions.count_open_by_task() == {"t-1": 2}


def test_la_table_se_cree_sans_broncher_a_chaque_ouverture():
    """Le SCHEMA est rejoué à chaque transaction : il doit être idempotent."""
    assert decisions.open_decisions() == []
    row = _ask()
    assert decisions.get(row["id"]) is not None
    assert decisions.count_open_by_task() == {"t-1": 1}
