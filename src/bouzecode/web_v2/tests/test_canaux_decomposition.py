"""Les canaux d'equipe se lisent EQUIPE PAR EQUIPE, et un timeout ne perd qu'une equipe.

Constat du 2026-09-21 (rapport de couverture rendu par l'assistant lui-meme) : « Canaux
d'equipe : PAS lus du tout -- 3 tentatives, 3 timeouts a 90s cote Graph ». Cause : UN seul
appel PowerShell couvrait toute la flotte (/me/joinedTeams -> N equipes -> N canaux ->
messages). Comme `subprocess.run(timeout=...)` TUE le process, un depassement ne laissait
RIEN : pas de partiel, pas de liste, rien a dire a l'humain.

Ces tests figent le correctif arbitre par l'humain : on decompose automatiquement en un
appel par equipe, et s'il en manque une, on rend ce qu'on a lu ET on nomme ce qui reste.

Aucun mock : le dépot injecte un faux `powershell` (`runner`) dans `ActiviteTransport`.
"""
from __future__ import annotations

import json
import subprocess

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import ms_activite


class _RunnerParEquipe:
    """Faux `powershell` sensible a l'ACTION et capable d'echouer sur UNE equipe.

    `-Action canaux -Since X -TeamId t2` arrive sous forme de paires : on les relit en
    dict. Lever `subprocess.TimeoutExpired` est fidele au vrai defaut : c'est exactement
    ce que `PowerShellTransport._call` traduit en `TeamsTransportError`.
    """

    def __init__(self, equipes: list[dict], canaux: dict[str, list[dict]],
                 echecs: set[str] | None = None):
        self.equipes = equipes
        self.canaux = canaux
        self.echecs = set(echecs or ())
        self.appels: list[dict] = []

    def __call__(self, args):
        paires = dict(zip(list(args)[::2], list(args)[1::2]))
        action = paires.get("-Action", "")
        self.appels.append(paires)
        if action in self.echecs:
            raise subprocess.TimeoutExpired("powershell", 90)
        if action == "equipes_ids":
            return 0, json.dumps({"value": self.equipes}), ""
        if action == "canaux":
            equipe_id = paires.get("-TeamId", "")
            if equipe_id in self.echecs:
                raise subprocess.TimeoutExpired("powershell", 90)
            if equipe_id:
                valeur = self.canaux.get(equipe_id, [])
            else:
                #  Appel GLOBAL (repli) : toutes les equipes d'un coup, comme avant.
                valeur = [canal for liste in self.canaux.values() for canal in liste]
            return 0, json.dumps({"value": valeur, "has_more": False}), ""
        return 0, json.dumps({"value": []}), ""

    def actions(self) -> list[str]:
        return [appel.get("-Action", "") for appel in self.appels]

    def equipes_demandees(self) -> list[str]:
        return [appel["-TeamId"] for appel in self.appels
                if appel.get("-Action") == "canaux" and appel.get("-TeamId")]


def _canal(equipe_id: str, equipe: str, canal: str, nb_messages: int = 1) -> dict:
    return {"id": f"{equipe_id}/19:{canal}", "equipe": equipe, "canal": canal,
            "messages": [{"de": "Quelqu'un", "texte": f"coucou {canal}"}] * nb_messages}


def _jeu_trois_equipes(echecs: set[str] | None = None):
    equipes = [{"id": "t1", "equipe": "Equipe Une"},
               {"id": "t2", "equipe": "Equipe Deux"},
               {"id": "t3", "equipe": "Equipe Trois"}]
    canaux = {
        "t1": [_canal("t1", "Equipe Une", "General")],
        "t2": [_canal("t2", "Equipe Deux", "Projets")],
        "t3": [_canal("t3", "Equipe Trois", "Veille")],
    }
    runner = _RunnerParEquipe(equipes, canaux, echecs=echecs)
    return runner, ms_activite.ActiviteTransport(runner=runner)


# --------------------------------------------------------------------------- #
#  1. La decomposition elle-meme
# --------------------------------------------------------------------------- #

def test_les_canaux_sont_lus_une_equipe_a_la_fois():
    runner, transport = _jeu_trois_equipes()

    rapport = ms_activite.rapport_canaux(fenetre="30j", transport=transport)

    #  Une amorce legere (1 requete /me/joinedTeams), puis UN appel par equipe.
    assert runner.actions().count("equipes_ids") == 1
    assert sorted(runner.equipes_demandees()) == ["t1", "t2", "t3"]
    assert rapport["ok"] is True
    assert rapport["total"] == 3
    assert sorted(canal["canal"] for canal in rapport["canaux"]) == [
        "General", "Projets", "Veille"]
    assert rapport["equipes_lues"] == 3
    assert rapport["equipes_non_lues"] == []


