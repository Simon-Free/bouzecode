"""D'OÙ vient une ligne du Bureau : provenance technique d'une micro-tâche.

Mesuré le 2026-09-21 sur la base réelle (`~/.bouzecode/web_v2/tickets/tickets.db`) : sur 353
micro-tâches, 323 portent `origine='cloture_agent'` et 30 `origine='humain'`. Autrement dit
91 % du Bureau est rempli par des clôtures d'agents — et il était IMPOSSIBLE de savoir QUELLE
session avait produit une ligne : ni `micros` ni `tasks` ne portaient d'identifiant de session.
Retrouver l'auteur d'une ligne (« Recuperer son badge d'acces », fabriquée à partir d'un
message Teams d'un collègue) a demandé de corréler `task_events` à la SECONDE.

Ce que ces tests verrouillent : une vague de lignes ouvertes par une clôture d'agent est
retrouvable par son `session_id`, donc auditable et purgeable en bloc. Et l'absence de
provenance reste ABSENTE : on n'invente pas une valeur par défaut pour les lignes déjà en base.

Tout passe par le vrai service et la vraie base SQLite (fixture autouse
`_isolate_production_state` du conftest). Aucun mock.
"""
from bouzecode.web_v2.services.work import micros
from bouzecode.web_v2.services.work.cloture_micros import ouvrir_micros_de_cloture


def _cloture(monkeypatch, taches_restantes, session_id, ticket_id="", run_kind="work"):
    """Reproduit la clôture réelle d'un agent : c'est `_final_answer` qui tient le session_id,
    et la boucle qui, en acceptant la clôture, ouvre les suites."""
    from bouzecode.backend.tools.registration import (
        _final_answer, ouvrir_micros_de_cloture_acceptee,
    )

    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket_id)
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", "bouzecode")
    monkeypatch.setenv("BOUZECODE_RUN_KIND", run_kind)
    config = {"_state": type("S", (), {})(), "_session_id": session_id}
    sortie = _final_answer(
        "Livré.", config, taches_terminees=["fait"], taches_restantes=taches_restantes
    )
    ouvrir_micros_de_cloture_acceptee(config)
    return sortie


# --------------------------------------------------- 1. le pont écrit la provenance


def test_une_micro_ouverte_par_une_cloture_sait_de_quelle_session_elle_vient():
    creees = ouvrir_micros_de_cloture(
        [{"titre": "Recuperer son badge d'acces", "corps": "j'ai tj pas mon badge"}],
        ticket_id="",
        session_id="sess-badge",
    )

    provenance = micros.provenance_de(creees[0]["id"])
    assert provenance["session_id"] == "sess-badge"
    #  `source` est le point d'entrée TECHNIQUE, distinct de `origine` (lecture métier).
    assert provenance["source"] == "final_answer"
    assert provenance["at"]
    assert micros.get_micro(creees[0]["id"])["origine"] == "cloture_agent"


def test_la_vague_entiere_dune_session_est_retrouvable_en_bloc():
    """Le besoin exprimé : « purger ou auditer une vague entière »."""
    ouvrir_micros_de_cloture(
        [{"titre": "Casque a velo"}, {"titre": "Questionnaire Ipsos"}],
        session_id="parsing-teams",
    )
    ouvrir_micros_de_cloture([{"titre": "Autre chantier"}], session_id="une-autre-session")

    vague = micros.micros_de_session("parsing-teams")

    assert sorted(m["titre"] for m in vague) == ["Casque a velo", "Questionnaire Ipsos"]
    assert [m["titre"] for m in micros.micros_de_session("une-autre-session")] == [
        "Autre chantier"
    ]


# ------------------------------------------- 2. l'absence de provenance reste absente


def test_une_micro_saisie_a_la_main_na_aucune_provenance():
    """Les 353 lignes déjà en base n'ont pas de session connue : inventer une valeur par
    défaut mentirait. Pas de ligne dans `micro_provenance` = « on ne sait pas »."""
    micro = micros.create_micro(titre="Saisie humaine")

    assert micros.provenance_de(micro["id"]) == {}


def test_une_session_vide_ne_ramene_jamais_rien():
    """Garde-fou : si `micros_de_session('')` ramenait les lignes sans provenance, une purge
    par session vide effacerait tout le Bureau historique."""
    micros.create_micro(titre="Saisie humaine")
    ouvrir_micros_de_cloture([{"titre": "Sans session"}], session_id="")

    assert micros.micros_de_session("") == []
    assert micros.micros_de_session("   ") == []


