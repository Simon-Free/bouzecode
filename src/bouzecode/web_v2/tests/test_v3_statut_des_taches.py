"""SPEC v3 §1.2 / §4.6 — le Bureau dit, pour chaque tâche, où elle en est ET ce qu'ont fait ses
agents, sans que l'écran ait une seule règle à redériver.

On fabrique l'état RÉEL sur disque (fiche d'agent, session, IPC, question pendante, ticket relié
à la tâche) sous le parc isolé du conftest, puis on lit `GET /api/lignes` comme le front.
"""
import json
import os

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.work import micros, runs_ticket, tickets
from bouzecode.web_v2.tests.aides_tickets import constater_tout

SLUG = "demo"

FINAL_ANSWER = {
    "answer": "J'ai corrigé le login et ajouté deux tests.",
    "taches_terminees": ["corriger le login", "ajouter les tests"],
    "taches_restantes": [
        {"titre": "brancher le SSO", "macro_titre": "Auth"},
        {"titre": "garder l'ancien cookie ?", "decision": True, "macro_titre": "Auth"},
    ],
}


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def ecrire_agent(agent_id, *, vivant=False, ipc="finished", question=None, final=None,
                 close_reason="final_answer", ticket_id="", finished_at="2026-09-23T10:10:00Z",
                 tour_fini_a=None):
    """Une fiche d'agent + sa session + son IPC, comme le runner les écrit.

    `tour_fini_a` : instant (ISO) où le process a clos son dernier tour, écrit dans son IPC. Par
    défaut, celui de sa mort constatée (`finished_at`) : un process ne survit pas à sa fin."""
    parc = agent_fiche.AGENTS_DIR
    session = parc / f"{agent_id}.session.json"
    (parc / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": f"travail {agent_id}", "model": "m", "cwd": "/tmp",
        "pid": os.getpid() if vivant else 999_999_999,
        "started_at": "2026-09-23T10:00:00Z",
        "returncode": None if vivant else 0,
        "finished_at": "" if vivant else finished_at,
        "session_path": str(session), "stdout_path": str(parc / f"{agent_id}.out.log"),
        "ipc_dir": str(parc / f"{agent_id}.ipc"),
        "ticket_slug": SLUG if ticket_id else "", "ticket_id": ticket_id,
    }), encoding="utf-8")
    messages = [{"role": "user", "content": "go"}]
    if final:
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": "f1", "name": "FinalAnswer", "input": final}]})
    session.write_text(json.dumps({"messages": messages, "close_reason": close_reason,
                                   "final_answer": (final or {}).get("answer", "")}),
                       encoding="utf-8")
    (parc / f"{agent_id}.ipc").mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    fin_du_tour = tour_fini_a or ("" if vivant else finished_at)
    etat_ipc = {"status": ipc, "turn": 3, "updated_at": datetime.fromisoformat(
        fin_du_tour.replace("Z", "+00:00")).timestamp() if fin_du_tour else 1.0}
    if question is not None:
        #  Pause CHAUDE : le process écrit la question dans son IPC (cf. store.agent_status).
        etat_ipc.update(question=question, options=[{"label": "ISO"}, {"label": "Locale"}])
    (parc / f"{agent_id}.ipc" / "state.json").write_text(json.dumps(etat_ipc), encoding="utf-8")
    if question is not None:
        (parc / f"{agent_id}.session.json.pending.json").write_text(json.dumps({
            "ask_tc_id": "a1", "question": question,
            "options": [{"label": "ISO"}, {"label": "Locale"}], "allow_freetext": True,
            "completed_results": {}, "pending_tcs": []}), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()
    #  Le statut d'un agent est mémorisé par process (store._status_cache) : réécrire sa fiche
    #  sans l'oublier laissait un test voir le statut écrit par un test précédent du même worker.
    from bouzecode.web_v2.services.sessions import store
    store.invalidate_status(agent_id)


def tache_lancee(titre, agent_id=None, echec_de_lancement="", en_preparation=False):
    """Une tâche passée « lancée », reliée à un ticket (et à son run de travail, ou à un
    lancement en préparation / échoué)."""
    from bouzecode.web_v2.services.work import dispatch
    micro = micros.create_micro(titre=titre)
    ticket = tickets.create_ticket(SLUG, titre, titre)
    if agent_id or echec_de_lancement or en_preparation:
        tickets.set_launching(SLUG, ticket)
    if agent_id:
        tickets.add_run(SLUG, ticket, agent_id, "work", "m")
    if echec_de_lancement:
        dispatch.record_launch_failure(SLUG, ticket, echec_de_lancement)
    micros.lier_ticket(micro["id"], slug=SLUG, ticket_id=ticket["id"])
    micros.marquer_etat(micro["id"], "lancee")
    return micro["id"], ticket["id"]


def ligne(client, micro_id):
    """La ligne COMPLÈTE (passages, récap, rapport) : la liste par défaut est allégée depuis le
    2026-09-29 et ne sert ces champs que pour une tâche dépliée (`?complet=1` / `?detail=`).
    Le watchdog a constaté ce que les agents ont fait avant qu'on regarde (lot L2)."""
    constater_tout()
    vue = client.get("/api/lignes?complet=1").get_json()
    for l in [x for c in vue["chantiers"] for x in c["lignes"]] + vue["non_rattachees"]:
        if l["id"] == micro_id:
            return l
    raise AssertionError(f"tâche {micro_id} absente de /api/lignes")


def test_un_brouillon_est_un_brouillon(client):
    micro = micros.create_micro(titre="écrire la doc")
    l = ligne(client, micro["id"])
    assert (l["statut_ui"], l["libelle_statut"], l["segment"]) == \
        ("brouillon", "À lancer", "a_lancer")
    assert l["passages"] == [] and l["joignable"] is False and l["agent_actif"] is False


def test_une_decision_laissee_par_un_agent_est_a_decider_dans_a_moi(client):
    micro = micros.create_micro(titre="garder l'ancien cookie ?", decision=True)
    l = ligne(client, micro["id"])
    assert (l["statut_ui"], l["segment"]) == ("a_decider", "a_moi")
    assert (l["motif"], l["categorie"], l["libelle_statut"]) == ("point", "decider", "À décider")
    assert "decision_source" not in l, "créée à la main : aucune FinalAnswer à montrer"


def test_une_decision_laissee_a_la_cloture_renvoie_a_la_final_answer_de_l_agent(client):
    from bouzecode.web_v2.services.work import suites_cloture
    ecrire_agent("d1e2c3d4e5f6", final=FINAL_ANSWER)
    _, ticket_id = tache_lancee("corriger le login", "d1e2c3d4e5f6")
    decision = micros.create_micro(titre="garder l'ancien cookie ?", decision=True)
    suites_cloture.lier(ticket_id, "garder l'ancien cookie ?", decision["id"], "creee")
    l = ligne(client, decision["id"])
    assert l["statut_ui"] == "a_decider"
    source = l["decision_source"]
    assert source["ticket_id"] == ticket_id and source["agent_id"] == "d1e2c3d4e5f6"
    assert "corrigé le login" in source["resume"]
    assert "corrigé le login" in source["rapport_html"]


def test_un_passage_fini_est_a_relire_avec_son_recap(client):
    ecrire_agent("a1b2c3d4e5f6", final=FINAL_ANSWER)
    micro_id, ticket_id = tache_lancee("corriger le login", "a1b2c3d4e5f6")
    l = ligne(client, micro_id)
    assert l["statut_ui"] == "a_relire" and l["segment"] == "a_moi"
    [passage] = l["passages"]
    assert passage["ticket_id"] == ticket_id and passage["agent_id"] == "a1b2c3d4e5f6"
    assert passage["etat"] == "finished" and passage["libelle_etat"] == "Terminé"
    assert passage["recap"]["fait"] == ["corriger le login", "ajouter les tests"]
    assert passage["recap"]["reste"] == ["brancher le SSO"]
    assert passage["recap"]["a_decider"] == ["garder l'ancien cookie ?"]
    assert "corrigé le login" in passage["recap"]["resume"]
    assert passage["joignable"] is True, "la session existe : on peut lui renvoyer un retour"


def test_une_final_answer_arrivee_en_texte_json_se_lit_comme_une_vraie(client):
    """Protocole XML : les paramètres liste / objet de FinalAnswer sont stockés en TEXTE JSON
    dans la session. Relus bruts, la liste était découpée caractère par caractère et un
    `recap` « {} » faisait planter tout /api/lignes (500 sur le Bureau entier)."""
    en_texte = {"answer": "Délégation faite.",
                "taches_terminees": json.dumps(["déléguer le lot A"]),
                "taches_restantes": json.dumps([{"titre": "relire le lot B", "decision": True}]),
                "recap": "{}"}
    ecrire_agent("0a1b2c3d4e5f", final=en_texte)
    micro_id, _ = tache_lancee("déléguer", "0a1b2c3d4e5f")
    assert client.get("/api/lignes").status_code == 200
    [passage] = ligne(client, micro_id)["passages"]
    assert passage["recap"]["fait"] == ["déléguer le lot A"]
    assert passage["recap"]["a_decider"] == ["relire le lot B"]


def test_une_tache_qui_a_delegue_reste_en_cours_tant_qu_un_sous_agent_travaille(client):
    """Un agent (profil ordinaire, pas « manager ») rend la main après avoir lancé des
    sous-agents : sa tâche n'est PAS « À relire » tant qu'un sous-agent se prépare ou travaille
    — son ticket reste `running{attend_enfants}` jusqu'à son réveil."""
    ecrire_agent("5a5a5a5a5a5a", final={"answer": "Sous-agents lancés, j'attends."})
    micro_id, parent_id = tache_lancee("déléguer deux lots", "5a5a5a5a5a5a")
    enfant = tickets.create_ticket(SLUG, "lot A", "lot A")
    tickets.poser(SLUG, enfant, parent="5a5a5a5a5a5a")
    tickets.set_launching(SLUG, enfant)
    l = ligne(client, micro_id)
    assert (l["statut_ui"], l["passages"][0]["etat"]) == ("en_cours", "orchestrating")

    ecrire_agent("6b6b6b6b6b6b", vivant=True, ipc="running", ticket_id=enfant["id"])
    tickets.add_run(SLUG, enfant, "6b6b6b6b6b6b", "work", "m")
    assert ligne(client, micro_id)["statut_ui"] == "en_cours"

    #  L'enfant finit : le parent ne l'a pas encore relu (il le sera à son réveil) — la tâche
    #  ne clignote pas « À relire » en attendant.
    ecrire_agent("6b6b6b6b6b6b", ticket_id=enfant["id"], final={"answer": "lot A fait"},
                 finished_at="2026-09-23T10:20:00Z")
    assert ligne(client, micro_id)["statut_ui"] == "en_cours"

    #  Réveillé (reprise : `running`), le parent conclut après son enfant : c'est à relire.
    runs_ticket.signaler(SLUG, parent_id, "5a5a5a5a5a5a", "message")
    ecrire_agent("5a5a5a5a5a5a", final={"answer": "Lots relus et intégrés."},
                 finished_at="2026-09-23T10:30:00Z")
    assert ligne(client, micro_id)["statut_ui"] == "a_relire"


def test_une_question_d_agent_remonte_avec_ses_options(client):
    ecrire_agent("b1b2c3d4e5f6", vivant=True, ipc="awaiting_input",
                 question="Quel format de date ?")
    micro_id, _ = tache_lancee("migrer les dates", "b1b2c3d4e5f6")
    l = ligne(client, micro_id)
    assert l["statut_ui"] == "a_repondre" and l["libelle_statut"] == "Attend ta réponse"
    assert l["question"]["question"] == "Quel format de date ?"
    assert [o["label"] for o in l["question"]["options"]] == ["ISO", "Locale"]
    assert l["question"]["agent_id"] == "b1b2c3d4e5f6"
    assert l["agent_actif"] is True


def test_un_agent_qui_tourne_est_en_cours(client):
    ecrire_agent("c1b2c3d4e5f6", vivant=True, ipc="running")
    micro_id, _ = tache_lancee("refacto", "c1b2c3d4e5f6")
    l = ligne(client, micro_id)
    assert l["statut_ui"] == "en_cours" and l["segment"] == "en_cours"
    #  « Le modèle lit ta demande… » tant qu'aucun token n'est arrivé, puis « En cours ».
    assert l["passages"][0]["etat"] in ("running", "thinking")
    assert l["agent_actif"] is True


def test_un_agent_mort_sans_reponse_finale_met_la_tache_en_echec(client):
    ecrire_agent("d1b2c3d4e5f6", close_reason="api_error")
    micro_id, _ = tache_lancee("refacto X", "d1b2c3d4e5f6")
    l = ligne(client, micro_id)
    assert l["statut_ui"] == "en_echec"
    assert l["passages"][0]["etat"] == "crashed"
    assert l["raison_echec"], "un échec doit dire pourquoi"


def test_un_lancement_echoue_met_la_tache_en_echec_avec_la_raison(client):
    micro_id, _ = tache_lancee("lancer ça", echec_de_lancement="git worktree add a échoué")
    l = ligne(client, micro_id)
    assert l["statut_ui"] == "en_echec"
    assert l["passages"][0]["etat"] == "launch_failed"
    assert "git worktree add a échoué" in l["raison_echec"]


def test_un_lancement_en_preparation_est_en_cours(client):
    micro_id, ticket_id = tache_lancee("préparer", en_preparation=True)
    l = ligne(client, micro_id)
    assert l["statut_ui"] == "en_cours"
    assert l["passages"][0]["etat"] == "preparing"
    assert l["passages"][0]["launch_key"] == f"launching/{ticket_id}"


def test_les_taches_urgentes_passent_devant(client):
    micros.create_micro(titre="un brouillon")
    ecrire_agent("e1b2c3d4e5f6", vivant=True, ipc="awaiting_input", question="?")
    tache_lancee("une question", "e1b2c3d4e5f6")
    constater_tout()
    vue = client.get("/api/lignes").get_json()
    ordre = [l["statut_ui"] for l in vue["non_rattachees"]]
    assert ordre == ["a_repondre", "brouillon"]
    assert vue["stats"]["compte_ui"]["segments"]["a_moi"] == 1


def test_le_depot_par_defaut_vient_du_chantier(client):
    macro = micros.create_macro("DEMODB", projets=["demo_ingestion", "demo_monorepo"])
    micro = micros.create_micro(titre="t", macro_id=macro["id"])
    assert ligne(client, micro["id"])["projet_defaut"] == "demo_ingestion"
    micros.update_micro(micro["id"], projet_slug="autre")
    assert ligne(client, micro["id"])["projet_defaut"] == "autre"


def test_un_seul_champ_le_titre_suit_toujours_le_brief(client):
    """Brief seul (demande du 2026-09-24) : éditer le brief recalcule le titre, même posé à la main
    par un agent ; seul un appel qui envoie `titre` le fixe. Créer avec `corps` seul suffit."""
    micro = micros.create_micro(titre="Migrer demo_table", corps="détails")
    micros.update_micro(micro["id"], corps="Migrer demo_table vers Delta\n\nLa table est alimentée par…")
    assert micros.get_micro(micro["id"])["titre"] == "Migrer demo_table vers Delta"
    cree = client.post("/api/micros", json={"corps": "## Nouvelle tâche\nle détail"})
    assert cree.status_code == 201, cree.get_data(as_text=True)
    assert cree.get_json()["micro"]["titre"] == "Nouvelle tâche"
    fixe = micros.update_micro(micro["id"], titre="Titre imposé", corps="autre chose")
    assert fixe["titre"] == "Titre imposé"


def test_le_rapport_d_un_passage_fini_est_rendu_en_html_sans_html_de_l_agent(client):
    """Un rapport EST du markdown : il s'affiche rendu (titres, listes, gras), et le HTML
    qu'un agent écrirait ressort neutralisé (condition d'un innerHTML côté écran)."""
    final = {**FINAL_ANSWER,
             "answer": "## Resultat\n- premier point\n\n**mot** <script>alert(1)</script>"}
    ecrire_agent("f1b2c3d4e5f6", final=final)
    micro_id, _ = tache_lancee("rendre le rapport", "f1b2c3d4e5f6")
    html = ligne(client, micro_id)["passages"][0]["rapport_html"]
    assert "<h2>Resultat</h2>" in html and "<li>premier point</li>" in html
    assert "<strong>mot</strong>" in html and "## Resultat" not in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_c_est_le_dernier_passage_qui_decide_du_statut_et_du_recap(client):
    """Un passage relancé après coup ne fait pas remonter le récap d'avant : le passage le
    plus récent vient en tête, et c'est lui qui dit où en est la tâche."""
    ecrire_agent("a2b2c3d4e5f6", final={**FINAL_ANSWER, "answer": "ancien rapport"})
    micro_id, _ = tache_lancee("deux passages", "a2b2c3d4e5f6")
    ticket2 = tickets.create_ticket(SLUG, "deux passages", "p")
    ecrire_agent("a3b2c3d4e5f6", vivant=True, ipc="running")
    tickets.add_run(SLUG, ticket2, "a3b2c3d4e5f6", "work", "m")
    micros.lier_ticket(micro_id, slug=SLUG, ticket_id=ticket2["id"])
    l = ligne(client, micro_id)
    assert [p["numero"] for p in l["passages"]] == [2, 1]
    assert l["statut_ui"] == "en_cours" and l["passages"][0]["recap"]["resume"] == ""
    assert "ancien rapport" in l["passages"][1]["recap"]["resume"]

def test_un_etat_de_run_perime_en_base_ne_prime_jamais_sur_l_agent_reel(client):
    """Bug du 08/09 : une tâche basculait « à relire » pendant que son agent travaillait,
    parce qu'un `state` figé en base était pris pour l'état de l'agent."""
    ecrire_agent("a4b2c3d4e5f6", vivant=True, ipc="running")
    micro_id, ticket_id = tache_lancee("encore en cours", "a4b2c3d4e5f6")
    ticket = tickets.get_ticket(SLUG, ticket_id)
    ticket["runs"][0]["state"] = "finished"
    tickets.update_ticket(SLUG, ticket)
    assert ligne(client, micro_id)["statut_ui"] == "en_cours"


# ------------------------------------------------------------ ce que l'utilisateur doit faire


def _motif(client, micro_id):
    l = ligne(client, micro_id)
    return l["motif"], l["categorie"]


def test_une_question_ou_un_plan_sont_des_decisions_a_prendre(client):
    ecrire_agent("a7b2c3d4e5f6", vivant=True, ipc="awaiting_input", question="ISO ?")
    question, _ = tache_lancee("dates", "a7b2c3d4e5f6")
    ecrire_agent("a8b2c3d4e5f6", vivant=True, ipc="awaiting_plan_validation", question="Valider le plan ?")
    plan, _ = tache_lancee("plan", "a8b2c3d4e5f6")
    assert _motif(client, question) == ("question", "decider")
    assert _motif(client, plan) == ("plan", "decider")


def test_une_reponse_finale_rendue_est_a_verifier(client):
    ecrire_agent("a9b2c3d4e5f6", final=FINAL_ANSWER)
    micro_id, _ = tache_lancee("livrer", "a9b2c3d4e5f6")
    l = ligne(client, micro_id)
    assert (l["motif"], l["categorie"], l["libelle_statut"]) == ("livraison", "verifier", "À vérifier")


def test_un_plantage_un_arret_voulu_et_un_lancement_rate_ne_demandent_pas_le_meme_geste(client):
    ecrire_agent("aab2c3d4e5f6", close_reason="api_error")
    plante, _ = tache_lancee("plante", "aab2c3d4e5f6")
    ecrire_agent("abb2c3d4e5f6", close_reason="killed")
    etat = agent_fiche.AGENTS_DIR / "abb2c3d4e5f6.ipc" / "state.json"
    etat.write_text(json.dumps({"status": "finished", "updated_at": 2.0, "killed_by": "server"}), encoding="utf-8")
    arrete, ticket_arrete = tache_lancee("arrêtée", "abb2c3d4e5f6")
    runs_ticket.signaler(SLUG, ticket_arrete, "abb2c3d4e5f6", "arret")  # tué par le serveur
    rate, _ = tache_lancee("ratée", echec_de_lancement="dépôt inconnu")
    assert _motif(client, plante) == ("plante", "reprendre")
    assert _motif(client, arrete) == ("arrete", "reprendre")
    assert _motif(client, rate) == ("lancement", "debloquer")


def test_une_tache_qui_n_attend_rien_n_a_pas_de_motif(client):
    brouillon = micros.create_micro(titre="plus tard")
    ecrire_agent("acb2c3d4e5f6", vivant=True, ipc="running")
    en_cours, _ = tache_lancee("tourne", "acb2c3d4e5f6")
    assert _motif(client, brouillon["id"]) == ("", "")
    assert _motif(client, en_cours) == ("", "")


@pytest.mark.parametrize("statut, passages, motif", [
    ("en_echec", [{"etat": "missing"}], "introuvable"),
    ("en_echec", [], "introuvable"),
    ("en_echec", [{"etat": "launch_failed",
                   "raison_echec": "Lancement échoué : arrêté à ta demande pendant la préparation"}], "arrete"),
])
def test_les_cas_rares_ont_aussi_leur_motif(statut, passages, motif):
    from bouzecode.web_v2.services.work import lexique
    assert lexique.motif_attente(statut, passages) == motif


def test_la_boite_a_traiter_porte_le_motif_de_chaque_point(client):
    micros.create_micro(titre="choisir le format", decision=True)
    ecrire_agent("adb2c3d4e5f6", vivant=True, ipc="awaiting_input", question="hors tâche ?")
    items = client.get("/api/inbox").get_json()["items"]
    par_titre = {c["titre"]: (c["motif"], c["categorie"]) for c in items}
    assert par_titre["choisir le format"] == ("point", "decider")
    libre = next(c for c in items if c["agent_id"] == "adb2c3d4e5f6")
    assert (libre["motif"], libre["categorie"], libre["tache"]) == ("question", "decider", None)


def _brouillon_avec_passage(titre, agent_id):
    """Une tâche restée `brouillon` alors qu'un ticket y est relié (tâche v1 migrée avec ses
    tickets, origine `cloture_agent`) : l'état écrit ne dit rien, c'est le passage qui parle."""
    micro = micros.create_micro(titre=titre, origine="cloture_agent")
    ticket = tickets.create_ticket(SLUG, titre, titre)
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, agent_id, "work", "m")
    micros.lier_ticket(micro["id"], slug=SLUG, ticket_id=ticket["id"])
    assert micros.get_micro(micro["id"])["etat"] == "brouillon"
    return micro["id"]


