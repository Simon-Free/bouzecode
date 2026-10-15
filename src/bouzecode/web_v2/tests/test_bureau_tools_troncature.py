"""Le contrat que l'assistant du Bureau LIT : plafond expose, troncature nommee.

Defaut du 2026-09-09 (session `d7c83ee6`) : l'assistant demande `fenetre="30j"`, l'outil
`Mails` lui rend 50 mails couvrant TROIS jours en annonçant `"fenetre": "30j"`, et son
schema n'expose aucun autre parametre que `fenetre`. Resultat : une demande reelle
(« propose-moi des dates ») arrivee hors des 50 derniers mails n'a jamais existe pour
lui, et il n'avait aucun levier pour aller la chercher.

Ces tests verrouillent les deux moities du correctif au niveau ou le modele les voit :
le PARAMETRE pour creuser, et le MOT `tronque` dans la description qui lui dit quand.
"""

from bouzecode.backend.tools import bureau_tools


def _schema(nom: str) -> dict:
    for entree in bureau_tools.BUREAU_TOOL_SCHEMAS:
        if entree["name"] == nom:
            return entree
    raise AssertionError(f"outil {nom} absent des schemas du Bureau")


def test_l_outil_mails_expose_un_plafond_reglable():
    """Sans `top`, une reponse coupee est un cul-de-sac : rien a retenter."""
    schema = _schema("Mails")
    proprietes = schema["input_schema"]["properties"]

    assert "top" in proprietes, "l'assistant ne peut pas elargir une lecture plafonnee"
    assert proprietes["top"]["type"] == "integer"


def test_l_outil_teams_expose_aussi_un_plafond_reglable():
    proprietes = _schema("Teams")["input_schema"]["properties"]

    assert "top" in proprietes
    assert proprietes["top"]["type"] == "integer"
    #  Le retour a la source, deja present, reste le levier pour les messages rognes.
    assert "conversation_id" in proprietes


def test_les_descriptions_nomment_la_troncature_et_la_conduite_a_tenir():
    """Un plafond silencieux se comporte comme une absence de donnee : il faut le NOMMER."""
    for nom in ("Mails", "Teams"):
        description = _schema(nom)["description"]
        assert "tronque" in description, f"{nom} ne previent pas de la troncature"
        assert "top" in description, f"{nom} ne dit pas comment elargir la lecture"


def test_le_handler_mails_accepte_un_top():
    """Le schema promet `top` : le handler doit reellement le prendre."""
    import inspect

    assert "top" in inspect.signature(bureau_tools.mails).parameters
    assert "top" in inspect.signature(bureau_tools.teams).parameters
