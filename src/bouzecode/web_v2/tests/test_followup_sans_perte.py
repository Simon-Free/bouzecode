# [desc] File des messages vers un agent chaud, SANS PERTE : deux messages poussés avant que l'agent ne relève le premier arrivent tous deux, dans l'ordre, une seule fois — y compris entre process. [/desc]
"""Avant : `runner._push_followup` ÉCRASAIT `followup.txt`. Deux messages arrivés avant que le
process ne relève le premier (relance humaine + réveil automatique du manager, ou deux messages
tapés coup sur coup) → le premier disparaissait. Constaté en E2E
(`test_scenarios_composes::test_relancer_le_meme_agent_apres_sa_reponse_finale…`).

Désormais tout passe par la boîte (`<ipc>/inbox/`, un fichier par message déposé d'un bloc) ;
`followup.txt` n'est plus écrit que pour un process lancé avec l'ancien code, qui ne sait pas
lire sa boîte (son `state.json` ne porte pas le drapeau `boite`)."""
from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime import ipc
from bouzecode.web_v2.runtime.runner import agent_chaud, agent_fiche, agent_reprise
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import file_messages
from bouzecode.web_v2.tests.test_v3_statut_des_taches import ecrire_agent


def _paths(agent_id: str) -> ipc.IPCPaths:
    return ipc.from_dir(agent_fiche.AGENTS_DIR / f"{agent_id}.ipc")


def _process_a_jour(agent_id: str, statut: str) -> None:
    """L'état tel que l'écrit un process du code actuel (`ipc.write_state`)."""
    ipc.write_state(_paths(agent_id), statut, turn=3)


def test_deux_messages_pousses_avant_lecture_arrivent_tous_les_deux_dans_l_ordre():
    ecrire_agent("f0a1b2c3d4e5", vivant=True, ipc="idle")
    _process_a_jour("f0a1b2c3d4e5", ipc.STATUS_IDLE)
    agent = agent_fiche.load_agent("f0a1b2c3d4e5")

    agent_chaud._push_followup(agent, "Il manque RETOUR.md.")
    agent_chaud._push_followup(agent, "Tes sous-agents ont fini.")

    paths = _paths("f0a1b2c3d4e5")
    assert not paths.followup.exists(), "plus rien n'écrase followup.txt"
    prompt = ipc._wait_for_followup(paths, ttl_seconds=5, poll_interval=0.01)
    assert prompt == "Il manque RETOUR.md.\n\nTes sous-agents ont fini."
    assert ipc.relever_messages(paths) == [], "aucun doublon"


def test_relever_un_par_un_garde_l_ordre():
    paths = _paths("f1a1b2c3d4e5")
    for i in range(5):
        ipc.deposer_message(paths, f"m{i}", f"message {i}")
    assert ipc.relever_messages(paths) == [f"message {i}" for i in range(5)]


def test_l_ordre_tient_meme_quand_l_horloge_ne_bouge_pas(monkeypatch):
    """Sous Windows, `time.time_ns()` avance par pas de ~1 à 16 ms : deux dépôts dans le même
    pas avaient le même préfixe, et l'identifiant aléatoire décidait de l'ordre."""
    monkeypatch.setattr(ipc.time, "time_ns", lambda: 1_700_000_000_000_000_000)
    paths = _paths("f2a1b2c3d4e5")
    for i, mid in enumerate(["zz", "aa", "mm"]):
        ipc.deposer_message(paths, mid, f"message {i}")
    assert ipc.relever_messages(paths) == ["message 0", "message 1", "message 2"]


def test_un_process_de_l_ancien_code_recoit_encore_son_message_par_followup_txt():
    """Pas de drapeau `boite` dans son état : il ne sonde que followup.txt."""
    ecrire_agent("f3a1b2c3d4e5", vivant=True, ipc="idle")          # état sans drapeau
    agent = agent_fiche.load_agent("f3a1b2c3d4e5")
    agent_chaud._push_followup(agent, "reprends stp")
    paths = _paths("f3a1b2c3d4e5")
    assert paths.followup.read_text(encoding="utf-8") == "reprends stp"
    assert not ipc.a_du_courrier(paths)