def test_un_brouillon_dont_le_passage_a_fini_est_a_verifier_pas_a_lancer(client):
    ecrire_agent("b0b2c3d4e5f6", final=FINAL_ANSWER)
    micro_id = _brouillon_avec_passage("migrée et livrée", "b0b2c3d4e5f6")
    l = ligne(client, micro_id)
    assert (l["statut_ui"], l["segment"]) == ("a_relire", "a_moi"), \
        "un agent a livré : « Brouillon » dans « À lancer » avec un bouton Lancer ment"


def test_un_brouillon_dont_le_passage_a_plante_est_en_echec_et_compte(client):
    ecrire_agent("b1b2c3d4e5f6", close_reason="api_error")
    micro_id = _brouillon_avec_passage("migrée et plantée", "b1b2c3d4e5f6")
    l = ligne(client, micro_id)
    assert l["statut_ui"] == "en_echec" and l["raison_echec"]
    from bouzecode.web_v2.services.work import taches_vue
    assert taches_vue.compte_ui([l])["en_echec"] == 1, "le compteur « en échec » la compte"


def test_un_brouillon_rouvert_apres_classement_reste_un_brouillon(client):
    """Rouvrir une tâche classée est un geste explicite : ses vieux passages ne la
    ramènent pas « À vérifier »."""
    ecrire_agent("b2b2c3d4e5f6", final=FINAL_ANSWER)
    micro_id = _brouillon_avec_passage("classée puis rouverte", "b2b2c3d4e5f6")
    constater_tout()  # l'agent a livré : plus aucun passage actif
    assert client.post(f"/api/micros/{micro_id}/etat",
                       json={"etat": "faite", "motif": "doublon"}).status_code == 200
    assert client.post(f"/api/micros/{micro_id}/etat", json={"etat": "brouillon"}).status_code == 200
    assert ligne(client, micro_id)["statut_ui"] == "brouillon"


def test_une_premiere_ligne_trop_longue_donne_un_titre_coupe_sans_doubler_le_brief(client):
    longue = "Analyser le flux " + "x" * 130
    cree = client.post("/api/micros", json={"corps": f"{longue}\nDeuxième ligne"}).get_json()["micro"]
    assert cree["titre"] == longue[:119] + "…"  # coupe marquée, jamais silencieuse
    assert cree["corps"] == f"{longue}\nDeuxième ligne", "le brief reste tel quel"


def test_vider_le_brief_vide_aussi_le_titre(client):
    """Vider le brief ne ramène pas l'ancien titre (l'écran l'affichait en tête du brief)."""
    micro = micros.create_micro(titre="Ancien titre", corps="Ancien titre\nancien détail")
    r = client.patch(f"/api/micros/{micro['id']}", json={"corps": ""})
    assert r.status_code == 200, r.get_data(as_text=True)
    vue = r.get_json()["micro"]
    assert (vue["titre"], vue["corps"]) == ("", "")
    lancer = client.post(f"/api/micros/{micro['id']}/lancer")
    assert lancer.get_json()["error"]["code"] == "titre_requis"
