# [desc] Defilement horizontal d'une ligne trop large de la barre des agents, temps injecte : immobile si elle tient, pause au debut, glissement vers la gauche, pause en fin, retour a 0. [/desc]
from __future__ import annotations

from bouzecode.ui.barre_agents.defilement import PAUSE_DEBUT, PAUSE_FIN, VITESSE, decalage, fenetre

TEXTE = "".join(chr(ord("a") + k % 26) for k in range(50))   # 50 caracteres
LARGEUR = 30                                                 # debord de 20
COURSE = 20 / VITESSE
CYCLE = PAUSE_DEBUT + COURSE + PAUSE_FIN


def test_un_texte_qui_tient_ne_bouge_jamais():
    assert {fenetre("court", 30, t / 10) for t in range(200)} == {"court"}
    assert decalage(30, 30, 12.3) == 0


def test_pause_au_debut_puis_glissement_vers_la_gauche():
    assert decalage(50, LARGEUR, 0.0) == 0
    assert decalage(50, LARGEUR, PAUSE_DEBUT - 0.01) == 0
    assert decalage(50, LARGEUR, PAUSE_DEBUT + 1.0) == int(VITESSE)
    positions = [decalage(50, LARGEUR, PAUSE_DEBUT + k * 0.25) for k in range(int(COURSE * 4))]
    assert positions == sorted(positions) and positions[-1] > positions[0]


def test_la_fin_est_montree_pendant_la_pause_puis_retour_a_zero():
    fin_de_course = PAUSE_DEBUT + COURSE
    assert fenetre(TEXTE, LARGEUR, fin_de_course) == TEXTE[-LARGEUR:]
    assert fenetre(TEXTE, LARGEUR, fin_de_course + PAUSE_FIN - 0.01) == TEXTE[-LARGEUR:]
    assert fenetre(TEXTE, LARGEUR, CYCLE) == TEXTE[:LARGEUR]          # cycle suivant


def test_le_cycle_se_repete_et_la_fenetre_garde_la_largeur():
    for t in (0.3, 2.7, 4.1, 5.9):
        assert decalage(50, LARGEUR, t) == decalage(50, LARGEUR, t + 7 * CYCLE)
        assert len(fenetre(TEXTE, LARGEUR, t)) == LARGEUR

