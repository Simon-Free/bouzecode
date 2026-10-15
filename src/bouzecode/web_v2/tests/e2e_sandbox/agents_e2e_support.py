# [desc] Gateway des E2E de la page Agents contre un bac à sable lancé à part : navigateur, page instrumentée (erreurs console, requêtes externes), lancement d'agents pilotés par le faux LLM, attentes. [/desc]
"""Fixtures et aides partagées par `test_agents_*.py`.

Les tests visent un VRAI serveur web_v2 + un FAUX LLM lancés à part :

    BZ_SANDBOX_HOME=/tmp/bz-sb-agents BZ_UI_PORT=5256 MOCK_LLM_PORT=5299 \\
        tests/sandbox/run_sandbox.sh start --fresh --seed
    BZ_E2E_URL_AGENTS=http://127.0.0.1:5256 \\
        .venv/bin/python -m pytest src/bouzecode/web_v2/tests/e2e_sandbox -k agents -m "web or not web"

Sans `BZ_E2E_URL_AGENTS` (ni `BZ_E2E_URL`), ou si le serveur ne répond pas, tout est SKIPPÉ :
jamais un faux vert. Chaque test lance SES agents (prompt unique + `[scn:<scénario>]` en 2ᵉ
ligne pour piloter le faux LLM) : aucun test ne dépend d'un autre.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

import pytest
from jeton_e2e import en_tetes

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE = (os.environ.get("BZ_E2E_URL_AGENTS") or os.environ.get("BZ_E2E_URL") or "").rstrip("/")
DEPOT = "demo-api"
TOAST_OK = "#toasts .toast[data-kind='ok']"
TOAST_ERR = "#toasts .toast[data-kind='err']"
TOAST_INFO = "#toasts .toast[data-kind='info']"


def _joignable() -> bool:
    if not BASE:
        return False
    try:
        with urllib.request.urlopen(f"{BASE}/api/version", timeout=5):
            return True
    except Exception:  # noqa: BLE001 — injoignable = skip, pas échec
        return False


SERVEUR_OK = _joignable()
MARQUES = [
    pytest.mark.web,
    pytest.mark.slow,
    pytest.mark.skipif(not SERVEUR_OK, reason="BZ_E2E_URL_AGENTS absent ou bac à sable injoignable"),
]


def uid(prefixe: str = "e2e") -> str:
    return f"{prefixe}-{uuid.uuid4().hex[:6]}"


def api(method: str, path: str, body: dict | None = None, attendu: int | None = None):
    """Appel direct au serveur (préparation / vérification), hors navigateur."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          **en_tetes(BASE, method)})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            statut, texte = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        statut, texte = e.code, e.read().decode()
    corps = json.loads(texte) if texte.strip().startswith(("{", "[")) else texte
    if attendu is not None:
        assert statut == attendu, f"{method} {path} → {statut} {texte[:300]}"
    return corps


def lancer(titre: str, scenario: str = "reply", depot: str = DEPOT, isolation: str = "worktree") -> str:
    """Lance un agent par l'API (comme la barre de lancement : titre = 1re ligne, `worktree` par
    défaut sur un dépôt git) et renvoie son ticket_id. `shared` est refusé (409
    `collision_isolation`) tant qu'un agent écrivain du seed reste au repos dans le dépôt."""
    r = api("POST", f"/api/projects/{depot}/tickets", {"title": titre[:200], "prompt": f"{titre}\n[scn:{scenario}]",
                                      "typology": "default", "isolation": isolation,
                                      "launch": True, "defer": True}, attendu=201)
    return r["ticket_id"]


def cle_agent(ticket_id: str, delai: float = 60) -> str:
    """Attend la naissance de l'agent d'un ticket et renvoie sa clé `agent/<id>`."""
    fin = time.time() + delai
    while time.time() < fin:
        r = api("GET", f"/api/sessions/launching/{ticket_id}/blocks")
        if isinstance(r, dict) and r.get("agent_key"):
            return r["agent_key"]
        tree = api("GET", "/api/agents/tree?offset=0&limit=200")
        for n in tree.get("nodes", []):
            if n.get("ticket_id") == ticket_id and str(n.get("key", "")).startswith("agent/"):
                return n["key"]
        time.sleep(0.5)
    raise AssertionError(f"l'agent du ticket {ticket_id} n'est pas né en {delai} s")


