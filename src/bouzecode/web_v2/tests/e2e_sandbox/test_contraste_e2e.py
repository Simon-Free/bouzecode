# [desc] E2E contraste : sur chaque page (Bureau + assistant, Agents, vues d'agent, Enquête, Profils) et dans les 4 états de thème (système clair / sombre, choix explicite qui le contredit), tout texte visible atteint 4,5:1 sur son fond (WCAG AA). [/desc]
"""Contraste texte/fond mesuré dans le navigateur (`contraste_scan.js`) : couleur et fond
EFFECTIFS (fonds translucides empilés, opacité des ancêtres), 4,5:1 pour le texte courant,
3:1 pour le grand texte. Le texte désactivé ou occupé (`aria-busy`) et le décor `aria-hidden` sont exemptés (WCAG 1.4.3).

Bug d'origine (2026-09-24) : l'écho du message envoyé à l'assistant du Bureau était blanc sur
fond clair (`--on-accent` hérité d'une règle dont la page repeignait le fond) en thème système
clair. L'écho ne vit que jusqu'au premier bloc de la conversation : on retient la lecture du fil
le temps de le mesurer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents_e2e_support import BASE, DEPOT, MARQUES, Retenue, api, attendre_etat, browser, expect  # noqa: F401 — fixtures importées

pytestmark = [*MARQUES, pytest.mark.couvre(
    "static/ds.css", "static/app.css", "static/pages.css", "static/css/**", "templates/**",
    "static/js/chrome.js", "static/js/bureau/assistant*.js", "static/js/shared/session_thread.js",
)]

SCAN = (Path(__file__).parent / "contraste_scan.js").read_text(encoding="utf-8")
AGENT = 90_000

#  (nom, préférence du système, choix explicite mémorisé par le bouton ◐)
ETATS = [
    ("systeme-clair", "light", None),
    ("systeme-sombre", "dark", None),
    ("choix-sombre-sur-systeme-clair", "light", "dark"),
    ("choix-clair-sur-systeme-sombre", "dark", "light"),
]
#  Conversations du seed, choisies pour couvrir les rendus : rapport markdown long, question en
#  attente, plan à valider, outils + diff, manager et sous-agents.
VUES_AGENT = ["audit détaillé", "Branche la base", "Refactore le module", "NOTES.md", "Orchestre"]


def _agents_du_seed() -> dict[str, str]:
    noeuds = api("GET", "/api/agents/tree?offset=0&limit=200").get("nodes", [])
    trouves = {}
    for motif in VUES_AGENT:
        n = next((n for n in noeuds if motif in (n.get("title") or "") and str(n.get("key", "")).startswith("agent/")), None)
        if n:
            trouves[motif] = n["key"]
    return trouves


def _mesurer(page, ou: str, echecs: dict, racine: str = "body"):
    trouves = page.evaluate(SCAN, {"racine": racine, "seuil": 4.5})
    if trouves:
        echecs[ou] = trouves


def _attendre(page, selecteur: str):
    expect(page.locator(f"{selecteur} >> visible=true").first).to_be_visible(timeout=20000)


def _assistant(page, echecs: dict):
    """Bureau + tiroir de l'assistant : écho du message envoyé, puis fil rendu (réponse finale)."""
    page.goto(f"{BASE}/bureau")
    _attendre(page, ".bz-task")
    _mesurer(page, "/bureau", echecs)
    page.locator("#assistant-bulle").click()
    expect(page.locator("#assistant-drawer")).to_have_attribute("data-open", "true")
    fil = Retenue(page, "**/api/sessions/**")
    try:
        page.locator("#assistant-input").fill("Contraste de l'écho")
        page.locator("#assistant-input").press("Enter")
        expect(page.locator(".bz-echo.optimistic-echo")).to_be_visible(timeout=AGENT)
        _mesurer(page, "/bureau · assistant (écho du message)", echecs, "#assistant-drawer")
    finally:
        fil.relacher()
    #  Fil complet : on attend la fin du tour côté serveur puis on rouvre le tiroir (la conversation
    #  est reprise), plutôt que d'attendre la relecture lente d'un fil qu'on a retenu. Tour fini =
    #  `idle` (process gardé chaud, le cas normal d'une conversation lancée à la main) ou
    #  `finished` (process sorti). N'attendre que `finished` ne passait que parce que le warm-pool
    #  évinçait toute conversation manuelle quelques secondes après son tour.
    cle = json.loads(page.evaluate("localStorage.getItem('bureau.assistant')"))["key"]
    attendre_etat(cle, {"finished", "idle"}, AGENT / 1000)
    page.reload()
    page.locator("#assistant-bulle").click()
    expect(page.locator("#assistant-messages .final-answer")).to_be_visible(timeout=AGENT)
    _mesurer(page, "/bureau · assistant (fil)", echecs, "#assistant-drawer")
    return cle


def _echo_page_agents(page, key: str, echecs: dict):
    """Page Agents : écho du message envoyé à un agent qui a fini (même piège que l'assistant)."""
    page.goto(f"{BASE}/conversations?agent={key}")
    _attendre(page, ".conv-messages .final-answer")
    fil = Retenue(page, "**/api/sessions/**")
    try:
        champ = page.locator(".ag-composer__input >> visible=true")
        champ.fill("Contraste de l'écho, page Agents")
        champ.press("Enter")
        expect(page.locator(".ag-echo.optimistic-echo >> visible=true")).to_be_visible(timeout=AGENT)
        _mesurer(page, "vue d'agent · écho du message", echecs)
    finally:
        fil.relacher()


@pytest.mark.parametrize("nom,systeme,choix", ETATS, ids=[e[0] for e in ETATS])
def test_tout_texte_visible_est_lisible(browser, nom, systeme, choix):
    agents = _agents_du_seed()
    assert agents, "aucune conversation du seed trouvée"
    ctx = browser.new_context(viewport={"width": 1400, "height": 900}, color_scheme=systeme,
                              reduced_motion="reduce")  # aucune transition : on mesure l'état final
    ctx.add_init_script(f"localStorage.setItem('bureau.assistant.projet', '{DEPOT}')")
    if choix:
        ctx.add_init_script(f"localStorage.setItem('bz.theme.choix', '{choix}')")
    page = ctx.new_page()
    page.set_default_timeout(20000)
    echecs: dict = {}
    try:
        cle_assistant = _assistant(page, echecs)
        attendu = "dark" if choix == "dark" else None
        assert page.evaluate("document.documentElement.dataset.theme || null") == attendu

        page.goto(f"{BASE}/conversations")
        _attendre(page, "#conv-list > *")
        _mesurer(page, "/conversations", echecs)
        for motif, key in agents.items():
            page.goto(f"{BASE}/conversations?agent={key}")
            _attendre(page, ".conv-messages :is(.turn-group, .block)")
            _mesurer(page, f"vue d'agent « {motif} »", echecs)
        _echo_page_agents(page, cle_assistant, echecs)

        page.goto(f"{BASE}/enquete/{next(iter(agents.values())).split('/', 1)[1]}")
        _attendre(page, "#eq-liste > *")
        _mesurer(page, "/enquete", echecs)

        page.goto(f"{BASE}/agent-builder")
        _attendre(page, "#pf-list > *")
        _mesurer(page, "/agent-builder (profils)", echecs)
    finally:
        ctx.close()
    assert not echecs, f"contraste insuffisant ({nom}) :\n" + "\n".join(
        f"  {ou} : {e}" for ou, liste in echecs.items() for e in liste[:8])
