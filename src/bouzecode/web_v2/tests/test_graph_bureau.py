"""Les ecritures Microsoft Graph du Bureau : brouillon de mail, creneau, reunion.

L'invariant central est social, pas technique : `deposer_brouillon` ne DOIT jamais
envoyer. La validation humaine demandee le 2026-09-21 est le dossier Brouillons
d'Outlook lui-meme -- si un jour ce module appelait une action d'envoi, la demande
serait trahie en silence. Ces tests verrouillent l'action passee a PowerShell.

Aucun test ne lance PowerShell ni ne touche le reseau : le runner est injecte,
exactement comme dans test_teams_graph_transport.py.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import graph_bureau


def _runner_ok(charge: dict | None = None):
    """Rend un couple (runner, appels) : le runner enregistre les args recus.

    Il relit aussi le fichier designe par `-CorpsPath` TANT QU'IL EXISTE (le
    transport le supprime apres l'appel), et range son contenu dans `corps`.
    """
    appels: list[list[str]] = []
    corps: list[str] = []

    def runner(args: list[str]) -> tuple[int, str, str]:
        appels.append(list(args))
        if "-CorpsPath" in args:
            chemin = Path(args[args.index("-CorpsPath") + 1])
            corps.append(chemin.read_text(encoding="utf-8"))
        return 0, json.dumps(charge if charge is not None else {"id": "obj-1"}), ""

    return runner, appels, corps


def _valeur(args: list[str], nom: str) -> str:
    return args[args.index(nom) + 1]


# --------------------------------------------------------------------------
# 1. Un brouillon ne s'envoie pas
# --------------------------------------------------------------------------

def test_un_brouillon_est_depose_jamais_envoye() -> None:
    runner, appels, corps = _runner_ok({"id": "AAMk-brouillon"})
    transport = graph_bureau.BureauGraph(runner=runner)

    charge = transport.deposer_brouillon(
        destinataires=["yann@example.com"],
        objet="Point de lundi",
        corps="Bonjour,\n\nOn se cale lundi ?\n",
    )

    assert charge["id"] == "AAMk-brouillon"
    assert len(appels) == 1
    args = appels[0]
    #  L'action DOIT etre 'brouillon' : aucune action d'envoi ne doit jamais
    #  sortir d'ici, c'est tout le contrat passe avec l'humain.
    assert args[0] == "-Action"
    assert args[1] == "brouillon"
    assert "send" not in args
    assert "envoyer" not in args
    assert _valeur(args, "-Destinataires") == "yann@example.com"
    assert _valeur(args, "-Objet") == "Point de lundi"
    assert corps == ["Bonjour,\n\nOn se cale lundi ?\n"]


def test_un_brouillon_accepte_plusieurs_destinataires_et_des_cc() -> None:
    runner, appels, _ = _runner_ok()
    transport = graph_bureau.BureauGraph(runner=runner)

    transport.deposer_brouillon(
        destinataires=["a@example.com", "b@example.com"],
        objet="Sujet",
        corps="texte",
        cc=["chef@example.com"],
    )

    args = appels[0]
    assert _valeur(args, "-Destinataires") == "a@example.com,b@example.com"
    assert _valeur(args, "-Cc") == "chef@example.com"


def test_un_brouillon_sans_cc_ne_passe_pas_le_parametre() -> None:
    runner, appels, _ = _runner_ok()
    transport = graph_bureau.BureauGraph(runner=runner)

    transport.deposer_brouillon(destinataires=["a@example.com"], objet="S", corps="t")

    #  Passer -Cc vide ferait echouer Require-Param cote PowerShell.
    assert "-Cc" not in appels[0]


def test_le_fichier_temporaire_du_corps_est_supprime_apres_l_appel() -> None:
    chemins: list[Path] = []

    def runner(args: list[str]) -> tuple[int, str, str]:
        chemins.append(Path(_valeur(args, "-CorpsPath")))
        return 0, json.dumps({"id": "x"}), ""

    graph_bureau.BureauGraph(runner=runner).deposer_brouillon(
        destinataires=["a@example.com"], objet="S", corps="t")

    assert chemins and not chemins[0].exists()


# --------------------------------------------------------------------------
# 2. Bloquer un creneau (sans validation, sans participant)
# --------------------------------------------------------------------------

def test_bloquer_un_creneau_calcule_la_fin_et_n_invite_personne() -> None:
    runner, appels, _ = _runner_ok({"id": "evt-1"})
    transport = graph_bureau.BureauGraph(runner=runner)

    charge = transport.bloquer_creneau(
        sujet="Focus specs", debut="2026-09-22T09:00", duree_minutes=90)

    assert charge["id"] == "evt-1"
    args = appels[0]
    assert args[1] == "creneau"
    assert _valeur(args, "-Sujet") == "Focus specs"
    assert _valeur(args, "-Debut") == "2026-09-22T09:00:00"
    #  La fin est CALCULEE : la classe d'erreur « fin avant debut » n'existe pas.
    assert _valeur(args, "-Fin") == "2026-09-22T10:30:00"
    assert _valeur(args, "-Fuseau") == graph_bureau.FUSEAU_DEFAUT
    #  Un creneau bloque du temps : il n'invite personne.
    assert "-Participants" not in args


def test_un_espace_au_lieu_du_T_est_accepte() -> None:
    runner, appels, _ = _runner_ok()
    transport = graph_bureau.BureauGraph(runner=runner)

    transport.bloquer_creneau(sujet="S", debut="2026-09-22 14:30", duree_minutes=30)

    assert _valeur(appels[0], "-Debut") == "2026-09-22T14:30:00"
    assert _valeur(appels[0], "-Fin") == "2026-09-22T15:00:00"


# --------------------------------------------------------------------------
# 3. Organiser une reunion (sans validation)
# --------------------------------------------------------------------------

def test_organiser_une_reunion_invite_et_demande_une_reunion_en_ligne() -> None:
    runner, appels, _ = _runner_ok({"id": "evt-2",
                                   "onlineMeeting": {"joinUrl": "https://teams/x"}})
    transport = graph_bureau.BureauGraph(runner=runner)

    charge = transport.organiser_reunion(
        sujet="Revue", debut="2026-09-23T10:00",
        participants=["a@example.com", "b@example.com"], duree_minutes=45)

    assert charge["onlineMeeting"]["joinUrl"] == "https://teams/x"
    args = appels[0]
    assert args[1] == "reunion"
    assert _valeur(args, "-Participants") == "a@example.com,b@example.com"
    assert _valeur(args, "-Debut") == "2026-09-23T10:00:00"
    assert _valeur(args, "-Fin") == "2026-09-23T10:45:00"


def test_une_reunion_sans_participant_est_refusee_sans_appeler_powershell() -> None:
    runner, appels, _ = _runner_ok()
    transport = graph_bureau.BureauGraph(runner=runner)

    with pytest.raises(ValueError) as souci:
        transport.organiser_reunion(sujet="Revue", debut="2026-09-23T10:00",
                                    participants=[])

    assert "participants" in str(souci.value)
    assert appels == []


# --------------------------------------------------------------------------
# 4. Saisies invalides : une erreur nommee, et AUCUN appel
# --------------------------------------------------------------------------

@pytest.mark.parametrize("brut", ["demain matin", "", "2026-13-45T99:00"])
def test_une_date_illisible_est_refusee_sans_appeler_powershell(brut: str) -> None:
    runner, appels, _ = _runner_ok()
    transport = graph_bureau.BureauGraph(runner=runner)

    with pytest.raises(ValueError):
        transport.bloquer_creneau(sujet="S", debut=brut, duree_minutes=30)

    assert appels == []


def test_un_brouillon_sans_destinataire_est_refuse_sans_appeler_powershell() -> None:
    runner, appels, _ = _runner_ok()
    transport = graph_bureau.BureauGraph(runner=runner)

    with pytest.raises(ValueError) as souci:
        transport.deposer_brouillon(destinataires=[], objet="S", corps="t")

    assert "destinataire" in str(souci.value)
    assert appels == []


@pytest.mark.parametrize("duree", [0, -30])
def test_une_duree_non_positive_est_refusee(duree: int) -> None:
    runner, appels, _ = _runner_ok()
    transport = graph_bureau.BureauGraph(runner=runner)

    with pytest.raises(ValueError):
        transport.bloquer_creneau(sujet="S", debut="2026-09-22T09:00",
                                  duree_minutes=duree)

    assert appels == []


# --------------------------------------------------------------------------
# 5. Pannes : un TYPE, jamais un code ni une exception brute
# --------------------------------------------------------------------------

def test_un_refus_de_consentement_devient_une_erreur_d_authentification() -> None:
    def runner(args: list[str]) -> tuple[int, str, str]:
        return 1, json.dumps({"error": {"code": "AuthenticationError",
                                        "message": "Mail.ReadWrite refuse",
                                        "action": "brouillon"}}), ""

    transport = graph_bureau.BureauGraph(runner=runner)

    with pytest.raises(graph_bureau.TeamsAuthError):
        transport.deposer_brouillon(destinataires=["a@example.com"], objet="S",
                                    corps="t")


def test_un_powershell_qui_pend_devient_une_panne_de_transport() -> None:
    def runner(args: list[str]) -> tuple[int, str, str]:
        raise subprocess.TimeoutExpired(cmd=["powershell", *args], timeout=90)

    transport = graph_bureau.BureauGraph(runner=runner, timeout=90)

    with pytest.raises(graph_bureau.TeamsTransportError) as panne:
        transport.bloquer_creneau(sujet="S", debut="2026-09-22T09:00")

    motif = str(panne.value)
    assert "creneau" in motif, motif
    assert "90" in motif, motif


def test_une_sortie_non_json_devient_une_panne_de_transport() -> None:
    def runner(args: list[str]) -> tuple[int, str, str]:
        return 0, "Connect-MgGraph : pas de contexte", ""

    transport = graph_bureau.BureauGraph(runner=runner)

    with pytest.raises(graph_bureau.TeamsTransportError):
        transport.bloquer_creneau(sujet="S", debut="2026-09-22T09:00")


# --------------------------------------------------------------------------
# 6. Le script PowerShell existe et reste dans les conventions maison
# --------------------------------------------------------------------------

def test_le_script_powershell_existe_et_declare_les_trois_actions() -> None:
    chemin = graph_bureau.GRAPH_BUREAU_PS1
    assert chemin.exists(), chemin
    #  BOM obligatoire : PowerShell 5.1 lit un .ps1 sans BOM en ANSI.
    assert chemin.read_bytes().startswith(b"\xef\xbb\xbf")
    texte = chemin.read_text(encoding="utf-8-sig")
    for action in ("brouillon", "creneau", "reunion"):
        assert f"'{action}'" in texte, action
    #  Scopes minimaux, un Connect-MgGraph par action (patron graph_activite.ps1).
    assert "Mail.ReadWrite" in texte
    assert "Calendars.ReadWrite" in texte
    #  Le chemin Teams vivant ne doit pas etre touche par ce script.
    assert "Chat.ReadWrite" not in texte


def test_le_script_powershell_est_ascii_pur() -> None:
    octets = graph_bureau.GRAPH_BUREAU_PS1.read_bytes()[3:]
    assert all(octet < 128 for octet in octets), "accent interdit dans un .ps1 maison"
