"""Recherche par mot-cle dans Mails / Teams / Canaux.

L'utilisateur cherchait « le mail ZEN/CONDOR » en deroulant 200 apercus a l'oeil : aucun des
trois outils n'acceptait de mot-cle. Ces tests figent le contrat du parametre `recherche`, et
surtout son GARDE-FOU : filtrer apres coup ne doit jamais transformer `total` en mensonge, donc
`total_lus` garde le compte d'avant filtre et l'avertissement dit que la recherche n'a porte que
sur ce qui a ete lu.
"""
from __future__ import annotations

import inspect

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import ms_activite


def _schema(nom: str) -> dict:
    for entree in bureau_tools.BUREAU_TOOL_SCHEMAS:
        if entree.get("name") == nom:
            return entree
    raise AssertionError(f"outil {nom} absent de BUREAU_TOOL_SCHEMAS")


class FauxTransport:
    """Duck typing sur les seules methodes que les `rapport_*` appellent : aucun reseau,
    aucun mock de bibliotheque, et les plafonds restent ceux du vrai code."""

    def __init__(self, mails=None, chats=None, canaux=None, has_more=False):
        self._mails = mails or []
        self._chats = chats or []
        self._canaux = canaux or []
        self._has_more = has_more

    def mail_brut(self, depuis_iso: str, top: int = 50) -> dict:
        return {"mails": list(self._mails), "has_more": self._has_more}

    def chats_brut(self, depuis_iso: str, top: int = 30, messages: int = 20,
                   budget: int = 0) -> dict:
        return {"chats": list(self._chats), "has_more": self._has_more}

    def equipes_ids(self, top: int = 30, depuis_iso: str = "") -> list:
        #  Liste vide : `_amorcer_equipes` rend ([], "") et `rapport_canaux` retombe sur
        #  l'appel global `canaux_brut`, sans alerte d'amorce perdue a interpreter.
        return []

    def canaux_brut(self, depuis_iso: str, top: int = 30, messages: int = 20,
                    budget: int = 0) -> dict:
        return {"canaux": list(self._canaux), "has_more": self._has_more,
                "messages_indisponibles": False}


TROIS_MAILS = [
    {"id": "aaa", "subject": "Prequalification ZEN / CONDOR",
     "preview": "merci de lancer la prequalification", "sender": "yann@example.com"},
    {"id": "bbb", "subject": "Reunion de service",
     "preview": "ordre du jour joint", "sender": "rh@example.com"},
    {"id": "ccc", "subject": "CONDOR seulement",
     #  Ne contient PAS « zen » : ce mail sert a prouver le ET strict (il a CONDOR seul) et
     #  l'insensibilite aux accents (« reunion » doit etre trouve par « RÉUNION »).
     "preview": "aucune mention ici mais un accent : reunion", "sender": "x@example.com"},
]


# --- 1. surface : le parametre existe pour le modele -------------------------------------

def test_les_trois_outils_exposent_recherche():
    for nom in ("Mails", "Teams", "Canaux"):
        proprietes = _schema(nom)["input_schema"]["properties"]
        assert "recherche" in proprietes, f"{nom} n'expose pas `recherche`"
        assert proprietes["recherche"]["type"] == "string"


def test_description_recherche_avoue_la_limite():
    #  Promettre une recherche exhaustive sur un echantillon plafonne serait le defaut que
    #  tout ce module combat : la description doit dire que ca cherche dans ce qui a ete LU.
    for nom in ("Mails", "Teams", "Canaux"):
        texte = _schema(nom)["input_schema"]["properties"]["recherche"]["description"].lower()
        assert "lu" in texte or "plafond" in texte or "top" in texte


def test_schema_et_signature_concordent():
    #  `execute_tool` valide les params contre le schema AVANT dispatch : un `recherche`
    #  present d'un seul cote rendrait « unknown parameter » a l'usage.
    for nom, handler in (("Mails", bureau_tools.mails), ("Teams", bureau_tools.teams),
                         ("Canaux", bureau_tools.canaux)):
        parametres = inspect.signature(handler).parameters
        assert "recherche" in parametres, f"handler {nom} sans parametre recherche"
        assert parametres["recherche"].default == ""


# --- 2. comportement : mails ------------------------------------------------------------

