"""L'assistant de pilotage du Bureau : ses outils font-ils vraiment le travail ?

Ces tests appellent les outils EXACTEMENT comme le runtime les appelle (une fonction,
un dict de paramètres), sans LLM et sans mock : la fixture autouse du conftest de
`web_v2/tests` redirige déjà le stockage vers un dossier temporaire.

Le test le plus important est le dernier : il vérifie que l'assistant ne peut PAS coder.
"""
import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.backend.tools.registration import enabled_tools_for_profile
from bouzecode.web_v2.services.work import decisions


PILOTAGE = ("ResteAFaire", "Taches", "Decisions", "Flotte", "LancerAgent")


@pytest.fixture(autouse=True)
def _outils_enregistres():
    """Les outils de pilotage ne sont pas des builtins : on les arme comme le fait
    un agent qui démarre sur le profil de l'assistant."""
    bureau_tools.register()


def test_reste_a_faire_respecte_la_fenetre_demandee():
    """« mes tickets des 2 derniers jours » = un paramètre, pas une extraction LLM."""
    rendu = bureau_tools.reste_a_faire(fenetre="2j")

    assert rendu["stats"]["fenetre"] == "2j"
    #  Les trois clés que l'assistant doit pouvoir raconter en français.
    assert set(("a_decider", "macros", "stats")) <= set(rendu)
    assert isinstance(rendu["a_decider"], list)
    assert isinstance(rendu["macros"], list)


def test_creer_lister_puis_clore_une_tache(monkeypatch):
    """Le cycle de vie complet d'une tâche, vu par l'assistant (mêmes objets que l'écran).

    `clore` passe par la route HTTP du serveur (elle arrête l'agent actif s'il y en a un) :
    on branche l'appel sur le client de test de la vraie app."""
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    monkeypatch.setattr(bureau_tools, "_http", lambda m, chemin, corps=None:
                        client.open(chemin, method=m, json=corps).get_json())
    cree = bureau_tools.taches(action="creer", titre="Rappeler le client")
    identifiant = cree["tache"]["id"]

    titres = [t["texte"] for t in bureau_tools.taches(action="lister")["taches"]]
    assert "Rappeler le client" in titres

    bureau_tools.taches(action="clore", task_id=identifiant, outcome="fait")

    encore = [t["id"] for t in bureau_tools.taches(action="lister")["taches"]]
    assert identifiant not in encore, "une tâche close ne fait plus partie du reste à faire"


def test_creer_une_tache_sans_titre_est_refuse():
    """Refus explicite plutôt qu'une tâche vide dans la todolist de l'humain."""
    rendu = bureau_tools.taches(action="creer", titre="   ")
    assert rendu.get("erreur")


def test_lister_puis_repondre_a_une_decision():
    """L'assistant doit pouvoir débloquer un agent sans passer par l'écran."""
    carte = decisions.upsert(
        source="test", situation="question", question="On garde l'ancien nom ?",
        options=[{"key": "oui", "label": "on garde", "consequence": "aucun renommage"},
                 {"key": "non", "label": "on renomme", "consequence": "il faudra migrer"}],
        recommended="oui", bloque="1 agent attend", reversible="réversible",
        defaut_si_silence="l'agent garde l'ancien nom",
    )

    ouvertes = bureau_tools.decisions(action="lister")["decisions"]
    assert carte["id"] in [d["id"] for d in ouvertes]

    rendu = bureau_tools.decisions(action="repondre", decision_id=carte["id"],
                                   answer_key="oui")
    assert rendu["decision"]["answered_at"]
    assert carte["id"] not in [d["id"] for d in bureau_tools.decisions(action="lister")["decisions"]]


def test_repondre_a_une_decision_inconnue_est_refuse():
    rendu = bureau_tools.decisions(action="repondre", decision_id="inexistante",
                                   answer_key="oui")
    assert rendu.get("erreur")


def test_flotte_rend_ce_qui_attend_et_ce_qui_tourne():
    """`Flotte` montre le haut du Bureau : « À traiter » et les tâches en cours — plus le
    store v1 `tasks`, que personne n'affiche (audit Bureau F-14)."""
    from bouzecode.web_v2.services.work import micros

    micros.create_micro(titre="Trancher le format de date", decision=True)
    rendu = bureau_tools.flotte()

    assert rendu["ok"] is True
    assert set(("a_traiter", "en_cours", "compte")) <= set(rendu)
    assert "Trancher le format de date" in [c["titre"] for c in rendu["a_traiter"]]


def test_lancer_un_agent_sans_consigne_est_refuse():
    """Un test ne lance JAMAIS un vrai agent : on vérifie le garde-fou d'entrée."""
    rendu = bureau_tools.lancer_agent(prompt="")
    assert rendu.get("erreur")


def test_action_inconnue_est_nommee():
    """Une action mal orthographiée doit se voir, pas échouer en silence."""
    assert bureau_tools.taches(action="supprimer").get("erreur")
    assert bureau_tools.decisions(action="ignorer").get("erreur")


def test_l_assistant_pilote_mais_ne_code_pas():
    """LE test du lot : le profil donne les 5 outils de pilotage, et RIEN pour écrire du code."""
    autorises = enabled_tools_for_profile("bureau-assistant")

    for outil in PILOTAGE:
        assert outil in autorises, f"l'assistant ne peut pas piloter sans {outil}"
    for interdit in ("Edit", "Write", "Bash"):
        assert interdit not in autorises, f"l'assistant ne doit pas pouvoir {interdit}"
