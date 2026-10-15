"""Point 4 du ticket 7fb5f816 : le mandat READ-ONLY ne doit s'armer que sur le DÉPÔT.

Quatre tickets bien cadrés d'affilée ont déclenché « MANDAT READ-ONLY NON TENU » le
2026-08-25 parce que l'interdiction d'écriture visait une base de données ou un fichier
nommé, pas le dépôt. Un avertissement qui crie sur les tickets corrects n'est plus lu.

Fonctions pures : ni serveur, ni réseau, ni mock.
"""
from bouzecode.web_v2.services.scope_guard.readonly import (
    declares_read_only,
    unenforced_read_only,
)

# Prompts réels (reformulés au plus près) des faux positifs du 2026-08-25.
FAUX_POSITIFS = [
    "Base DEMODB en lecture seule : SELECT uniquement. "
    "Écriture autorisée sur le seul fichier docs/rapport_rmm.md.",
    "Analyse le flux de facturation. Ne modifie aucun fichier hors de "
    "src/bouzecode/backend/billing.py, et ne touche à aucun autre fichier du dépôt.",
    "Tu peux écrire dans tests/. Aucune écriture sur la base partagée : "
    "ne lance pas le seed en écriture sur la base de données.",
    "Interroge l'API de supervision sans écrire dessus (GET uniquement, "
    "aucune écriture sur l'endpoint). Corrige ensuite src/bouzecode/web_v2/api.py.",
]

# Vrais mandats : l'interdiction porte sur le dépôt lui-même, sans exception accordée.
VRAIS_MANDATS = [
    "Mandat READ-ONLY : n'écris aucun fichier, ne commite rien, rends un rapport.",
    "Investigation en lecture seule du dépôt : ne modifie aucun fichier, "
    "aucun fichier de produit ne doit changer.",
]


def test_les_faux_positifs_ne_declarent_plus_un_mandat_read_only():
    for prompt in FAUX_POSITIFS:
        assert declares_read_only(prompt) is False, prompt


def test_les_vrais_mandats_restent_detectes():
    for prompt in VRAIS_MANDATS:
        assert declares_read_only(prompt) is True, prompt


def test_aucun_avertissement_sur_un_ticket_cadre_qui_ecrit_un_fichier_nomme():
    """La typologie accorde des outils d'écriture : c'est LÉGITIME ici, donc silence."""
    for prompt in FAUX_POSITIFS:
        assert unenforced_read_only(prompt, "dev") == [], prompt


def test_l_avertissement_survit_sur_un_vrai_mandat_avec_outils_d_ecriture():
    contradictions = unenforced_read_only(VRAIS_MANDATS[0], "dev")
    assert contradictions, "un mandat read-only + outils d'écriture doit rester signalé"
