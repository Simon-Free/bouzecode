# [desc] Chrome headless face à une page de login : l'agent est prévenu qu'il faut une fenêtre visible, et la fenêtre + le profil persistant choisis survivent aux redémarrages paresseux et aux reprises de session. [/desc]
"""TODO §5 du 2026-09-25 : « Chrome lancé en headless alors qu'il faut une fenêtre visible ».

Les options `visible_window` / `profile` d'`EnableChromeDevtools` existaient (cf.
test_chrome_devtools_args.py), mais deux chemins les perdaient ou ne les proposaient jamais :

1. PAS D'ESCALADE. Le démarrage paresseux (premier `navigate_page` sans `EnableChromeDevtools`)
   ouvre Chrome en headless. Quand la page atteinte est une page de login (SSO, OTP, captcha),
   rien ne le signalait : l'agent demandait à l'utilisateur de « s'authentifier dans la
   fenêtre » d'un navigateur qui n'en a aucune, ou concluait à un blocage.
2. OPTIONS NON TRANSMISES au redémarrage. Les options n'étaient mémorisées que dans les
   arguments du transport EN COURS. Dès qu'il n'était plus vivant (Chrome/serveur tombé, ou
   nouveau process après une reprise de session — réveil web), le premier outil utilisé
   rallumait Chrome avec le défaut `--headless --isolated` : plus de fenêtre, et un profil
   jetable à la place du profil persistant où l'humain venait de se connecter. La session
   « ne survivait » donc pas.

Aucun vrai Chrome ni vrai `npx` : faux transport injecté (même principe que les autres modules).
"""
import os
import threading

import pytest

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.chrome_devtools import launcher
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.session.session_pick import restore_state
from bouzecode.backend.core import tool_registry

NAV_TOOL = "mcp__chrome-devtools__navigate_page"
SNAP_TOOL = "mcp__chrome-devtools__take_snapshot"

# Sorties au format de chrome-devtools-mcp (liste des pages après une navigation, snapshot a11y).
PAGE_SSO = (
    "Successfully navigated to https://intranet.exemple.fr/wiki.\n"
    "## Pages\n"
    "0: https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=x [selected]"
)
#  Forme RÉELLE de chrome-devtools-mcp pour une page qui a un titre (relevée le 2026-09-26 avec
#  un Chrome headless sur la vraie page de login Microsoft) : titre, PUIS l'URL entre parenthèses.
PAGE_SSO_AVEC_TITRE = (
    "Successfully navigated to https://login.microsoftonline.com/common/oauth2/v2.0/"
    "authorize?client_id=x.\n"
    "## Pages\n"
    "1: Connectez-vous à votre compte (https://login.microsoftonline.com/common/oauth2/v2.0/"
    "authorize?client_id=x) [selected]"
)
PAGE_ORDINAIRE_AVEC_TITRE = (
    "Successfully navigated to https://docs.exemple.fr/guide.\n"
    "## Pages\n"
    "1: Guide (connexion SSO expliquée) (https://docs.exemple.fr/guide) [selected]"
)
PAGE_ORDINAIRE = (
    "Successfully navigated to https://docs.exemple.fr/guide.\n"
    "## Pages\n"
    "0: https://docs.exemple.fr/guide [selected]"
)
SNAPSHOT_OTP = (
    'uid=1_0 RootWebArea "Vérification" url="https://portail.exemple.fr/mfa"\n'
    '  uid=1_1 heading "Double authentification"\n'
    '  uid=1_2 textbox "Code de vérification"\n'
    '  uid=1_3 button "Valider"'
)
SNAPSHOT_CAPTCHA = (
    'uid=1_0 RootWebArea "Un instant" url="https://boutique.exemple.fr/"\n'
    '  uid=1_1 Iframe "reCAPTCHA"\n'
)
#  Un lien « Se connecter » sur une page ordinaire n'est PAS une page de login.
SNAPSHOT_LIEN_LOGIN = (
    'uid=1_0 RootWebArea "Accueil" url="https://docs.exemple.fr/"\n'
    '  uid=1_1 link "Se connecter" url="https://docs.exemple.fr/login"\n'
)
#  Un article qui PARLE de SSO n'est pas une page de SSO.
PAGE_ARTICLE_SSO = "## Pages\n0: https://docs.exemple.fr/blog/sso-explique [selected]"
#  L'application locale que l'agent teste : il a ses identifiants de test, pas d'humain requis.
SNAPSHOT_LOGIN_LOCAL = (
    'uid=1_0 RootWebArea "Connexion" url="http://127.0.0.1:5000/login"\n'
    '  uid=1_1 textbox "Mot de passe"\n'
)


