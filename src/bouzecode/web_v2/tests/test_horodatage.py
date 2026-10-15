# [desc] Horodatages du store : toute date écrite porte son fuseau (UTC), les anciennes dates locales naïves restent lisibles, comparables et triables. [/desc]
"""Le 2026-10-05, une heure LOCALE naïve du store (`2026-10-05T14:02:11`) a été lue comme UTC :
deux heures de décalage, et l'écriture a été imputée au mauvais process. Le store mêlait deux
formes ; il n'en écrit plus qu'une (`horodatage.maintenant_iso`, UTC `+00:00`) et les lit toutes
les deux par le même chemin (`horodatage.lire_instant`, naïf = local)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bouzecode.web_v2.services import horodatage
from bouzecode.web_v2.services.work import (
    _persistence, classement, decision_ingest, decisions, integration, micros, nettoyage,
    signalements, tache_v1_migration, tasks, ticket_fsm, tickets,
)
from bouzecode.web_v2.services.work.fsm import cycle_des_runs, journal, migration

SUFFIXE_UTC = re.compile(r"\+00:00$")
RACINE = Path(horodatage.__file__).resolve().parents[2]  # src/bouzecode
INSTANT = datetime(2026, 10, 5, 12, 2, 11, tzinfo=timezone.utc)


def _formes(instant: datetime) -> list[str]:
    """Le MÊME instant sous toutes les formes présentes en base ou servies par l'API."""
    local = instant.astimezone()
    return [
        local.replace(tzinfo=None).isoformat(timespec="seconds"),  # héritage : local naïf
        local.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),  # `saved_at` du harnais
        local.isoformat(timespec="seconds"),  # ancien `asked_at` : local + décalage
        instant.isoformat(timespec="seconds"),  # forme écrite désormais
        instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),  # ancien runner (`utcnow() + "Z"`)
    ]


def test_les_producteurs_du_store_ecrivent_tous_de_l_utc_explicite():
    producteurs = [_persistence._now, migration._maintenant, journal._maintenant,
                   cycle_des_runs._maintenant, ticket_fsm._maintenant, micros._now, tasks._now,
                   decisions._now, decision_ingest._now, signalements._maintenant,
                   classement._maintenant, integration._maintenant, nettoyage._maintenant,
                   tache_v1_migration._now, horodatage.maintenant_iso]
    for produire in producteurs:
        valeur = produire()
        assert SUFFIXE_UTC.search(valeur), f"{produire.__module__}.{produire.__name__} → {valeur}"
        assert abs(horodatage.age_s(valeur)) < 5


def test_un_ticket_cree_et_son_journal_portent_un_fuseau():
    ticket = tickets.create_ticket("horodatage", "dater", "rien")
    with _persistence._connect() as conn:
        evenements = journal.lire(conn, "horodatage", ticket["id"])
    assert SUFFIXE_UTC.search(ticket["created_at"])
    assert evenements and all(SUFFIXE_UTC.search(e["at"]) for e in evenements)


def test_plus_aucun_horodatage_naif_ecrit_par_le_code():
    """Garde-fou : un `datetime.now().isoformat()` qui reviendrait referait deux formes."""
    naif = re.compile(r"datetime\.now\(\)\.(isoformat|astimezone\(\)\.isoformat)|utcnow\(")
    fautifs = [f"{chemin.relative_to(RACINE)}:{numero}"
               for dossier in ("web_v2", "remote") for chemin in (RACINE / dossier).rglob("*.py")
               if "tests" not in chemin.parts
               for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1)
               if naif.search(ligne) and not ligne.lstrip().startswith(("#", "-", "*"))
               and chemin.name != "horodatage.py"]
    assert fautifs == []


def test_toutes_les_formes_d_un_instant_se_lisent_comme_le_meme_instant():
    for forme in _formes(INSTANT):
        assert horodatage.lire_instant(forme) == INSTANT, forme
    assert horodatage.lire_instant(INSTANT.astimezone().replace(tzinfo=None)) == INSTANT
    assert horodatage.lire_instant(INSTANT.timestamp()) == INSTANT
    for illisible in ("", None, "hier", "2026-13-45", 0, -1):
        assert horodatage.lire_instant(illisible) is None


def test_en_iso_ramene_une_date_heritee_a_la_forme_ecrite():
    naif = INSTANT.astimezone().replace(tzinfo=None).isoformat()
    assert horodatage.en_iso(naif) == "2026-10-05T12:02:11+00:00"
    assert horodatage.en_iso("pas une date") == ""


def test_un_tri_sur_des_formes_melangees_est_chronologique_et_ne_leve_pas():
    """Une heure d'écart, formes alternées : l'ordre lexical ment, la clé chronologique non."""
    valeurs = [_formes(INSTANT + timedelta(hours=heures))[forme]
               for heures, forme in ((0, 0), (1, 3), (2, 1), (3, 4))]
    melangees = [valeurs[2], valeurs[0], valeurs[3], valeurs[1], "", "illisible"]
    triees = sorted(melangees, key=horodatage.cle_chrono)
    assert triees[2:] == valeurs
    instants = [horodatage.lire_instant(v) for v in melangees if horodatage.lire_instant(v)]
    assert max(instants) - min(instants) == timedelta(hours=3)


def test_age_identique_quelle_que_soit_la_forme():
    il_y_a_une_minute = horodatage.maintenant() - timedelta(minutes=1)
    for forme in _formes(il_y_a_une_minute.replace(microsecond=0)):
        assert 59 <= horodatage.age_s(forme) <= 65, forme
    reference_naive = (INSTANT + timedelta(seconds=90)).astimezone().replace(tzinfo=None)
    assert horodatage.age_s(INSTANT.isoformat(), reference_naive) == 90
    assert horodatage.age_s("illisible") is None


def test_l_affichage_humain_est_en_heure_locale():
    attendu = INSTANT.astimezone().strftime("%d/%m %H:%M")
    for forme in _formes(INSTANT):
        assert horodatage.heure_locale(forme, "%d/%m %H:%M") == attendu
    assert horodatage.heure_locale("", "%H:%M") == ""
