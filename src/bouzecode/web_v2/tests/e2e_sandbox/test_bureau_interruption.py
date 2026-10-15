# [desc] Bureau — parler à l'assistant et à ses agents PENDANT qu'ils travaillent (U19) : message lu à la prochaine étape, Interrompre (bouton, Échap) sans perte d'état, précision transmise à un agent de tâche en ajout puis en interruption, agent au repos réveillé, brief complété, lecture visible sur la carte. [/desc]
"""Parcours U19 de SPEC.md contre le vrai profil `bureau-assistant` et de vrais agents de tâche,
pilotés par le faux LLM. Un message déposé pendant un tour devient un NOUVEL énoncé à la
frontière de tour suivante ; son tag `[scn:…]` prend alors la main : c'est ce qui prouve QUAND
il a été lu (les étapes restantes du scénario d'origine n'ont jamais lieu)."""
from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import expect

from bureau_e2e_support import (  # noqa: F401
    DEPOT, MARQUES, TOAST_INFO, TOAST_OK, api, attendre, attendre_statut, bz_browser, bz_page,
    creer_tache, ligne, ouvrir_bureau, tache_loc, uid,
)
from test_bureau_assistant import AGENT, _demarrer, _envoyer, _ouvrir

pytestmark = [*MARQUES, pytest.mark.couvre(
    "templates/bureau.html",
    "static/css/bureau.css",
    "static/js/bureau/**",
    "static/js/lib/**",
    "static/js/shared/session_thread.js",
    "routes/sessions/**",
    "routes/work/micros/**",
    "routes/work/fleet.py",
    "services/work/file_messages.py",
    "services/work/interruption.py",
    "services/work/taches_actions.py",
    "services/work/micros.py",
    "services/work/bureau_lignes.py",
    "runtime/ipc.py",
    "/src/bouzecode/backend/agent/loop.py",
    "/src/bouzecode/backend/tools/bureau_tools.py",
    "/src/bouzecode/ui/repl.py",
    "/tests/sandbox/mock_llm_server.py",
)]

RELAYE = "relayée par l'assistant du Bureau"


def _blocs(agent_id: str) -> list[dict]:
    return api("GET", f"/api/sessions/agent/{agent_id}/blocks?plain=1")["blocks"]


def _textes(agent_id: str) -> list[str]:
    return [f"{b['role']}:{b['text']}" for b in _blocs(agent_id)]


def _index(blocs: list[str], morceau: str) -> int:
    return next(i for i, b in enumerate(blocs) if morceau in b)


def _attendre_lu(page, echo, texte: str, timeout: int) -> None:
    """Le message a été lu. L'écho passe « lu », puis s'efface dès que le vrai message arrive dans
    le fil (`session_thread.purgeProvisional`) : les deux prouvent la lecture. N'attendre que
    « lu » échouait quand le bloc arrivait entre deux sondages (1 fois sur 3 en isolé)."""
    lu = echo.locator(".bz-echo__etat", has_text=re.compile(r"^lu$")).or_(
        page.locator("#assistant-messages .block.user", has_text=texte))
    expect(lu.first).to_be_visible(timeout=timeout)


def _agent_de(micro_id: str) -> str:
    def trouve():
        passages = (ligne(micro_id) or {}).get("passages") or []
        return passages[0].get("agent_id") if passages else ""
    return attendre(trouve, 60, 0.5, "agent de la tâche né")


def _tache_qui_tourne(scenario: str) -> tuple[str, str]:
    t = creer_tache(uid("Interruption"), f"[scn:{scenario}]", projet_slug=DEPOT)
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre_statut(t["id"], "en_cours", 60)
    return t["id"], _agent_de(t["id"])


# ---------------------------------------------------------------- parler à l'assistant


def test_un_message_ecrit_pendant_que_l_assistant_travaille_arrive_a_sa_prochaine_etape(bz_page):
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    conv = _demarrer(bz_page, "Fais le point sur la flotte [scn:assistant-etapes]")
    agent_id = conv["key"].split("/", 1)[1]
    expect(bz_page.locator("#assistant-stop")).to_be_visible(timeout=AGENT)
    expect(bz_page.locator("#assistant-input")).to_be_editable()
    _envoyer(bz_page, "Note aussi le dépôt demo-front [scn:reply]")
    echo = bz_page.locator(".bz-echo").filter(has_text="Note aussi le dépôt demo-front")
    expect(echo.locator(".bz-echo__etat")).to_contain_text("lira à sa prochaine étape", timeout=10000)
    _attendre_lu(bz_page, echo, "Note aussi le dépôt demo-front", AGENT)
    attendre(lambda: any("Voici ma réponse" in b for b in _textes(agent_id)), 60, 0.5, "réponse au message")
    blocs = _textes(agent_id)
    arrivee = _index(blocs, "Note aussi le dépôt demo-front")
    assert arrivee > _index(blocs, "Je relis la flotte"), blocs
    assert blocs[arrivee - 1].startswith("tool:"), "livré après le lot d'outils en cours"
    assert not any("Point de flotte fait" in b for b in blocs), "livré AVANT la fin du travail"