class FauxTransport:
    """Mémorise sa ligne de commande ; `tools/call` rend le texte de `PAGE`."""

    CREES = []
    PAGE = PAGE_ORDINAIRE

    def __init__(self, config):
        self.config = config
        self.arrete = False
        FauxTransport.CREES.append(self)

    def start(self):
        pass

    def request(self, method, params=None, timeout=None):
        if method == "tools/list":
            return {"tools": [{"name": "navigate_page", "description": "va a une URL"},
                              {"name": "take_snapshot", "description": "arbre a11y"}]}
        if method == "tools/call":
            return {"content": [{"type": "text", "text": FauxTransport.PAGE}]}
        return {}

    def notify(self, method, params=None):
        pass

    def stop(self):
        self.arrete = True

    @property
    def alive(self):
        return not self.arrete


def _purge_registry():
    for name in (NAV_TOOL, SNAP_TOOL, "EnableChromeDevtools", "DisableChromeDevtools"):
        for action in (tool_registry.unregister_tool, tool_registry.enable_tool,
                       tool_registry.unregister_tool):
            try:
                action(name)
            except Exception:  # noqa: BLE001 — déjà retiré
                pass


@pytest.fixture(autouse=True)
def _isolation(tmp_path, monkeypatch):
    """Faux transport, manifeste et profils dans tmp_path : jamais le HOME de l'utilisateur."""
    launcher.shutdown_all()
    _purge_registry()
    os.environ.pop("BOUZECODE_ENABLE_CHROME_DEVTOOLS", None)
    FauxTransport.CREES, FauxTransport.PAGE = [], PAGE_ORDINAIRE
    monkeypatch.setattr(launcher, "StdioTransport", FauxTransport)
    monkeypatch.setattr(launcher, "_manifest_path", lambda: tmp_path / "manifeste.json")
    monkeypatch.setattr(launcher, "_racine_des_profils", lambda: tmp_path / "profils")
    monkeypatch.setattr(launcher, "chrome_installe", lambda: True)
    monkeypatch.setattr(launcher, "_manque_pour_demarrer", lambda command: None)
    yield
    launcher.shutdown_all()
    _purge_registry()
    os.environ.pop("BOUZECODE_ENABLE_CHROME_DEVTOOLS", None)


def _appeler(nom_court: str, params=None) -> str:
    return tool_registry.get_tool(f"mcp__chrome-devtools__{nom_court}").func(params or {}, {})


def _args_du_dernier_lancement():
    assert FauxTransport.CREES, "aucun transport n'a été lancé"
    return list(FauxTransport.CREES[-1].config.args)


def _mourir():
    """Le serveur MCP / Chrome tombe (crash, fenêtre fermée qui emporte le serveur…)."""
    FauxTransport.CREES[-1].arrete = True


# ── 1. Escalade : une page de login dans un Chrome headless est signalée ──────

