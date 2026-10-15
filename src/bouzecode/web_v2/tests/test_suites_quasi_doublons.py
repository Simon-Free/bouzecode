# [desc] Suites de clôture : une micro quasi identique à une tâche ouverte du même chantier n'est pas recréée — le point s'y rattache (précision + lien), cas réels de l'essai du 2026-09-24. [/desc]
"""Plusieurs clôtures signalent le MÊME point sous des libellés voisins.

Cas réel (~/bouzecode-essai, chantier « Portail des énigmes », 24-25/09/2026) : en 20 minutes,
trois clôtures ont ouvert « Brancher d'autres sites sources que le Kangourou », « Étendre le
scraping à d'autres sites d'énigmes (après le Kangourou) » puis « Étendre le scraping à d'autres
sites d'énigmes » ; et deux décisions sur Q25/Q26 à une minute d'écart. L'anti-doublon ne
comparait que les titres EXACTS.

Règle : un point quasi identique à une tâche encore ouverte du même chantier (même nature :
décision ou travail) ne crée pas de ligne ; il est lié à cette tâche (récap du passage) et, si
elle n'est pas lancée, son libellé lui est ajouté en précision — rien n'est perdu.
"""
import pytest

from bouzecode.web_v2.services.work import meme_point, micros, suites_cloture
from bouzecode.web_v2.services.work.cloture_micros import ouvrir_micros_de_cloture

#  Libellés RÉELS relevés dans ~/bouzecode-essai/.bouzecode/web_v2/tickets/tickets.db.
BRANCHER = "Brancher d'autres sites sources que le Kangourou"
ETENDRE_APRES = "Étendre le scraping à d'autres sites d'énigmes (après le Kangourou)"
ETENDRE = "Étendre le scraping à d'autres sites d'énigmes"
RECUPERER = "Récupérer des énoncés d'autres années et vérifier le parsing des figures"
EXPORTER = "Exporter/importer les verdicts (aujourd'hui en localStorage seulement)"
Q25 = "Q25/Q26 (départage) sans choix A-E dans le sujet officiel"
PDF = "Comparaison page entière du PDF impossible"
ECARTS = "Écarts assumés sur les 2 questions de départage (Q25/Q26)"
RECADRAGE = "Corriger les 2 défauts de recadrage cosmétiques (Q23 coupée à droite, Q24 avec bande de la Q23)"
FIGURE = "Produire une figure Écoliers 2024 (exigence explicite du ticket)"
REGENERER = "Régénérer data/enigmes.json par le réseau (2025 + 2024, 12 sujets)"


@pytest.mark.parametrize("a, b", [
    (ETENDRE, ETENDRE_APRES),
    (BRANCHER, ETENDRE_APRES),
    (Q25, ECARTS),
    ("Étendre le périmètre à d'autres années et épreuves",
     "Étendre le corpus aux autres épreuves (Benjamin, Junior, Student) et à l'année 2022"),
])
def test_meme_point_sur_les_cas_reels(a, b):
    assert meme_point.meme_point(a, b)
    assert meme_point.meme_point(b, a)


@pytest.mark.parametrize("a, b", [
    (ETENDRE, RECUPERER),
    (BRANCHER, ETENDRE),  # rapprochés par transitivité (alias), pas directement
    (RECADRAGE, Q25),
    (RECADRAGE, ECARTS),
    (FIGURE, REGENERER),
    (EXPORTER, RECUPERER),
    (PDF, Q25),
    ("Corriger les tests de l'API", "Corriger les tests du front"),
    ("Corriger les tests", "Corriger les tests du module lexer"),
])
def test_points_differents_restent_distincts(a, b):
    assert not meme_point.meme_point(a, b)


def _chantier():
    macro = micros.ensure_macro("Portail des énigmes")
    mere = micros.create_micro(titre="Scraper les énigmes", macro_id=macro["id"])
    for ticket in ("T1", "T2", "T3", "T4", "T5"):
        micros.lier_ticket(mere["id"], slug="portail-enigmes", ticket_id=ticket)
    return macro, mere


def _ouvertes(macro_id, mere_id):
    return sorted(m["titre"] for m in micros.list_micros(macro_id=macro_id)
                  if m["id"] != mere_id and m["etat"] in ("brouillon", "prete", "lancee"))


def test_la_sequence_reelle_ne_fabrique_plus_de_doublons():
    """Rejoue, dans l'ordre, les clôtures réelles du chantier (23:42 → 02:41)."""
    macro, mere = _chantier()
    ouvrir_micros_de_cloture([BRANCHER, RECUPERER], ticket_id="T1", slug="portail-enigmes")
    ouvrir_micros_de_cloture([ETENDRE_APRES], ticket_id="T2", slug="portail-enigmes")
    ouvrir_micros_de_cloture([ETENDRE, EXPORTER], ticket_id="T3", slug="portail-enigmes")
    ouvrir_micros_de_cloture([{"titre": Q25, "decision": True}, {"titre": PDF, "decision": True}],
                             ticket_id="T4", slug="portail-enigmes")
    ouvrir_micros_de_cloture([{"titre": ECARTS, "decision": True}], ticket_id="T5",
                             slug="portail-enigmes")

    assert _ouvertes(macro["id"], mere["id"]) == sorted([BRANCHER, RECUPERER, EXPORTER, Q25, PDF])


def test_le_point_rattache_est_trace_et_rien_ne_se_perd():
    macro, mere = _chantier()
    [brancher] = ouvrir_micros_de_cloture([BRANCHER], ticket_id="T1", slug="portail-enigmes")

    creees = ouvrir_micros_de_cloture([{"titre": ETENDRE_APRES, "corps": "Sources : Castor, Alkindi."}],
                                      ticket_id="T2", slug="portail-enigmes")

    assert creees == []
    lien = suites_cloture.index()["T2"][suites_cloture.cle(ETENDRE_APRES)]
    assert lien == {"micro_id": brancher["id"], "lien": "existante"}
    [precision] = micros.get_micro(brancher["id"])["precisions"]
    assert ETENDRE_APRES in precision["texte"] and "Castor" in precision["texte"]


def test_un_autre_chantier_ou_une_autre_nature_n_est_pas_un_doublon():
    macro, mere = _chantier()
    ouvrir_micros_de_cloture([ETENDRE], ticket_id="T1", slug="portail-enigmes")

    #  Même libellé voisin, mais une DÉCISION : ce n'est pas le même geste.
    decision = ouvrir_micros_de_cloture([{"titre": ETENDRE_APRES, "decision": True}],
                                        ticket_id="T2", slug="portail-enigmes")
    #  Sans chantier (ticket d'aucune tâche) : pas le même chantier.
    orpheline = ouvrir_micros_de_cloture([ETENDRE_APRES], ticket_id="HORS", slug="portail-enigmes")

    assert len(decision) == 1 and len(orpheline) == 1


def test_une_tache_close_ne_retient_pas_le_point():
    macro, mere = _chantier()
    [ancienne] = ouvrir_micros_de_cloture([ETENDRE], ticket_id="T1", slug="portail-enigmes")
    micros.marquer_etat(ancienne["id"], "abandonnee")

    assert len(ouvrir_micros_de_cloture([ETENDRE_APRES], ticket_id="T2", slug="portail-enigmes")) == 1
