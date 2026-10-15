# [desc] Plugin pytest injecté par testd : délai par défaut de 5 s (au lieu de 30 s) des actions Playwright (`click`, `fill`, attente d'un élément, navigation) sur tout contexte ou page créé dans le process du test ; un `set_default_timeout` du test reste maître [/desc]
"""Chargé par `-p _bz_pw_delai` (même dossier que `_bz_testd_plugin`). Autonome : il tourne dans
le venv du PROJET testé, et ne fait rien sans Playwright.

Mesuré le 2026-10-14 : un parcours navigateur chaud prend ~1 s, une action ~0,05 s. Le délai par
défaut de Playwright (30 s par action) faisait attendre 30 s un élément absent avant l'échec —
et, multiplié par les relances `flaky`, des minutes pour un seul vrai échec.

Le délai est posé à la CRÉATION (`Browser.new_context`, `Browser.new_page`), sync comme async :
un `set_default_timeout` (ou `set_default_navigation_timeout`) appelé ensuite par le test ou sa
fixture le remplace, comme d'ordinaire. `BrowserContext.new_page` n'est pas touché : la page
hérite du délai de son contexte, celui que le test a pu y fixer. `BZ_PW_DELAI_MS` le change
(0 : délai de Playwright). Non couvert : `launch_persistent_context`, et les navigateurs lancés
par un sous-process du test."""
import os

DELAI_MS = 5000


def _delai_ms() -> int:
    brut = os.environ.get("BZ_PW_DELAI_MS")
    return DELAI_MS if not brut else int(brut)


def _avec_delai(objet):
    delai = _delai_ms()
    if delai > 0:
        objet.set_default_timeout(delai)
    return objet


def _patcher_sync(classe) -> None:
    contexte, page = classe.new_context, classe.new_page

    def new_context(self, *args, **kwargs):
        return _avec_delai(contexte(self, *args, **kwargs))

    def new_page(self, *args, **kwargs):
        return _avec_delai(page(self, *args, **kwargs))
    classe.new_context, classe.new_page = new_context, new_page


def _patcher_async(classe) -> None:
    contexte, page = classe.new_context, classe.new_page

    async def new_context(self, *args, **kwargs):
        return _avec_delai(await contexte(self, *args, **kwargs))

    async def new_page(self, *args, **kwargs):
        return _avec_delai(await page(self, *args, **kwargs))
    classe.new_context, classe.new_page = new_context, new_page


try:
    from playwright.sync_api import Browser as _SyncBrowser
    from playwright.async_api import Browser as _AsyncBrowser
except ImportError:
    _SyncBrowser = _AsyncBrowser = None

if _SyncBrowser is not None:
    _patcher_sync(_SyncBrowser)
    _patcher_async(_AsyncBrowser)
