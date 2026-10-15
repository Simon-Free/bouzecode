# [desc] Tests que l'outil Teams transmet bien son timeout et son transport injecté (schéma non mensonger) [/desc]
#
#  Defaut du 2026-09-21 : `Teams` avait gagne un parametre `timeout` dans son schema
#  (expose au modele) mais son corps ne s'en servait pas — les 90 s par defaut de
#  `graph_transport.DEFAULT_TIMEOUT` s'appliquaient quand meme. Un schema qui annonce
#  un reglage inoperant est un mensonge fait a l'assistant : il aurait relance avec
#  `timeout=300` et aurait rate au meme instant, sans comprendre pourquoi.
#
#  Aucun mock : on injecte un faux `powershell` (runner) exactement comme
#  `test_canaux_degradation.py`, et on espionne la construction du transport en
#  remplacant l'attribut de module (monkeypatch), pas en patchant du code interne.
import json

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import ms_activite


class _RunnerChats:
    """Faux `powershell` : memorise les arguments recus, rend une charge valide."""

    def __init__(self):
        self.args: list[str] = []

    def __call__(self, args):
        self.args = list(args)
        charge = {
            "value": [{"id": "19:abc", "sujet": "Point archi", "messages": [
                {"de": "Alice", "date": "2026-09-20T09:00:00Z", "texte": "coucou"}]}],
            "has_more": False,
        }
        return 0, json.dumps(charge), ""


def test_teams_mode_liste_utilise_le_transport_injecte():
    runner = _RunnerChats()
    transport = ms_activite.ActiviteTransport(runner=runner)

    reponse = bureau_tools.teams(fenetre="30j", transport=transport)

    assert reponse["ok"] is True
    assert runner.args[:2] == ["-Action", "chats"]


def test_teams_mode_conversation_utilise_le_transport_injecte():
    runner = _RunnerChats()
    transport = ms_activite.ActiviteTransport(runner=runner)

    reponse = bureau_tools.teams(fenetre="30j", conversation_id="19:abc",
                                 transport=transport)

    assert reponse["ok"] is True
    #  Le retour a la source passe par l'action `messages`, avec le meme pont.
    assert runner.args[:2] == ["-Action", "messages"]


def test_teams_transmet_le_timeout_demande(monkeypatch):
    """`timeout=300` doit arriver jusqu'au subprocess, sinon le schema ment."""
    vus: dict = {}
    vrai = ms_activite.ActiviteTransport

    class _Espion(vrai):  # type: ignore[valid-type,misc]
        def __init__(self, runner=None, timeout=None):
            vus["timeout"] = timeout
            super().__init__(runner=_RunnerChats(), timeout=timeout)

    monkeypatch.setattr(ms_activite, "ActiviteTransport", _Espion)

    reponse = bureau_tools.teams(fenetre="30j", timeout=300)

    assert vus["timeout"] == 300, "le timeout du schema n'atteint pas le transport"
    assert reponse["ok"] is True


def test_le_schema_teams_annonce_le_timeout():
    schema = next(s for s in bureau_tools.BUREAU_TOOL_SCHEMAS if s["name"] == "Teams")
    proprietes = schema["input_schema"]["properties"]
    assert "timeout" in proprietes, (
        "sans ce parametre, l'assistant ne peut PAS retenter plus longuement apres "
        "un timeout : il se rabat sur une fenetre plus courte sans le dire")
