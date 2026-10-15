# [desc] Titres lisibles : un ticket / agent s'appelle par ce qu'on lui demande (l'objectif du brief), pas par la 1re ligne d'un prompt de contexte ou d'un gabarit — cas réels de l'essai du 2026-09-24/25. [/desc]
"""La liste des agents disait « Tu travailles sur le projet « portail d… », « Dans le chantier
« Portail des énigm… » (×2), « Reprends la tâche interrompue là o… » : la 1re ligne du prompt,
qui est du CONTEXTE (où travailler) ou un GABARIT (l'enveloppe d'une demande), jamais la demande.

Le brief complet reste intact (`prompt`, `title_full`) : seul le titre court change.
"""
import pytest

from bouzecode.web_v2.services.work import titres

#  Débuts RÉELS de prompts relevés dans ~/bouzecode-essai/.bouzecode/web_v2/tickets/tickets.db.
GABARIT = ("Dans le chantier « Portail des énigmes », crée et lance une tâche dont le brief est "
           "exactement le texte suivant :\n\nJe ne veux pas juste rediriger vers des liens vers les "
           "sites, mais scrapper les énigmes des sites. Par exemple, commence par le kangourou.")
CONTEXTE_PUIS_OBJECTIF = (
    "Tu travailles dans le dépôt git `/home/simon/portail-enigmes` (worktree dédié). Commence par "
    "`Environment(action='worktree')` pour t'isoler, puis LIS `SPEC.md` à la racine.\n\n"
    "## OBJECTIF (vérifiable)\nLivrer la partie « consultation » du portail : un serveur local "
    "stdlib + une page `tinder.html` de revue d'énigmes (accepter / refuser / révéler la solution).\n\n"
    "## PÉRIMÈTRE — fichiers que TU écris\n- `server.py`\n")
CONTEXTE_PUIS_MISSION = (
    "Tu travailles sur le projet « portail des énigmes » : /home/simon/portail-enigmes (dépôt git, "
    "branche main). Demande d'abord ton worktree.\n\n## Contexte mesuré (ne le re-mesure pas)\n"
    "- `scraper/kangourou.py` existe déjà et fonctionne.\n- Codes sujets : e, b, c, j, p, s.\n\n"
    "## Ta mission : 5 points de correction du scraping\n**1) FIGURES — image recadrée.**\n")
OBJECTIF_EN_TETE = ("OBJECTIF : corriger le parsing, le barème et l'affichage des figures du scraper "
                    "Kangourou dans le dépôt /home/simon/portail-enigmes.\nPÉRIMÈTRE : `scraper/kangourou.py`.")
MISSION_TIRET = ("MISSION — Lot B du portail des énigmes : serveur local + interface « Tinder ». Tu es en "
                 "autonomie complète.\nDÉMARRAGE OBLIGATOIRE :\n1. `Environment(action='worktree')`")
TITRE_MARKDOWN = ("Tu es dans le dépôt git `/home/simon/bouzecode-essai` (worktree déjà provisionné).\n"
                  "# Objectif (livrable unique et fermé)\nRéécrire entièrement `/index.html` en "
                  "application **mono-fichier** « Portail des énigmes ».\n# Contexte mesuré\n- x\n")
TACHE_DU_BUREAU = ("Scraper les énigmes des sites et les présenter dans une interface style Tinder\n\n"
                   "Chantier : Portail des énigmes (id 9d17f256)\n\nJe ne veux pas juste rediriger…")
DEMANDE_HUMAINE = ("J'ai testé le portail des énigmes livré par la tâche \"Scraper les énigmes\" et voici "
                   "mes retours :\n1. « La moitié des énigmes parlent d'un dessin que je ne vois pas »")