def etat_agent(key: str) -> str:
    r = api("GET", f"/api/sessions/{key}/blocks?after=100000")
    return ((r or {}).get("status") or {}).get("state", "") if isinstance(r, dict) else ""


def attendre_etat(key: str, etats: set[str], delai: float = 60) -> str:
    fin = time.time() + delai
    etat = ""
    while time.time() < fin:
        etat = etat_agent(key)
        if etat in etats:
            return etat
        time.sleep(0.5)
    raise AssertionError(f"{key} est resté en « {etat} » (attendu : {etats})")


# ---------------------------------------------------------------- navigateur


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as play:
        try:
            b = play.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium indisponible : {exc}")
        yield b
        b.close()


class Page:
    """Page instrumentée : erreurs console et requêtes hors localhost collectées.

    `autoriser(motif)` déclare une erreur console ATTENDUE (ex. un 500 simulé par page.route)."""

    def __init__(self, page):
        self.page = page
        self.erreurs: list[str] = []
        self.externes: list[str] = []
        self.requetes: list[tuple[str, str]] = []
        self._autorisees: list[re.Pattern] = [re.compile(r"favicon")]
        page.on("console", lambda m: self.erreurs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.erreurs.append(f"pageerror: {e}"))
        page.on("request", self._requete)

    def _requete(self, req):
        self.requetes.append((req.method, req.url))
        url = req.url
        if not (url.startswith(BASE) or url.startswith("data:") or url.startswith("blob:") or url.startswith("about:")):
            self.externes.append(url)

    def autoriser(self, motif: str):
        self._autorisees.append(re.compile(motif))

    def erreurs_inattendues(self) -> list[str]:
        return [e for e in self.erreurs if not any(p.search(e) for p in self._autorisees)]

    def appels(self, motif: str, methode: str | None = None) -> list[str]:
        rx = re.compile(motif)
        return [u for m, u in self.requetes if rx.search(u) and (methode is None or m == methode)]


@pytest.fixture()
def pg(browser):
    ctx = browser.new_context(viewport={"width": 1400, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    page.set_default_timeout(20000)
    p = Page(page)
    yield p
    try:
        assert p.erreurs_inattendues() == [], f"erreurs console : {p.erreurs_inattendues()}"
        assert p.externes == [], f"requêtes externes (aucun CDN autorisé) : {p.externes}"
    finally:
        ctx.close()


class Retenue:
    """Retient les requêtes qui correspondent à `motif` (sans bloquer le navigateur) jusqu'à
    `relacher()` : permet d'observer l'état « en cours » (bouton occupé, squelette, « Recherche… »)
    SANS sleep. En API synchrone, un sleep dans le gestionnaire gèlerait aussi les assertions."""

    def __init__(self, page, motif):
        self.page, self.motif, self.retenues = page, motif, []
        self.actif = True
        page.route(motif, self._garde)

    def _garde(self, route):
        if self.actif:
            self.retenues.append(route)
        else:
            route.continue_()

    def relacher(self):
        self.actif = False
        for r in self.retenues:
            r.continue_()
        self.retenues.clear()
        self.page.unroute(self.motif, self._garde)


def ouvrir(p: Page, agent: str | None = None):
    url = f"{BASE}/conversations" + (f"?agent={agent}" if agent else "")
    p.page.goto(url, wait_until="domcontentloaded")
    expect(p.page.locator("#conv-list .ag-group").first).to_be_visible(timeout=30000)


def panneau(p: Page):
    """Le panneau de l'onglet actif."""
    return p.page.locator(".ag-panel:not([hidden])")


def ouvrir_agent(p: Page, key: str):
    """Ouvre l'onglet d'un agent via le lien profond et attend son fil."""
    ouvrir(p, key.split("/", 1)[1])
    expect(panneau(p).locator(".ag-head__title")).to_be_visible()


__all__ = ["Retenue", "BASE", "DEPOT", "MARQUES", "TOAST_OK", "TOAST_ERR", "TOAST_INFO", "api", "lancer", "cle_agent",
           "attendre_etat", "etat_agent", "browser", "pg", "ouvrir", "ouvrir_agent", "panneau", "uid", "expect"]
