# [desc] Plugin pytest injecté par RunPythonTest : tout lancement Chromium headless de Playwright (fixture, harnais maison, sync ou async) devient une connexion au navigateur chaud de testd ; sinon vrai lancement sans proxy (coquille headless livrée, Edge à défaut), tué à sa fermeture [/desc]
"""Chargé par `-p _bz_pw_patch` (copié dans un dossier temporaire par RunPythonTest, ou pris dans
le dossier des plugins de testd). Autonome : il tourne dans le venv du PROJET testé.

Navigateur chaud, dans l'ordre :
- `BZ_PW_WS` (playwright launch-server) ou `BZ_PW_CDP` : donné par testd au sous-run ;
- `BZ_PW_DEMANDE` (+ `BZ_PW_JETON`) : URL du démon qui DÉMARRE le navigateur chaud à la première
  demande et rend son ws. Session B4 (2026-10-14) : les tests d'exercices de demoapp_clone lançaient
  Chromium dans un harnais maison, invisibles à la séparation : sans ws, chacun démarrait (et
  fermait, 8 à 90 s) son propre navigateur. Le patch ne dépend plus du classement.
Échec de connexion = vrai lancement (`_bz_pw_lancement` : coquille headless de Playwright, Edge
système si elle manque ; tué à sa fermeture), dit sur stderr et dans `BZ_PW_NOTES`. Chaque test servi par
le navigateur chaud est inscrit dans `BZ_PW_CONNECTS` : testd classe son fichier « navigateur »
pour les jobs suivants (créneaux, contextes, `-n`).

Non couverts (le dire, pas les deviner) : `launch_persistent_context` (profil sur disque, pas
partageable), Firefox/WebKit, un navigateur demandé visible (`headless=False`), et tout
navigateur lancé par un SOUS-PROCESS du test (le patch ne vit que dans le process pytest)."""
import json
import os
import sys
import urllib.request

from _bz_pw_lancement import armer_fermeture, armer_fermeture_async, canal_par_defaut

_demande = {"ws": None}


def _bz_note(text):
    sys.__stderr__.write(text + "\n")
    if os.environ.get("BZ_PW_NOTES"):
        with open(os.environ["BZ_PW_NOTES"], "a", encoding="utf-8") as notes:
            notes.write(text + "\n")


def _noter_connexion():
    fichier, test = os.environ.get("BZ_PW_CONNECTS"), os.environ.get("PYTEST_CURRENT_TEST", "")
    if fichier and test:
        with open(fichier, "a", encoding="utf-8") as connexions:
            connexions.write(test.rsplit(" (", 1)[0] + "\n")


def _ws_du_demon(renouveler=False):
    """ws du navigateur chaud demandé au démon (une fois par process ; `renouveler` : le
    précédent ne répond plus, le démon le relance)."""
    url = os.environ.get("BZ_PW_DEMANDE")
    if not url:
        return ""
    if _demande["ws"] is None or renouveler:
        requete = urllib.request.Request(url, headers={"X-BZ-Token": os.environ.get("BZ_PW_JETON", "")})
        ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with ouvreur.open(requete, timeout=180) as reponse:
                _demande["ws"] = json.loads(reponse.read().decode("utf-8")).get("ws") or ""
        except OSError as error:
            _bz_note(f"[bz-pw] démon de tests injoignable ({type(error).__name__}) -> vrai lancement")
            _demande["ws"] = ""
    return _demande["ws"]


def _sources(browser_type, kwargs):
    """Les ws / cdp à essayer, dans l'ordre ; vide = vrai lancement."""
    if browser_type.name != "chromium":
        _bz_note(f"[bz-pw] {browser_type.name} : pas de navigateur chaud (Chromium seulement)")
        return []
    if kwargs.get("headless") is False:
        _bz_note("[bz-pw] headless=False : navigateur visible demandé, vrai lancement")
        return []
    if os.environ.get("BZ_PW_CDP"):
        return [("cdp", os.environ["BZ_PW_CDP"])]
    sources = [("ws", os.environ["BZ_PW_WS"])] if os.environ.get("BZ_PW_WS") else []
    return sources + ([("demon", None)] if os.environ.get("BZ_PW_DEMANDE") else [])


def _ws(source, valeur, deja_essayes):
    if source != "demon":
        return valeur
    ws = _ws_du_demon(renouveler=_demande["ws"] in deja_essayes)
    return ws if ws and ws not in deja_essayes else ""


def _echec(error):
    _bz_note(f"[bz-pw] warm browser unreachable ({type(error).__name__}: {str(error)[:200]}) -> real launch")


def _vraies_options(kwargs, nom):
    if nom == "chromium" and "channel" not in kwargs:
        canal = canal_par_defaut(_bz_note)
        if canal:
            kwargs["channel"] = canal
    args = list(kwargs.get("args") or [])
    if "--no-proxy-server" not in args:
        args.append("--no-proxy-server")
    kwargs["args"] = args
    return kwargs


def _bz_warm(browser_type, kwargs):
    essayes = []
    for source, valeur in _sources(browser_type, kwargs):
        cible = _ws(source, valeur, essayes)
        if not cible:
            continue
        essayes.append(cible)
        try:
            navigateur = (browser_type.connect_over_cdp(cible) if source == "cdp"
                          else browser_type.connect(cible))
        except Exception as error:  # le vrai lancement prend le relais, et c'est dit
            _echec(error)
            continue
        _noter_connexion()
        return navigateur
    return None


async def _bz_warm_async(browser_type, kwargs):
    essayes = []
    for source, valeur in _sources(browser_type, kwargs):
        cible = _ws(source, valeur, essayes)
        if not cible:
            continue
        essayes.append(cible)
        try:
            navigateur = await (browser_type.connect_over_cdp(cible) if source == "cdp"
                                else browser_type.connect(cible))
        except Exception as error:  # le vrai lancement prend le relais, et c'est dit
            _echec(error)
            continue
        _noter_connexion()
        return navigateur
    return None


def _patcher_persistant(classe):
    origine = classe.launch_persistent_context

    def persistant(self, *args, **kwargs):
        _bz_note("[bz-pw] launch_persistent_context : profil sur disque, navigateur réel "
                 "(non partageable avec le navigateur chaud)")
        return origine(self, *args, **_vraies_options(kwargs, self.name))
    classe.launch_persistent_context = persistant


try:
    from playwright.sync_api import BrowserType as _SyncBrowserType
    from playwright.async_api import BrowserType as _AsyncBrowserType
except ImportError:
    _SyncBrowserType = _AsyncBrowserType = None

if _SyncBrowserType is not None:
    _orig_launch = _SyncBrowserType.launch
    _orig_async_launch = _AsyncBrowserType.launch

    def _patched_launch(self, **kwargs):
        warm = _bz_warm(self, kwargs)
        if warm is not None:
            return warm
        navigateur = _orig_launch(self, **_vraies_options(kwargs, self.name))
        if self.name == "chromium":
            armer_fermeture(navigateur)
        return navigateur

    async def _patched_async_launch(self, **kwargs):
        warm = await _bz_warm_async(self, kwargs)
        if warm is not None:
            return warm
        navigateur = await _orig_async_launch(self, **_vraies_options(kwargs, self.name))
        if self.name == "chromium":
            await armer_fermeture_async(navigateur)
        return navigateur

    _SyncBrowserType.launch = _patched_launch
    _AsyncBrowserType.launch = _patched_async_launch
    _patcher_persistant(_SyncBrowserType)
