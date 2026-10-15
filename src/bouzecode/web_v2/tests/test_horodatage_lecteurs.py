# [desc] Les lecteurs de dates du store (âges, fenêtres, tris, clés de dédoublonnage) donnent le même verdict pour une date locale héritée et pour la même date écrite en UTC. [/desc]
"""Avant l'unification, plusieurs lecteurs comparaient `datetime.now()` NAÏF à une date du store
dont ils arrachaient le fuseau (`.replace(tzinfo=None)`) : une date UTC y vieillissait de deux
heures d'un coup (lancement déclaré figé à tort), ou levait un TypeError avalé (doublon de
précision jamais reconnu). Chaque test pose le même instant sous les deux formes."""
from __future__ import annotations

from datetime import datetime, timedelta

from bouzecode.web_v2.services import horodatage
from bouzecode.web_v2.services.work import (
    board, bureau_lignes, decisions, inbox, taches_actions, todo_board,
)
from bouzecode.web_v2.services.work.fsm import correspondance


def _deux_formes(il_y_a: timedelta) -> tuple[str, str]:
    """(héritage local naïf, forme écrite UTC) du même instant passé."""
    instant = horodatage.maintenant().replace(microsecond=0) - il_y_a
    return (instant.astimezone().replace(tzinfo=None).isoformat(),
            instant.isoformat(timespec="seconds"))


def test_un_lancement_recent_n_est_jamais_fige_quelle_que_soit_sa_forme():
    for forme in _deux_formes(timedelta(minutes=10)):
        assert correspondance._lancement_fige({"created_at": forme}) is False, forme
    for forme in _deux_formes(timedelta(minutes=40)):
        assert correspondance._lancement_fige({"created_at": forme}) is True, forme
    assert correspondance._lancement_fige({"created_at": ""}) is False


def test_l_age_d_une_tache_et_d_une_carte_ne_depend_pas_de_la_forme():
    for forme in _deux_formes(timedelta(minutes=5)):
        assert 299 <= board._age_seconds({"at": forme}) <= 305, forme
        assert 299 <= board._waiting_s(forme) <= 305, forme


def test_la_fenetre_de_l_inbox_lit_les_deux_formes():
    for forme in _deux_formes(timedelta(days=1)):
        assert inbox._recent(forme, jours=2) is True
    for forme in _deux_formes(timedelta(days=3)):
        assert inbox._recent(forme, jours=2) is False


def test_une_precision_renvoyee_a_l_instant_est_reconnue_comme_doublon():
    """Avant : `datetime.now()` naïf − date UTC → TypeError avalé → doublon jamais vu."""
    for forme in _deux_formes(timedelta(seconds=30)):
        micro = {"precisions": [{"rang": 1, "texte": "même texte", "created_at": forme}]}
        assert taches_actions._doublon_recent(micro, "même  texte") is not None, forme


def test_le_dernier_signe_d_une_ligne_est_le_plus_recent_pas_le_dernier_de_la_liste():
    """Liste triée en CHAÎNE par le store : un local naïf `14:00` passe après `12:30+00:00`
    (même jour, Paris) alors qu'il est plus ancien d'une demi-heure."""
    ancien_local, _ = _deux_formes(timedelta(minutes=60))
    _, recent_utc = _deux_formes(timedelta(minutes=30))
    ligne = {"tickets": [{"at": recent_utc}, {"at": ancien_local}, {"at": "illisible"}]}
    assert bureau_lignes._dernier_signe(ligne) == horodatage.lire_instant(recent_utc)
    assert bureau_lignes._dernier_signe({"tickets": []}) is None


def test_la_fenetre_de_la_todo_accepte_un_maintenant_naif_ou_conscient():
    naif = datetime(2026, 8, 27, 12, 0, 0)
    plancher = todo_board.borne_de("2j", naif)
    assert plancher == horodatage.lire_instant(naif) - timedelta(days=2)
    assert todo_board.borne_de("2j", horodatage.lire_instant(naif)) == plancher
    assert todo_board.borne_de("tout", naif) is None


def test_la_cle_de_dedoublonnage_survit_au_passage_a_l_utc():
    """Les clés en base ont été calculées sur des `asked_at` LOCAUX : la même question, datée
    désormais en UTC, doit retomber sur la même clé — sinon elle renaît en doublon."""
    local, utc = _deux_formes(timedelta(minutes=3))
    assert decisions.dedup_key("question", "t1", "a1", local) == decisions.dedup_key(
        "question", "t1", "a1", utc)
    assert decisions.dedup_key("question", "t1", "a1", "brut illisible") == (
        "question|t1|a1|brut illisible")