@pytest.mark.parametrize("page", [PAGE_SSO, PAGE_SSO_AVEC_TITRE], ids=["sans-titre", "avec-titre"])
def test_page_sso_en_headless_dit_de_relancer_avec_une_fenetre_visible(page):
    """LE bug : l'agent navigue (Chrome headless), tombe sur le SSO, et rien ne lui dit qu'il
    n'existe aucune fenêtre où l'utilisateur pourrait se connecter. `avec-titre` est la forme
    que rend vraiment chrome-devtools-mcp pour une page de SSO : sans elle, `navigate_page` ne
    signalait rien (seul un `take_snapshot` ultérieur le faisait)."""
    launcher.enable_chrome_devtools()
    FauxTransport.PAGE = page

    resultat = _appeler("navigate_page", {"url": "https://intranet.exemple.fr/wiki"})

    assert page in resultat, "le résultat du serveur est rendu intact"
    assert "EnableChromeDevtools" in resultat and "visible_window" in resultat, resultat
    assert "profile" in resultat, "le profil persistant doit être proposé (la session survit)"
    assert "login.microsoftonline.com" in resultat


@pytest.mark.parametrize("page", [SNAPSHOT_OTP, SNAPSHOT_CAPTCHA], ids=["otp", "captcha"])
def test_otp_et_captcha_en_headless_sont_signales(page):
    launcher.enable_chrome_devtools()
    FauxTransport.PAGE = page

    resultat = _appeler("take_snapshot")

    assert "visible_window" in resultat, resultat


def test_le_demarrage_paresseux_signale_aussi_la_page_de_login():
    """Chemin le plus fréquent : aucun `EnableChromeDevtools`, le premier outil allume Chrome."""
    launcher.enable_chrome_devtools()           # déclare les outils (manifeste)
    launcher.shutdown_chrome_devtools()         # puis plus aucun Chrome vivant
    FauxTransport.PAGE = PAGE_SSO
    os.environ["BOUZECODE_ENABLE_CHROME_DEVTOOLS"] = "1"
    launcher.declarer_depuis_le_manifeste()

    resultat = _appeler("navigate_page", {"url": "https://intranet.exemple.fr/wiki"})

    assert "--headless" in _args_du_dernier_lancement()
    assert "visible_window" in resultat, resultat


@pytest.mark.parametrize("page", [PAGE_ORDINAIRE, PAGE_ORDINAIRE_AVEC_TITRE, SNAPSHOT_LIEN_LOGIN,
                                  PAGE_ARTICLE_SSO, SNAPSHOT_LOGIN_LOCAL],
                         ids=["ordinaire", "ordinaire-avec-titre", "simple-lien-login",
                              "article-sso", "appli-locale"])
def test_pas_d_alerte_sans_page_de_login_distante(page):
    """Contrôles négatifs : pas de bruit (des tokens à chaque appel) sur une page ordinaire, un
    simple lien « Se connecter », ni sur l'application locale que l'agent teste lui-même."""
    launcher.enable_chrome_devtools()
    FauxTransport.PAGE = page

    assert _appeler("take_snapshot") == page


def test_pas_d_alerte_quand_la_fenetre_est_deja_visible():
    launcher.enable_chrome_devtools(visible_window=True, profile="sso")
    FauxTransport.PAGE = PAGE_SSO

    assert _appeler("navigate_page", {"url": "https://intranet.exemple.fr/wiki"}) == PAGE_SSO


def test_l_alerte_n_est_donnee_qu_une_fois_par_site():
    launcher.enable_chrome_devtools()
    FauxTransport.PAGE = PAGE_SSO

    premier = _appeler("navigate_page", {"url": "https://intranet.exemple.fr/wiki"})
    second = _appeler("take_snapshot")

    assert "visible_window" in premier
    assert second == PAGE_SSO


def test_suivre_l_alerte_ouvre_une_fenetre_avec_un_profil_persistant():
    """Le chemin complet : l'appel proposé relance Chrome AVEC fenêtre et profil persistant."""
    launcher.enable_chrome_devtools()
    FauxTransport.PAGE = PAGE_SSO
    _appeler("navigate_page", {"url": "https://intranet.exemple.fr/wiki"})

    launcher._enable_tool_func({"visible_window": True,
                                "profile": launcher.profil_suggere("login.microsoftonline.com")},
                               {})

    args = _args_du_dernier_lancement()
    assert "--headless" not in args and "--userDataDir" in args


