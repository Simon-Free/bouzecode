# [desc] Import LAZY du store legacy `{slug}.json` vers SQLite : une fois, dans l'ordre, jamais deux fois. [/desc]
"""Le dernier chemin qui lit encore un `{slug}.json` d'avant SQLite.

Il n'avait AUCUN test, alors que son effet de bord — la mémoire `_migrated`, un `set` de
PROCESS — a rendu VIDES deux assertions de `test_subagent_events` : le premier test d'un
module migrait la graine, les suivants voyaient un store vide et n'observaient plus rien.

Ces tests sont écrits pour être honnêtes SEULS comme en contexte de fichier : chacun pose
lui-même l'état de `_migrated` au lieu d'hériter de celui du test précédent (la fixture
autouse le remet à vide, ces tests ne s'y fient pas pour ce qu'ils prouvent).
Vraie base SQLite dans un TICKETS_DIR temporaire, aucun mock.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.services.work import _persistence, tickets

SLUG = "projet-d-avant"


def _semer_json_legacy(*tickets_json: dict) -> None:
    """Écrit le fichier legacy tel que l'ancien store le laissait : liste RÉCENT EN TÊTE."""
    _persistence.TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    (_persistence.TICKETS_DIR / f"{SLUG}.json").write_text(
        json.dumps(list(tickets_json)), encoding="utf-8")


def _ticket(ident: str, titre: str) -> dict:
    return {"id": ident, "title": titre, "prompt": "p", "created_at": "2026-01-01T00:00:00",
            "done": False, "comments": [], "runs": []}


def test_un_store_legacy_est_importe_a_la_premiere_lecture():
    """Ouvrir un projet jamais rouvert depuis la migration rend ses tickets d'avant."""
    _semer_json_legacy(_ticket("recent", "Le plus récent"), _ticket("ancien", "Le plus ancien"))

    lus = tickets.list_tickets(SLUG)

    assert [t["id"] for t in lus] == ["recent", "ancien"], "l'ordre récent-en-tête est perdu"
    assert tickets.get_ticket(SLUG, "ancien")["title"] == "Le plus ancien"


def test_le_fichier_legacy_est_marque_consomme():
    """Le `.json` devient `.json.migrated` : une trace, plus une source."""
    _semer_json_legacy(_ticket("t1", "T"))

    tickets.list_tickets(SLUG)

    assert not (_persistence.TICKETS_DIR / f"{SLUG}.json").exists()
    assert (_persistence.TICKETS_DIR / f"{SLUG}.json.migrated").is_file()


def test_relire_le_projet_ne_duplique_pas_les_tickets_importes():
    """Idempotence RÉELLE, indépendante de la mémoire de process : même en oubliant que le
    slug a été migré, une seconde passe ne réimporte rien (les lignes existent déjà)."""
    _semer_json_legacy(_ticket("t1", "T"), _ticket("t2", "U"))
    tickets.list_tickets(SLUG)

    _persistence._migrated.clear()  # comme au boot suivant du serveur : mémoire vierge
    relus = tickets.list_tickets(SLUG)

    assert [t["id"] for t in relus] == ["t1", "t2"]


def test_une_modification_faite_apres_l_import_survit_a_une_relecture():
    """Garde-fou de PERTE : le legacy ne doit jamais réécraser le travail fait depuis.
    C'est ce que le renommage et le compte de lignes protègent ensemble."""
    _semer_json_legacy(_ticket("t1", "Titre d'origine"))
    tickets.list_tickets(SLUG)
    tickets.add_comment(SLUG, tickets.get_ticket(SLUG, "t1"), "écrit après la migration", False)

    _persistence._migrated.clear()
    frais = tickets.get_ticket(SLUG, "t1")

    assert [c["text"] for c in frais["comments"]] == ["écrit après la migration"]


def test_un_slug_sans_legacy_ne_fabrique_aucun_ticket():
    """Un projet inconnu ne rend rien et ne crée aucun fichier — pas de faux store."""
    assert tickets.list_tickets("slug-jamais-vu") == []
    assert not (_persistence.TICKETS_DIR / "slug-jamais-vu.json.migrated").exists()


def test_un_json_legacy_illisible_n_empeche_pas_d_ouvrir_le_projet():
    """Un fichier tronqué (crash d'écriture de l'ère JSON) ne doit pas rendre le projet
    inouvrable : on l'écarte, on le marque consommé, et le projet repart de zéro."""
    _persistence.TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    (_persistence.TICKETS_DIR / f"{SLUG}.json").write_text("[{tronqué", encoding="utf-8")

    assert tickets.list_tickets(SLUG) == []
    assert (_persistence.TICKETS_DIR / f"{SLUG}.json.migrated").is_file()


def test_la_memoire_de_process_ne_fait_pas_disparaitre_un_store_deja_en_base():
    """`_migrated` n'est qu'un raccourci : un slug marqué migré reste parfaitement lisible.
    (C'est l'inverse qui a mordu : un slug marqué migré dont la graine n'était QUE sur
    disque devenait invisible — d'où des tests verts qui n'observaient plus rien.)"""
    cree = tickets.create_ticket(SLUG, "Né en base", "p")

    assert SLUG in _persistence._migrated
    assert [t["id"] for t in tickets.list_tickets(SLUG)] == [cree["id"]]


def test_une_graine_legacy_posee_apres_le_premier_acces_est_ignoree():
    """Contrat explicite, et piège documenté : une fois le slug marqué migré, déposer un
    `{slug}.json` ne le fait PAS entrer en base. Un test qui sème ainsi n'observe rien —
    c'est exactement la panne corrigée dans test_subagent_events."""
    tickets.create_ticket(SLUG, "Né en base", "p")  # marque le slug migré
    _semer_json_legacy(_ticket("fantome", "Jamais importé"))

    assert tickets.get_ticket(SLUG, "fantome") is None


@pytest.mark.parametrize("nombre", [1, 5])
def test_l_ordre_du_fichier_legacy_est_conserve_quel_que_soit_le_volume(nombre: int):
    """L'ordre d'affichage (récent en tête) est celui du fichier, pas celui de l'insertion."""
    attendus = [f"t{i}" for i in range(nombre)]
    _semer_json_legacy(*[_ticket(ident, ident.upper()) for ident in attendus])

    assert [t["id"] for t in tickets.list_tickets(SLUG)] == attendus