def test_le_drapeau_boite_est_ecrit_par_chaque_etat():
    paths = _paths("f4a1b2c3d4e5")
    ipc.write_state(paths, ipc.STATUS_RUNNING, turn=1)
    assert ipc.read_state(paths).get("boite") == 1
    assert ipc.lit_sa_boite(paths)


def test_un_message_au_process_en_plein_tour_attend_dans_sa_boite_au_lieu_d_etre_perdu():
    """Réveil automatique arrivé juste après que l'agent a relevé la relance humaine : il joue
    déjà son tour. Avant, `continue_agent` tentait un respawn, refusé (pid vivant) → perdu."""
    ecrire_agent("f5a1b2c3d4e5", vivant=True, ipc="running")
    _process_a_jour("f5a1b2c3d4e5", ipc.STATUS_RUNNING)
    agent = agent_fiche.load_agent("f5a1b2c3d4e5")
    assert agent_reprise.continue_agent(agent, "Tes sous-agents ont fini.") is not None
    assert ipc.relever_messages(_paths("f5a1b2c3d4e5")) == ["Tes sous-agents ont fini."]


# ------------------------------------------------------------------ file des messages (lu / non lu)

def _livrer_deux_messages(agent_id: str) -> None:
    ecrire_agent(agent_id, vivant=False, ipc="running")
    file_messages.mettre_en_file(agent_id, "premier")
    file_messages.mettre_en_file(agent_id, "second")
    ecrire_agent(agent_id, vivant=True, ipc="idle")
    _process_a_jour(agent_id, ipc.STATUS_IDLE)
    store.invalidate_status(agent_id)
    assert file_messages.livrer_si_pret(agent_id) == {"ok": True}


def test_la_file_montre_les_messages_livres_en_attente_de_lecture_puis_lus():
    _livrer_deux_messages("f6a1b2c3d4e5")
    assert [(i["text"], i.get("statut")) for i in file_messages.lister("f6a1b2c3d4e5")] == [
        ("premier", "en_livraison"), ("second", "en_livraison")]
    assert file_messages.message_non_lu(agent_fiche.load_agent("f6a1b2c3d4e5"))
    assert ipc.relever_messages(_paths("f6a1b2c3d4e5")) == ["premier\n\nsecond"]
    assert file_messages.lister("f6a1b2c3d4e5") == []
    assert not file_messages.message_non_lu(agent_fiche.load_agent("f6a1b2c3d4e5"))


def test_un_process_arrete_avant_de_lire_rend_tous_les_messages_du_lot_non_livres():
    _livrer_deux_messages("f7a1b2c3d4e5")
    ecrire_agent("f7a1b2c3d4e5", vivant=False, ipc="finished")      # évincé avant lecture
    store.invalidate_status("f7a1b2c3d4e5")
    items = file_messages.lister("f7a1b2c3d4e5")
    assert [(i["text"], i.get("statut")) for i in items] == [
        ("premier", "non_livre"), ("second", "non_livre")], "l'arrêt a pu être voulu : Renvoyer"
    assert ipc.relever_messages(_paths("f7a1b2c3d4e5")) == [], "repris de la boîte"
    assert file_messages.livrer_si_pret("f7a1b2c3d4e5") is None, "rien ne part tout seul"


def test_annuler_un_message_du_lot_rend_les_autres_a_la_file():
    _livrer_deux_messages("f8a1b2c3d4e5")
    premier = file_messages.lister("f8a1b2c3d4e5")[0]
    assert file_messages.annuler("f8a1b2c3d4e5", premier["id"])
    assert [(i["text"], i.get("statut")) for i in file_messages.lister("f8a1b2c3d4e5")] == [
        ("second", None)]
    assert ipc.relever_messages(_paths("f8a1b2c3d4e5")) == []


# ------------------------------------------------------------------ concurrence entre process

