# [desc] Gateway des E2E du Bureau contre un bac à sable lancé à part : navigateur, page instrumentée (erreurs console, requêtes externes), appels API de préparation, attentes. [/desc]
"""Fixtures et aides partagées par `test_bureau_*.py`.

Les tests visent un VRAI serveur web_v2 + un FAUX LLM lancés à part par
`tests/sandbox/run_sandbox.sh` ; ils ne démarrent rien eux-mêmes :

    BZ_SANDBOX_HOME=/tmp/bz-sb-bureau BZ_UI_PORT=5156 MOCK_LLM_PORT=5199 \\
        tests/sandbox/run_sandbox.sh start --fresh --seed
    BZ_E2E_URL_BUREAU=http://127.0.0.1:5156 \\
        .venv/bin/python -m pytest src/bouzecode/web_v2/tests/e2e_sandbox -k bureau -m "web or not web"

Sans `BZ_E2E_URL_BUREAU` (ou si le serveur ne répond pas), tout est SKIPPÉ — jamais un faux
vert. Chaque test crée ses propres chantiers / tâches sous un nom unique : aucun test ne
dépend d'un autre ni des données du seed (sauf les dépôts `demo-*`).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

import pytest
from jeton_e2e import en_tetes

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE = (os.environ.get("BZ_E2E_URL_BUREAU") or "").rstrip("/")

TOAST_OK = "#toasts .toast[data-kind='ok']"
TOAST_ERR = "#toasts .toast[data-kind='err']"
TOAST_INFO = "#toasts .toast[data-kind='info']"
DEPOT = "demo-api"


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
    pytest.mark.skipif(not SERVEUR_OK, reason="BZ_E2E_URL_BUREAU absent ou serveur de bac à sable injoignable"),
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
        with urllib.request.urlopen(req, timeout=60) as r:
            statut, texte = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        statut, texte = e.code, e.read().decode()
    corps = json.loads(texte) if texte.strip().startswith(("{", "[")) else texte
    if attendu is not None:
        assert statut == attendu, f"{method} {path} → {statut} {texte[:300]}"
    return corps


def creer_chantier(titre: str | None = None, projets=(DEPOT,)) -> dict:
    titre = titre or uid("Chantier")
    r = api("POST", "/api/macros", {"titre": titre, "projets": list(projets)}, attendu=201)
    return r["macro"]


def creer_tache(titre: str | None = None, corps: str = "", macro_id: str = "", projet_slug: str = "") -> dict:
    titre = titre or uid("Tâche")
    r = api("POST", "/api/micros", {"titre": titre, "corps": corps, "macro_id": macro_id,
                                    "projet_slug": projet_slug}, attendu=201)
    return r["micro"]


def ligne(micro_id: str) -> dict | None:
    #  La liste est ALLÉGÉE (1 passage, ni récap, ni classements) : `detail=` sert cette
    #  ligne COMPLÈTE, comme pour une tâche dépliée à l'écran.
    d = api("GET", f"/api/lignes?detail={micro_id}")
    for c in d.get("chantiers") or []:
        for t in c.get("lignes") or []:
            if t["id"] == micro_id:
                return t
    for t in d.get("non_rattachees") or []:
        if t["id"] == micro_id:
            return t
    return None


def attendre(pred, delai: float = 60.0, pas: float = 0.5, message: str = ""):
    fin = time.time() + delai
    dernier = None
    while time.time() < fin:
        dernier = pred()
        if dernier:
            return dernier
        time.sleep(pas)
    raise AssertionError(f"délai dépassé ({delai} s) : {message} — dernier={dernier!r}")


def _resume_ligne(t: dict | None) -> str:
    """Ce qu'on a vu de la tâche la dernière fois : sans ça, « dernier=None » ne distinguait pas
    une tâche ABSENTE de /api/lignes d'une tâche présente dans un autre statut."""
    if t is None:
        return "absente de /api/lignes"
    passages = [(p.get("etat"), p.get("agent_id")) for p in (t.get("passages") or [])[:2]]
    return f"statut_ui={t.get('statut_ui')!r} statut={t.get('statut')!r} passages={passages}"


def attendre_statut(micro_id: str, statuts, delai: float = 90.0) -> dict:
    statuts = {statuts} if isinstance(statuts, str) else set(statuts)
    vu: list = [None]

    def atteint():
        vu[0] = ligne(micro_id)
        return vu[0] if vu[0] and vu[0].get("statut_ui") in statuts else None
    try:
        return attendre(atteint, delai, 1.0, f"tâche {micro_id} → {statuts}")
    except AssertionError as exc:
        raise AssertionError(f"{exc} ; dernière observation : {_resume_ligne(vu[0])}") from None


# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def bz_browser():
    with sync_playwright() as play:
        try:
            chromium = play.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 — chromium absent → skip
            pytest.skip(f"Chromium indisponible : {exc}")
        yield chromium
        chromium.close()


@pytest.fixture()
def bz_page(bz_browser):
    """Page neuve (contexte isolé : localStorage vierge) + journal d'erreurs console et de
    requêtes externes. À la fin du test : ZÉRO erreur console et ZÉRO requête externe (U16),
    sauf erreurs déclarées attendues dans `page.erreurs_attendues` (motifs)."""
    ctx = bz_browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.erreurs = []
    pg.externes = []
    pg.erreurs_attendues = []
    pg.on("console", lambda m: m.type == "error" and pg.erreurs.append(m.text))
    pg.on("pageerror", lambda e: pg.erreurs.append(f"pageerror: {e}"))

    def _req(r):
        if not r.url.startswith(BASE) and not r.url.startswith(("data:", "blob:")):
            pg.externes.append(r.url)
    pg.on("request", _req)
    yield pg
    inattendues = [e for e in pg.erreurs if not any(m in e for m in pg.erreurs_attendues)]
    ctx.close()
    assert not pg.externes, f"requêtes hors du serveur local : {pg.externes}"
    assert not inattendues, f"erreurs console : {inattendues}"