def test_echap_interrompt_un_long_streaming_sans_rien_perdre(bz_page):
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    conv = _demarrer(bz_page, "Lis la flotte puis développe [scn:assistant-lent]")
    agent_id = conv["key"].split("/", 1)[1]
    attendre(lambda: any(b["name"] == "Flotte" for b in _blocs(agent_id)), 60, 0.5, "1er lot d'outils fait")
    expect(bz_page.locator("#assistant-messages .streaming-turn")).to_contain_text("Je développe", timeout=30000)
    bz_page.locator("#assistant-input").focus()
    bz_page.keyboard.press("Escape")
    expect(bz_page.locator(TOAST_INFO).filter(has_text="Assistant interrompu")).to_be_visible(timeout=15000)
    expect(bz_page.locator("#assistant-drawer")).to_have_attribute("data-open", "true")
    expect(bz_page.locator("#assistant-stop")).to_be_hidden(timeout=15000)
    blocs = _blocs(agent_id)
    assert any(b["name"] == "Flotte" and b["role"] == "tool" for b in blocs), "résultat d'outil gardé"
    assert not any("Réponse longue terminée" in b["text"] for b in blocs)
    # La conversation continue normalement : rien n'est resté à moitié écrit.
    _envoyer(bz_page, "Et ensuite ? [scn:reply]")
    attendre(lambda: any("Voici ma réponse" in b for b in _textes(agent_id)), 60, 0.5, "reprise après interruption")
    assert any(b["name"] == "Flotte" for b in _blocs(agent_id))


def test_un_message_envoye_juste_apres_interrompre_apparait_dans_le_fil(bz_page):
    """Le tour coupé laisse un message éphémère que la reprise retire de la session : les index
    du fil se décalent. Le message envoyé ensuite (et la réponse) doivent quand même s'afficher."""
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    conv = _demarrer(bz_page, "Rédige longuement [scn:slow]")
    agent_id = conv["key"].split("/", 1)[1]
    expect(bz_page.locator("#assistant-messages .streaming-turn")).to_be_visible(timeout=AGENT)
    bz_page.locator("#assistant-stop").click()
    expect(bz_page.locator("#assistant-stop")).to_be_hidden(timeout=15000)
    _envoyer(bz_page, "Et maintenant ? [scn:reply]")
    attendre(lambda: any("Voici ma réponse" in b for b in _textes(agent_id)), 60, 0.5, "réponse au message")
    fil = bz_page.locator("#assistant-messages")
    expect(fil.locator(".block.user").filter(has_text="Et maintenant ?")).to_have_count(1, timeout=10000)
    expect(fil.locator(".block.assistant").filter(has_text="Voici ma réponse")).to_have_count(1)
    expect(fil.locator(".block.user").filter(has_text="Rédige longuement")).to_have_count(1)


def _chevauche(a: dict, b: dict) -> bool:
    return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])


@pytest.mark.parametrize("largeur", [1440, 390])
def test_apres_interrompre_le_fil_le_dit_et_le_toast_laisse_le_champ_libre(bz_browser, largeur):
    ctx = bz_browser.new_context(viewport={"width": largeur, "height": 900})
    page = ctx.new_page()
    try:
        ouvrir_bureau(page)
        _ouvrir(page)
        _demarrer(page, "Rédige longuement [scn:slow]")
        expect(page.locator("#assistant-messages .streaming-turn")).to_be_visible(timeout=AGENT)
        page.locator("#assistant-stop").click()
        toast = page.locator(TOAST_INFO).filter(has_text="Assistant interrompu")
        expect(toast).to_be_visible(timeout=15000)
        for cible in ("#assistant-input", "#assistant-send"):
            assert not _chevauche(toast.bounding_box(), page.locator(cible).bounding_box()), f"le toast masque {cible}"
        expect(page.locator("#assistant-messages .block.assistant").last).to_contain_text("interrompu", timeout=15000)
    finally:
        ctx.close()