def _producteur(dossier: str, nom: str, n: int) -> None:
    paths = ipc.from_dir(dossier)
    for i in range(n):
        ipc.deposer_message(paths, f"{nom}{i}", f"{nom}:{i}")


def _consommateur(dossier: str, attendus: int, sortie: str) -> None:
    paths = ipc.from_dir(dossier)
    recus: list[str] = []
    fin = time.monotonic() + 60
    while len(recus) < attendus and time.monotonic() < fin:
        recus.extend(ipc.relever_messages(paths))
    Path(sortie).write_text(json.dumps(recus), encoding="utf-8")


def test_producteurs_et_consommateur_dans_des_process_distincts_rien_perdu_rien_double(tmp_path):
    ctx = multiprocessing.get_context("spawn")      # comme sous Windows
    dossier, sortie, n = str(tmp_path / "ipc"), str(tmp_path / "recus.json"), 150
    consommateur = ctx.Process(target=_consommateur, args=(dossier, 3 * n, sortie))
    producteurs = [ctx.Process(target=_producteur, args=(dossier, nom, n)) for nom in "abc"]
    consommateur.start()
    for p in producteurs:
        p.start()
    for p in [*producteurs, consommateur]:
        p.join(90)
        assert p.exitcode == 0
    recus = json.loads(Path(sortie).read_text(encoding="utf-8"))
    assert sorted(recus) == sorted(f"{nom}:{i}" for nom in "abc" for i in range(n))
    for nom in "abc":
        assert [r for r in recus if r.startswith(nom)] == [f"{nom}:{i}" for i in range(n)], \
            "l'ordre d'un même producteur est gardé"


def _repreneur(dossier: str, n: int, sortie: str) -> None:
    paths = ipc.from_dir(dossier)
    repris = [f"m{i}" for i in range(n) if ipc.reprendre_message(paths, f"m{i}")]
    Path(sortie).write_text(json.dumps(repris), encoding="utf-8")


def test_reprise_par_le_serveur_et_releve_par_l_agent_ne_se_partagent_jamais_un_message(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    dossier, n = str(tmp_path / "ipc"), 200
    _producteur(dossier, "m", n)
    sortie_agent, sortie_serveur = str(tmp_path / "agent.json"), str(tmp_path / "serveur.json")
    agent = ctx.Process(target=_consommateur, args=(dossier, n, sortie_agent))
    serveur = ctx.Process(target=_repreneur, args=(dossier, n, sortie_serveur))
    serveur.start()
    agent.start()
    serveur.join(90)
    #  L'agent attend `n` messages : on complète ce que le serveur a repris pour qu'il finisse.
    repris = json.loads(Path(sortie_serveur).read_text(encoding="utf-8"))
    _producteur(dossier, "fin", len(repris))
    agent.join(90)
    lus = [r for r in json.loads(Path(sortie_agent).read_text(encoding="utf-8"))
           if r.startswith("m:")]
    assert len(lus) + len(repris) == n
    assert not set(lus) & {f"m:{m[1:]}" for m in repris}
    assert not list(Path(dossier, "inbox").iterdir()), "aucun fichier orphelin"


def test_un_fichier_momentanement_verrouille_ne_fait_pas_doubler_les_suivants(monkeypatch):
    """Windows : un antivirus qui ouvre un message bloque son renommage (PermissionError). Les
    suivants ne doivent pas passer devant : la relève s'arrête et reprend au tour suivant."""
    paths = _paths("f9a1b2c3d4e5")
    for i in range(3):
        ipc.deposer_message(paths, f"m{i}", f"message {i}")
    vrai_replace = Path.replace
    bloque = {"fois": 1}

    def replace(self, cible):
        if self.name.endswith("-m0.txt") and bloque["fois"]:
            bloque["fois"] -= 1
            raise PermissionError(13, "occupé")
        return vrai_replace(self, cible)

    monkeypatch.setattr(Path, "replace", replace)
    assert ipc.relever_messages(paths) == []
    assert ipc.relever_messages(paths) == ["message 0", "message 1", "message 2"]
