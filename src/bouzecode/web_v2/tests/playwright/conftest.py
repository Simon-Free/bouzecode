# [desc] Fixtures partagées des tests navigateur : un vrai serveur werkzeug + un vrai Chromium. [/desc]
"""Base commune des tests Playwright de web_v2.

Chaque fichier de ce dossier recopiait les mêmes 40 lignes (`_free_port`, fixture
`server`, fixture `browser`). Elles vivent ici une seule fois : un fichier de test
ne contient plus que ce qu'il PROUVE.

Chromium est lancé UNE fois pour toute la session, chaque test recevant une page
neuve. Ouvrir un navigateur par test coûtait ~5 s pièce et, surtout, ré-entrer dans
`sync_playwright()` plusieurs fois dans le même processus fermait le navigateur sous
les pieds du test suivant (`TargetClosedError` selon l'ordre d'exécution).

Rappel de la politique de test : un test n'atterrit dans ce dossier que si le
comportement observé est INVISIBLE au client de test Flask — CSS calculé, géométrie
en pixels, exécution réelle du JavaScript, clic/scroll d'un vrai utilisateur. Tout ce
qui se résume à « telle route répond ceci » ou « tel élément est dans le HTML rendu »
se teste avec `client.get(...)` dans le dossier parent, et tourne 100x plus vite.
"""
from __future__ import annotations

import socket
import threading

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from bouzecode.web_v2 import app as web_app  # noqa: E402

VIEWPORT = {"width": 1280, "height": 800}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def server():
    """Sert la vraie application sur un vrai socket local (routes, templates, CSS, JS)."""
    port = _free_port()
    srv = make_server("127.0.0.1", port, web_app.create_app())
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    """Chromium réel, lancé une seule fois ; SKIP propre s'il n'est pas installé."""
    with sync_playwright() as play:
        try:
            chromium = play.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 — chromium absent -> skip, pas échec
            pytest.skip(f"Chromium indisponible : {exc}")
        try:
            yield chromium
        finally:
            chromium.close()


@pytest.fixture()
def page(browser):
    """Une page 1280x800 neuve par test, refermée à la fin."""
    new_page = browser.new_page(viewport=VIEWPORT)
    try:
        yield new_page
    finally:
        new_page.close()


@pytest.fixture()
def page_with_console_errors(page):
    """Une page neuve + la liste, vivante, de ses erreurs console et pageerror."""
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return page, errors