def test_interrompre_repart_aussitot_avec_le_message_en_attente(bz_page):
    ouvrir_bureau(bz_page)
    _ouvrir(bz_page)
    conv = _demarrer(bz_page, "Lis la flotte puis développe [scn:assistant-lent]")
    agent_id = conv["key"].split("/", 1)[1]
    expect(bz_page.locator("#assistant-messages .streaming-turn")).to_contain_text("Je développe", timeout=AGENT)
    _envoyer(bz_page, "Laisse tomber, parle-moi de demo-api [scn:reply]")
    echo = bz_page.locator(".bz-echo").filter(has_text="Laisse tomber")
    expect(echo.locator(".bz-echo__etat")).to_contain_text("lira à sa prochaine étape", timeout=10000)
    debut = time.time()
    bz_page.locator("#assistant-stop").click()
    expect(bz_page.locator(TOAST_INFO).filter(has_text="il repart avec ton message")).to_be_visible(timeout=15000)
    _attendre_lu(bz_page, echo, "Laisse tomber", 30000)
    attendre(lambda: any("Voici ma réponse" in b for b in _textes(agent_id)), 30, 0.5, "réponse au message")
    assert time.time() - debut < 30, "sans interruption, il aurait fallu attendre la fin du long streaming"


# ---------------------------------------------------------------- transmettre à un agent de tâche


def test_l_assistant_transmet_une_precision_a_l_agent_en_cours_qui_la_lit_a_sa_prochaine_etape(bz_page):
    micro_id, agent_id = _tache_qui_tourne("etapes")
    ouvrir_bureau(bz_page, "en_cours")
    _ouvrir(bz_page)
    _demarrer(bz_page, f"[scn:bureau-preciser] tâche={micro_id} "
                       "précision=«finalement le fichier doit s'appeler AJOUT.md — Fichier : AJOUT.md {scn:ecrire-fichier}»")
    expect(bz_page.locator("#assistant-messages")).to_contain_text("Précision transmise", timeout=AGENT)
    carte = tache_loc(bz_page, micro_id).locator(".bz-task__transmis")
    expect(carte).to_contain_text("✎ Précision transmise à", timeout=20000)
    expect(carte).to_have_attribute("data-lecture", "lue", timeout=AGENT)
    expect(carte).to_contain_text("lue par l'agent")
    attendre_statut(micro_id, "a_relire", 90)
    blocs = _textes(agent_id)
    arrivee = _index(blocs, RELAYE)
    assert blocs[arrivee - 1].startswith("tool:"), "injectée à la frontière de tour, après un lot d'outils"
    assert "AJOUT.md" in blocs[arrivee] and "CHANGEMENT DE CONSIGNE" in blocs[arrivee]
    assert any("AJOUT.md" in b for b in blocs[arrivee + 1:]), "l'agent en a tenu compte"
    assert sum("echo etape" in str(b) for b in _blocs(agent_id)) < 4, "pas à la fin du travail"
    # Le brief est complété : une relance future recevra la précision.
    micro = api("GET", f"/api/micros/{micro_id}")["micro"]
    assert "Précisions ajoutées" in micro["prompt"] and "AJOUT.md" in micro["prompt"]


def test_l_assistant_interrompt_un_agent_parti_dans_une_mauvaise_direction(bz_page):
    micro_id, agent_id = _tache_qui_tourne("slow")
    debut = time.time()
    ouvrir_bureau(bz_page, "en_cours")
    _ouvrir(bz_page)
    _demarrer(bz_page, f"[scn:bureau-preciser] tâche={micro_id} interrompre=oui "
                       "précision=«arrête, écris plutôt STOP.md — Fichier : STOP.md {scn:ecrire-fichier}»")
    expect(bz_page.locator("#assistant-messages")).to_contain_text("Précision transmise", timeout=AGENT)
    expect(tache_loc(bz_page, micro_id).locator(".bz-task__transmis")).to_contain_text("tour interrompu", timeout=20000)
    attendre_statut(micro_id, "a_relire", 90)
    blocs = _textes(agent_id)
    assert any("STOP.md" in b for b in blocs[_index(blocs, RELAYE) + 1:])
    assert not any("Réponse lente terminée" in b for b in blocs), "le long tour a bien été coupé"
    assert time.time() - debut < 60


def test_une_precision_reveille_l_agent_au_repos(bz_page):
    t = creer_tache(uid("Repos"), "[scn:reply]", projet_slug=DEPOT)
    api("POST", f"/api/micros/{t['id']}/lancer", {"projet_slug": DEPOT}, attendu=200)
    attendre_statut(t["id"], "a_relire", 90)
    agent_id = _agent_de(t["id"])
    r = api("POST", f"/api/micros/{t['id']}/precisions",
            {"texte": "Ajoute REVEIL.md — Fichier : REVEIL.md [scn:ecrire-fichier]", "transmettre": True}, attendu=201)
    assert [x["agent_id"] for x in r["transmis"]] == [agent_id]
    attendre(lambda: any("REVEIL.md est écrit" in b for b in _textes(agent_id)), 90, 1, "agent réveillé")
    ouvrir_bureau(bz_page)
    expect(tache_loc(bz_page, t["id"]).locator(".bz-task__transmis")).to_have_attribute("data-lecture", "lue",
                                                                                     timeout=30000)