def test_mails_tous_les_termes_exiges():
    rapport = ms_activite.rapport_mails(
        "30j", top=50, transport=FauxTransport(mails=TROIS_MAILS), recherche="zen condor")
    assert [mail["id"] for mail in rapport["mails"]] == ["aaa"]
    assert rapport["total"] == 1
    assert rapport["total_lus"] == 3
    assert rapport["recherche"] == "zen condor"


def test_mails_insensible_casse_et_accents():
    rapport = ms_activite.rapport_mails(
        "30j", top=50, transport=FauxTransport(mails=TROIS_MAILS), recherche="RÉUNION")
    trouves = {mail["id"] for mail in rapport["mails"]}
    assert trouves == {"bbb", "ccc"}


def test_mails_identifiant_ne_matche_pas():
    #  Un terme qui ne tombe que dans un id ou un lien n'est pas une correspondance :
    #  sinon un GUID contenant « zen » polluerait chaque recherche.
    mails = [{"id": "zen-42", "subject": "rien a voir", "webLink": "https://x/zen"}]
    rapport = ms_activite.rapport_mails(
        "30j", top=50, transport=FauxTransport(mails=mails), recherche="zen")
    assert rapport["mails"] == []
    assert rapport["total_lus"] == 1


def test_mails_sans_recherche_inchange():
    rapport = ms_activite.rapport_mails(
        "30j", top=50, transport=FauxTransport(mails=TROIS_MAILS))
    assert rapport["total"] == 3
    assert rapport["total_lus"] == 3
    assert rapport["recherche"] == ""
    assert "recherche" not in rapport["avertissement"].lower()


def test_mails_recherche_partielle_avouee_quand_tronque():
    rapport = ms_activite.rapport_mails(
        "30j", top=3, transport=FauxTransport(mails=TROIS_MAILS), recherche="zen")
    assert rapport["tronque"] is True, "plafond atteint : la troncature reste calculee sur les lus"
    assert "recherche" in rapport["avertissement"].lower()
    assert "3" in rapport["avertissement"]


# --- 3. comportement : chats et canaux --------------------------------------------------

TROIS_CHATS = [
    {"id": "c1", "topic": "Projet ZEN", "messages": [{"texte": "rien de special"}]},
    {"id": "c2", "topic": "Divers",
     "messages": [{"texte": "as-tu vu CONDOR ?"}, {"texte": "cafe ?"}]},
    {"id": "c3", "topic": "Autre", "messages": [{"texte": "bonjour"}]},
]


def test_chats_garde_par_topic_ou_par_message():
    rapport = ms_activite.rapport_chats(
        "30j", top=30, transport=FauxTransport(chats=TROIS_CHATS), recherche="zen")
    assert [chat["id"] for chat in rapport["conversations"]] == ["c1"]
    assert rapport["total_lus"] == 3

    rapport = ms_activite.rapport_chats(
        "30j", top=30, transport=FauxTransport(chats=TROIS_CHATS), recherche="condor")
    gardes = rapport["conversations"]
    assert [chat["id"] for chat in gardes] == ["c2"]
    #  Seuls les messages correspondants restent : on ne rend pas 20 messages hors sujet
    #  parce qu'un seul matchait.
    assert [message["texte"] for message in gardes[0]["messages"]] == ["as-tu vu CONDOR ?"]


def test_chats_sans_correspondance_rend_liste_vide():
    rapport = ms_activite.rapport_chats(
        "30j", top=30, transport=FauxTransport(chats=TROIS_CHATS), recherche="xyzzy")
    assert rapport["conversations"] == []
    assert rapport["total"] == 0
    assert rapport["total_lus"] == 3


def test_canaux_meme_regle_que_les_chats():
    canaux = [
        {"id": "k1", "canal": "General", "equipe": "SI",
         "messages": [{"texte": "audit ZEN a lancer"}, {"texte": "hors sujet"}]},
        {"id": "k2", "canal": "Veille", "equipe": "SI", "messages": [{"texte": "rien"}]},
    ]
    rapport = ms_activite.rapport_canaux(
        "30j", top=30, transport=FauxTransport(canaux=canaux), recherche="zen")
    gardes = rapport["canaux"]
    assert [canal["id"] for canal in gardes] == ["k1"]
    assert [message["texte"] for message in gardes[0]["messages"]] == ["audit ZEN a lancer"]
    assert rapport["total_lus"] == 2