def test_un_canal_rendu_deux_fois_ne_compte_qu_une_fois():
    """Deux appels qui se recouvrent ne doivent pas gonfler le total."""
    equipes = [{"id": "t1", "equipe": "Equipe Une"}, {"id": "t2", "equipe": "Equipe Deux"}]
    partage = _canal("t1", "Equipe Une", "General")
    runner = _RunnerParEquipe(equipes, {"t1": [partage], "t2": [partage]})
    transport = ms_activite.ActiviteTransport(runner=runner)

    rapport = ms_activite.rapport_canaux(fenetre="30j", transport=transport)

    assert rapport["total"] == 1, "le dedoublonnage par id de canal manque"


# --------------------------------------------------------------------------- #
#  2. Le partiel EXISTE, et le reste est nomme (la demande de l'humain)
# --------------------------------------------------------------------------- #

def test_un_timeout_sur_une_equipe_ne_perd_que_cette_equipe():
    runner, transport = _jeu_trois_equipes(echecs={"t2"})

    rapport = ms_activite.rapport_canaux(fenetre="30j", transport=transport)

    #  On rend ce qu'on a : deux equipes sur trois.
    assert rapport["ok"] is True
    assert sorted(canal["canal"] for canal in rapport["canaux"]) == ["General", "Veille"]
    assert rapport["equipes_lues"] == 2
    #  Et on NOMME ce qui reste a faire, sinon l'humain croit la liste exhaustive.
    non_lues = rapport["equipes_non_lues"]
    assert [entree["equipe"] for entree in non_lues] == ["Equipe Deux"]
    assert non_lues[0]["raison"]
    assert "Equipe Deux" in rapport["avertissement"]


def test_l_alerte_de_couverture_ne_se_confond_pas_avec_celle_des_droits():
    """Trois causes distinctes de trou : droit manquant, budget, equipe non lue."""
    runner, transport = _jeu_trois_equipes(echecs={"t2"})

    rapport = ms_activite.rapport_canaux(fenetre="30j", transport=transport)

    assert rapport["messages_indisponibles"] is False
    #  L'avertissement parle d'equipe NON LUE, pas de consentement.
    assert "ChannelMessage.Read.All" not in rapport["avertissement"]


def test_si_l_amorce_echoue_on_retombe_sur_l_appel_global():
    """Ne jamais rendre moins qu'avant : sans la liste des equipes, on fait comme avant."""
    runner, transport = _jeu_trois_equipes(echecs={"equipes_ids"})

    rapport = ms_activite.rapport_canaux(fenetre="30j", transport=transport)

    assert rapport["ok"] is True
    assert rapport["total"] == 3
    #  Un appel `canaux` SANS -TeamId : le chemin monolithique d'origine.
    assert runner.equipes_demandees() == []
    assert "canaux" in runner.actions()


# --------------------------------------------------------------------------- #
#  3. Au point d'entree REEL : l'outil que l'assistant appelle
# --------------------------------------------------------------------------- #

def test_l_outil_canaux_rend_le_partiel_et_dit_quoi_faire():
    runner, transport = _jeu_trois_equipes(echecs={"t2"})

    reponse = bureau_tools.canaux(fenetre="30j", transport=transport)

    assert reponse["ok"] is True, "un timeout partiel ne doit plus rendre un echec nu"
    assert reponse["total"] == 2
    assert [entree["equipe"] for entree in reponse["equipes_non_lues"]] == ["Equipe Deux"]
    #  L'assistant doit savoir QUOI FAIRE : relancer avec un timeout plus grand.
    consigne = (reponse.get("consigne") or "") + reponse.get("avertissement", "")
    assert "timeout" in consigne.lower()


def test_l_outil_canaux_expose_un_timeout_reglable():
    schema = next(entree for entree in bureau_tools.BUREAU_TOOL_SCHEMAS
                  if entree.get("name") == "Canaux")
    assert "timeout" in schema["input_schema"]["properties"], (
        "sans timeout reglable, l'assistant ne peut que constater l'echec")


def test_le_timeout_demande_arrive_bien_au_transport(monkeypatch):
    """La plomberie existait (`ActiviteTransport(timeout=...)`) mais n'etait pas branchee."""
    vus: list[int | None] = []
    vrai = ms_activite.ActiviteTransport

    class _Espion(vrai):  # type: ignore[misc, valid-type]
        def __init__(self, runner=None, timeout=None):
            vus.append(timeout)
            runner_bidon = _RunnerParEquipe([], {})
            super().__init__(runner=runner_bidon, timeout=timeout)

    monkeypatch.setattr(ms_activite, "ActiviteTransport", _Espion)
    bureau_tools.canaux(fenetre="30j", timeout=300)

    assert 300 in vus, f"timeout non transmis au transport : {vus}"


def test_la_fenetre_par_defaut_de_l_activite_couvre_bien_trente_jours():
    """Le « rabattu sur 7 jours » du 2026-09-21 venait de ce defaut, pas d'un choix."""
    assert ms_activite.FENETRE_DEFAUT == "30j"
    assert bureau_tools.FENETRE_DEFAUT_ACTIVITE == "30j"

    runner, transport = _jeu_trois_equipes()
    reponse = bureau_tools.canaux(transport=transport)

    assert reponse["fenetre"] == "30j"