def choisir_mode(page, mode: str):
    """Bascule « Trier par : Statut | Chantier » et attend que le bouton soit marqué."""
    bouton = page.locator(f"#bz-mode [data-mode='{mode}']")
    if bouton.get_attribute("aria-pressed") != "true":
        bouton.click()
    expect(bouton).to_have_attribute("aria-pressed", "true")


def ouvrir_archives(page):
    """Mode Statut : déplie la section « Archivées » si elle est repliée."""
    bascule = page.locator(".bz-sec[data-sec='archivees'] .bz-sec__bascule")
    if bascule.get_attribute("aria-expanded") != "true":
        bascule.click()
    expect(bascule).to_have_attribute("aria-expanded", "true")


def ouvrir_bureau(page, vue: str | None = None):
    """Ouvre /bureau et attend la fin du chargement. `vue` : « statut » (défaut), « chantier »,
    ou « archivees » (Statut + section Archivées dépliée)."""
    page.goto(f"{BASE}/bureau")
    expect(page.locator("#bz-mode .seg__btn")).to_have_count(2, timeout=20000)
    expect(page.locator("#lignes-liste")).not_to_have_attribute("aria-busy", "true", timeout=20000)
    expect(page.locator("#lignes-liste .skeleton")).to_have_count(0, timeout=20000)
    choisir_mode(page, "chantier" if vue == "chantier" else "statut")
    if vue == "archivees":
        ouvrir_archives(page)
    return page


def tache_loc(page, micro_id: str):
    return page.locator(f".bz-task[data-id='{micro_id}']")


def section_loc(page, macro_id: str):
    return page.locator(f".bz-ch[data-chantier='{macro_id}']")


def simuler_erreur(page, motif: str, statut: int = 500, methode: str | None = None, corps: dict | None = None,
                   une_fois: bool = True):
    """Fait échouer (une fois par défaut) les requêtes du navigateur correspondant au motif."""
    etat = {"n": 0}

    def handler(route):
        if methode and route.request.method != methode:
            route.fallback()
            return
        if une_fois and etat["n"] >= 1:
            route.fallback()
            return
        etat["n"] += 1
        if statut == 0:
            route.abort("connectionrefused")
        else:
            route.fulfill(status=statut, content_type="application/json",
                          body=json.dumps(corps or {"error": f"erreur simulée ({statut})", "code": "simule"}))
    page.route(motif, handler)
    # La page journalise « Failed to load resource » pour la réponse simulée : c'est attendu.
    page.erreurs_attendues.append("Failed to load resource")
    page.erreurs_attendues.append("ERR_CONNECTION_REFUSED")
    return etat


def attendre_busy(bouton):
    """Signal immédiat (R1) : le bouton passe occupé et désactivé."""
    expect(bouton).to_have_attribute("aria-busy", "true", timeout=2000)


class Retenue:
    """Retient les requêtes correspondant au motif (elles restent « en vol ») jusqu'à `relacher()`.
    Sert à OBSERVER l'état occupé (R1/R2) sans dépendre de la vitesse du serveur local."""

    def __init__(self, page, motif: str, methode: str | None = None):
        self.page, self.motif, self.methode = page, motif, methode
        self.routes = []
        page.route(motif, self._handler)

    def _handler(self, route):
        if self.methode and route.request.method != self.methode:
            route.fallback()
            return
        self.routes.append(route)

    def attendre(self, n: int = 1, delai_ms: int = 5000):
        fin = time.time() + delai_ms / 1000
        while len(self.routes) < n and time.time() < fin:
            self.page.wait_for_timeout(50)
        assert len(self.routes) >= n, f"aucune requête {self.methode or ''} {self.motif} partie"

    def relacher(self):
        self.page.unroute(self.motif, self._handler)
        for r in self.routes:
            r.fallback()
        self.routes = []


def deplier(page, micro_id: str):
    """Déplie la tâche si elle ne l'est pas déjà (un clic sur un titre déplié la replierait)."""
    titre = tache_loc(page, micro_id).locator(".bz-task__titre")
    expect(titre).to_be_visible(timeout=20000)
    if titre.get_attribute("aria-expanded") != "true":
        titre.click()
    expect(titre).to_have_attribute("aria-expanded", "true")
    return tache_loc(page, micro_id)


def point_hors_tache(page, type_: str, texte: str, timeout: int = 90000):
    """Ligne d'un point HORS tâche (conversation libre, lancement hors tâche) qui attend un geste ;
    elle arrive par le rafraîchissement automatique. Sa bande d'action (question, gestes) est
    visible sans rien déplier."""
    point = page.locator(f".bz-point[data-type='{type_}']").filter(has_text=texte)
    expect(point).to_have_count(1, timeout=timeout)
    expect(point.locator(".bz-task__attente")).to_be_visible()
    return point


def bande(page, micro_id: str):
    """La bande « ce qui t'attend » d'une tâche : l'action attendue, sans déplier."""
    return tache_loc(page, micro_id).locator(".bz-task__attente")


def section_statut(page, cle: str):
    """Section du mode Statut : a_moi (À traiter), en_cours, a_lancer, archivees."""
    return page.locator(f".bz-sec[data-sec='{cle}']")


def groupe_a_traiter(page, cat: str):
    """Groupe de « À traiter » : decider, debloquer, reprendre, verifier."""
    return page.locator(f".bz-sec[data-sec='a_moi'] .bz-cat[data-cat='{cat}']")
