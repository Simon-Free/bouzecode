# [desc] Tests pytest de prompt_de : plus de titre dérivé redondant, macro conservée, infos communes du chantier injectées [/desc]
"""Le geste utilisateur teste ici : depuis /bureau, je clique « Lancer un agent » sur une
ligne. Ce que l'agent recoit est construit par `prompt_de`, cote serveur, et rien d'autre.

Demande utilisateur du 2026-09-08 :
  1. ne plus envoyer un « Titre » qui n'est que le contenu tronque, repete juste apres ;
  2. garder la macro-tache de rattachement ;
  3. pouvoir ecrire des INFORMATIONS COMMUNES au niveau de la macro-tache (les depots ou
     l'on va travailler, les conventions, les chiffres de reference) et les retrouver dans
     le brief de CHAQUE agent lance depuis ce chantier.

On appelle `prompt_de` avec la meme forme de dict que `_vue` lui passe : pas de mock,
pas de HTTP, pas de LLM.
"""
from __future__ import annotations

from bouzecode.web_v2.services.work.micros import prompt_de, titre_depuis_corps

CORPS = ("Ameliorer le prompt envoye a l'assistant\n"
         "\n"
         "On ne veut plus du titre tronque, on veut le contexte du chantier.")

INFOS = ("Depots : bouzecode (web_v2) et demo.\n"
         "Le serveur tourne sur http://127.0.0.1:5056.")


def _micro(titre: str = "", corps: str = CORPS, macro: dict | None = None) -> dict:
    """La forme exacte que `_vue` passe a `prompt_de` : le dict macro COMPLET."""
    return {"titre": titre or titre_depuis_corps(corps), "corps": corps, "macro": macro}


def test_le_prompt_ne_repete_pas_le_titre_derive_du_corps():
    """Cas courant : le titre n'est PAS saisi, il est derive du corps (titre_depuis_corps).
    L'envoyer en tete revient a repeter la premiere ligne du corps deux fois."""
    prompt = prompt_de(_micro())

    assert "Tache :" not in prompt and "Tâche :" not in prompt, prompt
    assert prompt.strip().startswith("Ameliorer le prompt"), prompt
    assert CORPS.strip() in prompt, prompt


def test_un_titre_saisi_a_la_main_reste_dans_le_prompt():
    """Si l'humain a donne au ticket un libelle qui n'est pas la premiere ligne du corps,
    ce libelle porte une information : on le garde."""
    prompt = prompt_de(_micro(titre="Refonte du brief d'agent"))

    assert "Refonte du brief d'agent" in prompt, prompt


def test_un_titre_sans_corps_reste_dans_le_prompt():
    """Un ticket peut n'avoir qu'un titre : le brief ne doit pas etre vide."""
    prompt = prompt_de(_micro(titre="Corriger le blanc-sur-blanc du Bureau", corps=""))

    assert "Corriger le blanc-sur-blanc du Bureau" in prompt, prompt


def test_les_informations_communes_du_chantier_entrent_dans_le_prompt():
    macro = {"id": "m1", "titre": "Finir l'assistant", "corps": INFOS, "etat": "active"}

    prompt = prompt_de(_micro(macro=macro))

    assert "Finir l'assistant" in prompt, prompt
    assert "Depots : bouzecode (web_v2) et demo." in prompt, prompt
    assert "http://127.0.0.1:5056" in prompt, prompt


def test_un_chantier_sans_informations_communes_najoute_rien():
    macro = {"id": "m1", "titre": "Finir l'assistant", "corps": "   ", "etat": "active"}

    prompt = prompt_de(_micro(macro=macro))

    assert "Finir l'assistant" in prompt, prompt
    #  Aucun en-tete de bloc vide : un brief ne contient pas de rubrique sans contenu.
    assert "commun" not in prompt.lower(), prompt


def test_les_precisions_validees_restent_apres_le_contexte():
    """Non-regression : l'arbitrage humain du §9 (precisions validees seulement) survit."""
    macro = {"id": "m1", "titre": "Finir l'assistant", "corps": INFOS}
    micro = _micro(macro=macro)
    micro["precisions"] = [
        {"auteur": "humain", "texte": "commence par le backend", "statut": "validee"},
        {"auteur": "agent", "texte": "ne pas toucher a la TO-DO", "statut": "en_attente_de_validation"},
    ]

    prompt = prompt_de(micro)

    assert "commence par le backend" in prompt, prompt
    assert "ne pas toucher a la TO-DO" not in prompt, prompt
    assert prompt.index("Depots :") < prompt.index("commence par le backend"), prompt


LONG = ("Je ne veux pas juste rediriger vers des liens vers les sites, mais scrapper les "
        "enigmes des sites. Par exemple, commence par le kangourou.\n\nDetails ensuite.")


def test_un_titre_tronque_de_la_premiere_ligne_n_est_pas_repete():
    """Brief seul : le titre stocke est la 1re ligne COUPEE (avec ou sans « … »). L'aperçu du
    prompt montrait ce debut de phrase puis le meme paragraphe en entier : doublon."""
    for titre in ("Je ne veux pas juste rediriger vers des liens vers les sites",
                  "Je ne veux pas juste rediriger vers des liens vers les sites…"):
        prompt = prompt_de(_micro(titre=titre, corps=LONG))
        assert prompt.count("Je ne veux pas juste rediriger") == 1, prompt


def test_le_prompt_donne_l_id_du_chantier_pour_rattacher_les_taches_restantes():
    """Sans l'id, l'agent ne pouvait pas remplir taches_restantes.macro_id."""
    macro = {"id": "9d17f256", "titre": "Portail des énigmes", "corps": "", "etat": "active"}
    prompt = prompt_de(_micro(macro=macro))
    assert "Chantier : Portail des énigmes (id 9d17f256)" in prompt, prompt