def test_un_appel_sans_session_id_reste_accepte():
    """Compatibilité : `ouvrir_micros_de_cloture` était appelée sans session_id."""
    creees = ouvrir_micros_de_cloture([{"titre": "Ancien appel"}], ticket_id="T1")

    assert len(creees) == 1
    #  Le pont signe TOUJOURS sa source : « ligne de clôture, session inconnue » est une
    #  information, pas une absence. Et `session_id=''` ne peut pas être purgé par vague.
    provenance = micros.provenance_de(creees[0]["id"])
    assert provenance["source"] == "final_answer"
    assert provenance["session_id"] == ""
    assert micros.micros_de_session("") == []


# ------------------------------------------------- 3. bout en bout via FinalAnswer


def test_final_answer_estampille_la_session_qui_a_declare_les_restes(monkeypatch):
    _cloture(
        monkeypatch,
        [{"titre": "Reste a brancher le poller"}, {"titre": "Reste a documenter"}],
        session_id="S42",
    )

    vague = micros.micros_de_session("S42")

    assert sorted(m["titre"] for m in vague) == [
        "Reste a documenter",
        "Reste a brancher le poller",
    ][::-1]
    assert all(m["origine"] == "cloture_agent" for m in vague)
    assert {micros.provenance_de(m["id"])["source"] for m in vague} == {"final_answer"}


def test_une_cloture_sans_session_id_connu_ouvre_quand_meme_les_micros(monkeypatch):
    """Le pont ne doit jamais devenir dépendant de la provenance : une clôture sans
    `_session_id` (ancien état persisté, run hors boucle) ouvre ses lignes comme avant."""
    _cloture(monkeypatch, [{"titre": "Toujours ouvert"}], session_id="")

    filles = [m for m in micros.list_micros() if m["origine"] == "cloture_agent"]
    assert [m["titre"] for m in filles] == ["Toujours ouvert"]
    provenance = micros.provenance_de(filles[0]["id"])
    assert provenance["source"] == "final_answer"
    assert provenance["session_id"] == ""


# ------------------------------------------------------------- 4. écriture directe


def test_enregistrer_provenance_est_idempotent():
    micro = micros.create_micro(titre="Ligne")

    micros.enregistrer_provenance(micro["id"], session_id="S1", source="assistant")
    micros.enregistrer_provenance(micro["id"], session_id="S2", source="assistant")

    assert micros.provenance_de(micro["id"])["session_id"] == "S2"
    assert micros.micros_de_session("S1") == []
    assert [m["id"] for m in micros.micros_de_session("S2")] == [micro["id"]]


# ------------------------------------------------ 5. par le VRAI outil enregistré


def _outil(nom):
    """L'outil tel que la boucle l'appelle : `ToolDef.func(params, config)` du registre.

    Les tests ci-dessus appellent `_final_answer` DIRECTEMENT : ils restaient verts pendant
    que la table restait vide en production (Windows, 373 lignes, 0 provenance au 2026-09-23).
    La lambda d'enregistrement de FinalAnswer ne transmettait que `answer` et `recap` : les
    `taches_restantes` n'atteignaient jamais le pont, aucune ligne ne naissait d'une clôture.
    Seul un appel par le registre prouve le chemin réel."""
    from bouzecode.backend.core.tool_registry import get_tool
    from bouzecode.backend.tools import bureau_tools, registration  # noqa: F401 — enregistre
    bureau_tools.register()
    outil = get_tool(nom)
    assert outil is not None, f"{nom} absent du registre"
    return outil


def test_final_answer_appele_par_le_registre_estampille_sa_session(monkeypatch):
    from bouzecode.backend.tools.registration import ouvrir_micros_de_cloture_acceptee
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "work")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", "")
    config = {"_state": type("S", (), {})(), "_session_id": "sess-registre"}
    _outil("FinalAnswer").func({"answer": "Livré.", "taches_terminees": ["fait"],
                                "taches_restantes": '[{"titre": "Brancher le SSO"}]'}, config)
    ouvrir_micros_de_cloture_acceptee(config)

    assert [m["titre"] for m in micros.micros_de_session("sess-registre")] == ["Brancher le SSO"]


def test_une_tache_creee_par_l_assistant_porte_la_session_de_l_assistant():
    """L'assistant du Bureau fabrique des lignes à partir des mails et de Teams : c'est
    précisément celles-là qu'il faut pouvoir auditer et purger par vague."""
    r = _outil("Taches").func({"action": "creer", "titre": "Récupérer son badge d'accès"},
                              {"_session_id": "sess-assistant"})
    assert r["ok"], r

    provenance = micros.provenance_de(r["tache"]["id"])
    assert (provenance["session_id"], provenance["source"]) == ("sess-assistant", "assistant")