# ── 2. Options transmises aux redémarrages : la fenêtre et le profil survivent ─

def test_un_redemarrage_paresseux_garde_la_fenetre_visible_et_le_profil():
    """Chrome tombe après que l'humain s'est connecté : le prochain outil le rallume. Avant, avec
    le défaut headless + profil jetable — fenêtre disparue, session perdue."""
    launcher.enable_chrome_devtools(visible_window=True, profile="confluence-otp")
    _mourir()

    _appeler("navigate_page", {"url": "https://confluence.exemple.fr"})

    assert len(FauxTransport.CREES) == 2, "le premier outil rallume Chrome"
    args = _args_du_dernier_lancement()
    assert "--headless" not in args, f"la fenêtre visible demandée a été perdue : {args}"
    assert "confluence-otp" in args[args.index("--userDataDir") + 1], args


def test_une_session_reprise_rallume_chrome_avec_la_meme_fenetre_et_le_meme_profil():
    """Réveil web = nouveau process. La reprise redéclarait les outils, mais le premier
    `navigate_page` repartait en headless sur un profil jetable : il fallait se reconnecter
    dans une fenêtre… qui n'existait pas."""
    launcher.enable_chrome_devtools(visible_window=True, profile="confluence-otp")
    session = _build_session_data(AgentState(), session_id="s1", model="m")
    launcher.shutdown_all()                     # fin du premier process (atexit)

    restore_state(AgentState(), session)        # nouveau process : reprise
    _appeler("navigate_page", {"url": "https://confluence.exemple.fr"})

    args = _args_du_dernier_lancement()
    assert "--headless" not in args, args
    assert "confluence-otp" in args[args.index("--userDataDir") + 1], args


def test_une_session_sans_option_repart_sur_le_defaut():
    """Non-régression : la reprise d'une session headless ne fait surgir aucune fenêtre."""
    launcher.enable_chrome_devtools()
    session = _build_session_data(AgentState(), session_id="s1", model="m")
    launcher.shutdown_all()

    restore_state(AgentState(), session)
    _appeler("navigate_page", {"url": "https://docs.exemple.fr"})

    assert _args_du_dernier_lancement() == launcher.build_server_args()


def test_disable_oublie_les_options():
    """`DisableChromeDevtools` est une demande explicite : le Chrome suivant repart du défaut."""
    launcher.enable_chrome_devtools(visible_window=True, profile="otp")
    launcher.shutdown_chrome_devtools()

    launcher.enable_chrome_devtools()
    _appeler("navigate_page", {"url": "https://docs.exemple.fr"})

    assert "--headless" in _args_du_dernier_lancement()


def test_les_options_restent_propres_a_chaque_agent():
    """Un sous-agent (autre thread) ne récupère pas la fenêtre ni le profil de son parent :
    deux Chrome sur le même user-data-dir se bloqueraient."""
    launcher.enable_chrome_devtools(visible_window=True, profile="otp")
    args_enfant = []

    def _enfant():
        _appeler("navigate_page", {"url": "https://docs.exemple.fr"})
        args_enfant.extend(_args_du_dernier_lancement())

    fil = threading.Thread(target=_enfant)
    fil.start()
    fil.join()

    assert "--headless" in args_enfant and "--isolated" in args_enfant, args_enfant


def test_la_description_de_l_outil_dit_que_la_fenetre_et_le_profil_sont_gardes():
    launcher.register_bootstrap_tools()
    description = tool_registry.get_tool("EnableChromeDevtools").schema["description"].lower()

    assert "login" in description
    assert "remember" in description or "kept" in description, description