@pytest.mark.parametrize("prompt, attendu", [
    (GABARIT, "Je ne veux pas juste rediriger vers des liens vers les sites, mais scrapper…"),
    (CONTEXTE_PUIS_OBJECTIF, "Livrer la partie « consultation » du portail : un serveur local stdlib + une…"),
    (CONTEXTE_PUIS_MISSION, "5 points de correction du scraping"),
    (OBJECTIF_EN_TETE, "Corriger le parsing, le barème et l'affichage des figures du scraper Kangourou…"),
    (MISSION_TIRET, "Lot B du portail des énigmes : serveur local + interface « Tinder »"),
    (TITRE_MARKDOWN, "Réécrire entièrement `/index.html` en application mono-fichier « Portail des…"),
    (TACHE_DU_BUREAU, "Scraper les énigmes des sites et les présenter dans une interface style Tinder"),
    (DEMANDE_HUMAINE, "J'ai testé le portail des énigmes livré par la tâche \"Scraper les énigmes\" et…"),
])
def test_titre_lisible_des_cas_reels(prompt, attendu):
    titre = titres.titre_lisible(prompt)
    assert titre == attendu
    assert len(titre) <= titres.TITRE_MAX


def test_jamais_vide_et_jamais_du_contexte():
    assert titres.titre_lisible("") == ""
    assert titres.titre_lisible("Tu travailles dans le dépôt git `/x`.") == "Tu travailles dans le dépôt git `/x`"
    assert not titres.titre_lisible(CONTEXTE_PUIS_OBJECTIF).startswith("Tu travailles")


def test_l_outil_agent_titre_un_ticket_neuf_par_son_objectif():
    from bouzecode.backend.multi_agent.client_tickets import _titre
    assert _titre({"prompt": CONTEXTE_PUIS_OBJECTIF}).startswith("Livrer la partie « consultation »")


def test_un_agent_repris_garde_le_nom_de_celui_qu_il_reprend(tmp_path):
    """« Reprends la tâche interrompue là où elle s'est arrêtée. » n'est pas un nom d'agent."""
    from types import SimpleNamespace
    from bouzecode.web_v2.runtime.runner import agent_reprise
    from bouzecode.web_v2.services.work import fleet
    origine = SimpleNamespace(agent_id="40ea29e4253a", prompt=CONTEXTE_PUIS_MISSION, run_kind="work",
                              reprise_de="", titre="")
    reprise = SimpleNamespace(agent_id="84678d1f88b1", prompt=agent_reprise.RESUME_PROMPT, run_kind="work",
                              reprise_de="40ea29e4253a", titre=titres.titre_lisible(CONTEXTE_PUIS_MISSION))
    assert fleet._short_label(origine) == "5 points de correction du scraping"
    assert fleet._short_label(reprise) == "5 points de correction du scraping"
    ancienne = SimpleNamespace(agent_id="x", prompt=agent_reprise.RESUME_PROMPT, run_kind="work")
    assert fleet._short_label(ancienne) == "Reprise d'un agent arrêté"


def test_le_titre_d_une_tache_ecrite_d_un_trait_s_arrete_a_la_premiere_phrase():
    """Brief réel tapé sur UNE ligne : le titre coupait à 120 caractères en plein mot
    (« … Par exemple, commence »). Il s'arrête à la 1re phrase, ou au mot avec « … »."""
    from bouzecode.web_v2.services.work import micros
    brief = ("Je ne veux pas juste rediriger vers des liens vers les sites, mais scrapper les énigmes "
             "des sites. Par exemple, commence par le kangourou. je veux une interface style \"tinder\".")
    assert micros.titre_depuis_corps(brief) == ("Je ne veux pas juste rediriger vers des liens vers les "
                                                "sites, mais scrapper les énigmes des sites")
    sans_point = "mot " * 60
    titre = micros.titre_depuis_corps(sans_point)
    assert titre.endswith("…") and len(titre) <= micros.TITRE_MAX and " mo…" not in titre
    assert micros.titre_depuis_corps("Corriger le login") == "Corriger le login"
    #  Le brief n'est pas dupliqué dans le prompt de l'agent pour autant.
    assert micros._titre_deja_en_tete(micros.titre_depuis_corps(brief), brief)
    assert micros._titre_deja_en_tete(titre, sans_point)
