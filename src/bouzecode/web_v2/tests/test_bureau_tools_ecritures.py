"""Les 3 outils d'ecriture du Bureau, vus du modele : ce qu'il recoit et ce qu'il peut.

Deux choses sont verrouillees ici :
1. Une panne n'est jamais un crash -- c'est une REPONSE nommee que l'agent peut lire
   et repeter a l'humain (meme contrat que `mails()`).
2. Les outils sont reellement ENVOYES AU MODELE pour un agent de /conversation
   (profil `default`). Mesure du 2026-09-21 : avant ce travail, ce profil recevait
   27 outils dont AUCUN outil Microsoft, parce que tout ce qui est hors
   `_DEFAULT_WORK_TOOLS` est `disable_tool()`e a l'import. Ce test empeche la
   regression silencieuse de cette whitelist.
"""

from __future__ import annotations

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.backend.tools.registration import enabled_tools_for_profile
from bouzecode.web_v2.services.work import graph_bureau


OUTILS_MICROSOFT = ("Mails", "Teams", "Canaux", "Brouillon", "Creneau", "Reunion")


@pytest.fixture
def transport_en_panne(monkeypatch):
    """Remplace le transport reel par un faux qui leve le type demande."""
    def poser(exception: Exception) -> None:
        class FauxTransport:
            def deposer_brouillon(self, **_):
                raise exception

            def bloquer_creneau(self, **_):
                raise exception

            def organiser_reunion(self, **_):
                raise exception

        monkeypatch.setattr(graph_bureau, "default_transport",
                            lambda: FauxTransport())
    return poser


@pytest.fixture
def transport_qui_marche(monkeypatch):
    appels: list[tuple[str, dict]] = []

    class FauxTransport:
        def deposer_brouillon(self, **kwargs):
            appels.append(("brouillon", kwargs))
            return {"id": "AAMk-1", "webLink": "https://outlook/brouillon"}

        def bloquer_creneau(self, **kwargs):
            appels.append(("creneau", kwargs))
            return {"id": "evt-1"}

        def organiser_reunion(self, **kwargs):
            appels.append(("reunion", kwargs))
            return {"id": "evt-2", "onlineMeeting": {"joinUrl": "https://teams/x"}}

    monkeypatch.setattr(graph_bureau, "default_transport", lambda: FauxTransport())
    return appels


# --------------------------------------------------------------------------
# Le chemin heureux : la reponse dit a l'agent ce qui s'est passe
# --------------------------------------------------------------------------

def test_brouillon_rend_ok_et_dit_que_rien_n_est_parti(transport_qui_marche) -> None:
    reponse = bureau_tools.brouillon(destinataires="yann@example.com",
                                     objet="Point", corps="Bonjour")

    assert reponse["ok"] is True
    assert transport_qui_marche[0][0] == "brouillon"
    #  L'agent doit pouvoir REPETER a l'humain ou aller valider.
    assert "brouillon" in " ".join(str(v) for v in reponse.values()).lower()


def test_les_destinataires_se_donnent_en_texte_separe_par_virgules(
        transport_qui_marche) -> None:
    bureau_tools.brouillon(destinataires="a@example.com, b@example.com",
                           objet="S", corps="t")

    _, kwargs = transport_qui_marche[0]
    assert kwargs["destinataires"] == ["a@example.com", "b@example.com"]


def test_creneau_rend_ok(transport_qui_marche) -> None:
    reponse = bureau_tools.creneau(sujet="Focus", debut="2026-09-22T09:00",
                                   duree_minutes=90)

    assert reponse["ok"] is True
    geste, kwargs = transport_qui_marche[0]
    assert geste == "creneau"
    assert kwargs["duree_minutes"] == 90


def test_reunion_rend_le_lien_de_la_reunion(transport_qui_marche) -> None:
    reponse = bureau_tools.reunion(sujet="Revue", debut="2026-09-23T10:00",
                                   participants="a@example.com", duree_minutes=45)

    assert reponse["ok"] is True
    assert reponse.get("lien") == "https://teams/x"


# --------------------------------------------------------------------------
# Les pannes : une reponse nommee, jamais une exception
# --------------------------------------------------------------------------

def test_un_refus_de_consentement_est_une_reponse_nommee(transport_en_panne) -> None:
    transport_en_panne(graph_bureau.TeamsAuthError("Mail.ReadWrite refuse"))

    reponse = bureau_tools.brouillon(destinataires="a@example.com", objet="S",
                                     corps="t")

    assert reponse["ok"] is False
    assert reponse["erreur"] == "authentification"
    #  Une consigne en clair : l'agent doit le dire a l'humain, pas inventer.
    assert reponse["consigne"]


def test_une_panne_de_transport_est_une_reponse_nommee(transport_en_panne) -> None:
    transport_en_panne(graph_bureau.TeamsTransportError("powershell muet"))

    reponse = bureau_tools.creneau(sujet="S", debut="2026-09-22T09:00")

    assert reponse["ok"] is False
    assert reponse["erreur"] == "transport"


def test_une_saisie_invalide_est_une_reponse_nommee(transport_en_panne) -> None:
    transport_en_panne(ValueError("date_illisible: demain matin"))

    reponse = bureau_tools.creneau(sujet="S", debut="demain matin")

    assert reponse["ok"] is False
    assert reponse["erreur"] == "saisie_invalide"
    assert "demain matin" in reponse["message"]


# --------------------------------------------------------------------------
# Exposition : le modele les recoit vraiment
# --------------------------------------------------------------------------

@pytest.mark.parametrize("nom", OUTILS_MICROSOFT)
def test_un_agent_de_code_ne_recoit_plus_les_outils_microsoft(nom: str) -> None:
    #  Audit du prompt (2026-09-24) : 3 050 tokens par appel, 0 appel sur 18 sessions de code.
    #  Ils restent a l'assistant du Bureau (test suivant), qui les declare dans son allowlist.
    assert nom not in enabled_tools_for_profile("default")


@pytest.mark.parametrize("nom", OUTILS_MICROSOFT)
def test_l_assistant_du_bureau_garde_les_outils_microsoft(nom: str) -> None:
    #  Son `tools:` est une allowlist NON vide : elle exclut tout le reste.
    assert nom in enabled_tools_for_profile("bureau-assistant")


@pytest.mark.parametrize("nom", ("Brouillon", "Creneau", "Reunion"))
def test_chaque_nouvel_outil_a_son_schema(nom: str) -> None:
    schemas = {schema["name"]: schema for schema in bureau_tools.BUREAU_TOOL_SCHEMAS}
    assert nom in schemas
    assert schemas[nom]["description"].strip()
    assert schemas[nom]["input_schema"]["type"] == "object"


def test_le_schema_du_brouillon_annonce_qu_il_n_envoie_pas() -> None:
    schemas = {schema["name"]: schema for schema in bureau_tools.BUREAU_TOOL_SCHEMAS}
    description = schemas["Brouillon"]["description"].lower()
    #  C'est la seule garantie que le modele ne croira pas avoir envoye le mail.
    assert "brouillon" in description
    assert "n'envoie" in description or "pas envoye" in description
