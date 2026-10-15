"""Arguments de lancement de chrome-devtools-mcp : defaut headless, fenetre visible, profil persistant.

PROBLEME VECU EN PRODUCTION (2026-08-25). Un agent devait capturer un Confluence protege par un
code OTP : seul un humain peut le saisir. L'agent a ouvert Chrome, vu la page de login, et demande
a l'utilisateur d'aller s'authentifier "dans sa fenetre". Il n'y avait AUCUNE fenetre : les
arguments etaient codes en dur en `--headless --isolated`, et l'outil `EnableChromeDevtools`
exposait un `input_schema` VIDE. Aucune authentification interactive (OTP, SSO, captcha) n'etait
donc realisable sur la plateforme.

Ce que ces tests verrouillent :
- le DEFAUT ne bouge pas d'un octet (`--headless --isolated`) : 15 agents en parallele ne doivent
  pas faire surgir 15 fenetres ;
- une fenetre visible est obtenue en NE passant PAS `--headless` (l'option est un booleen dont le
  defaut cote chrome-devtools-mcp est false) ;
- un profil persistant passe par `--userDataDir <chemin>` (option constatee via
  `npx chrome-devtools-mcp@latest --help`) et retire `--isolated`, sinon la session ouverte a la
  main par l'humain mourrait avec le profil jetable ;
- deux profils NOMMES differemment n'ont jamais le meme repertoire (c'etait la raison d'etre de
  `--isolated`) ;
- et surtout le piege : l'activation est memorisee PAR THREAD et l'outil est annonce idempotent.
  Un agent qui a deja allume Chrome en headless AVANT de decouvrir la page de login doit obtenir
  une vraie fenetre : le transport en cours doit etre ARRETE puis RELANCE.

Aucun vrai Chrome ni vrai `npx` ici : `launcher.StdioTransport` est remplace par un faux transport
qui memorise la ligne de commande demandee (points d'injection existants, pas de unittest.mock).
"""
import json
import os
import threading

import pytest

from bouzecode.backend.chrome_devtools import launcher
from bouzecode.backend.core import tool_registry

NAV_TOOL = "mcp__chrome-devtools__navigate"
BOOTSTRAP = ("EnableChromeDevtools", "DisableChromeDevtools")
DEFAUT = [launcher.MCP_PACKAGE, "--headless", "--isolated"]


class FauxTransport:
    """Enregistre la ServerConfig recue au lieu de lancer un sous-processus."""

    CREES = []

    def __init__(self, config):
        self.config = config
        self.arrete = False
        FauxTransport.CREES.append(self)

    def start(self):
        pass

    def request(self, method, params=None, timeout=None):
        if method == "tools/list":
            return {"tools": [{"name": "navigate", "description": "va a une URL"}]}
        return {}

    def notify(self, method, params=None):
        pass

    def stop(self):
        self.arrete = True

    @property
    def alive(self):
        return not self.arrete


def _purge_registry():
    for name in (NAV_TOOL, *BOOTSTRAP):
        for action in (tool_registry.unregister_tool, tool_registry.enable_tool,
                       tool_registry.unregister_tool):
            try:
                action(name)
            except Exception:
                pass


@pytest.fixture(autouse=True)
def _manifeste_isole(tmp_path, monkeypatch):
    """Le manifeste de ces tests ne doit JAMAIS toucher `~/.bouzecode/` (cf. l'autre module)."""
    monkeypatch.setattr(launcher, "_manifest_path",
                        lambda: tmp_path / "chrome_devtools_manifest.json")
    yield


@pytest.fixture(autouse=True)
def _faux_transport(monkeypatch):
    launcher.shutdown_all()
    _purge_registry()
    os.environ.pop("BOUZECODE_ENABLE_CHROME_DEVTOOLS", None)
    FauxTransport.CREES = []
    monkeypatch.setattr(launcher, "StdioTransport", FauxTransport)
    #  Cas historique de ces tests : Chrome est installé et npx disponible. Les autres cas
    #  (Chromium de secours, rien d'installé) vivent dans test_chrome_devtools_navigateur.py.
    monkeypatch.setattr(launcher, "chrome_installe", lambda: True)
    monkeypatch.setattr(launcher, "_manque_pour_demarrer", lambda command: None)
    yield
    launcher.shutdown_all()
    _purge_registry()
    os.environ.pop("BOUZECODE_ENABLE_CHROME_DEVTOOLS", None)


def _args_du_dernier_lancement():
    assert FauxTransport.CREES, "aucun transport n'a ete lance"
    return list(FauxTransport.CREES[-1].config.args)


# ── Le defaut : non-regression, c'est le test le plus important ────────────────

def test_sans_parametre_les_arguments_restent_exactement_headless_isolated():
    """Un ticket existant ne doit voir AUCUNE difference : octet pour octet le meme lancement."""
    launcher.enable_chrome_devtools()

    assert _args_du_dernier_lancement() == DEFAUT
    assert FauxTransport.CREES[-1].config.command == "npx"


def test_le_demarrage_paresseux_d_un_outil_reste_headless():
    """`_make_tool_func` rallume Chrome tout seul au premier usage : ce chemin garde le defaut."""
    assert launcher.build_server_args() == DEFAUT


# ── Fenetre visible (action humaine requise) ───────────────────────────────────

def test_fenetre_visible_ne_passe_plus_headless():
    """LE test qui echoue sur le code d'avant : on demande une fenetre, `--headless` sautait quand
    meme dans la ligne de commande, donc l'humain n'avait rien a l'ecran pour saisir son OTP."""
    launcher.enable_chrome_devtools(visible_window=True)

    args = _args_du_dernier_lancement()
    assert "--headless" not in args, f"une fenetre visible ne peut pas etre headless : {args}"
    assert args[0] == launcher.MCP_PACKAGE
    assert "--isolated" in args, "sans profil nomme, on reste sur un profil jetable"


# ── Profil persistant nomme ───────────────────────────────────────────────────

def test_profil_persistant_passe_userDataDir_et_retire_isolated():
    """`--userDataDir` est l'option constatee (`npx chrome-devtools-mcp@latest --help`) ;
    `--isolated` (profil jetable nettoye a la fermeture) doit disparaitre, sinon la session
    ouverte a la main mourrait au premier redemarrage du navigateur."""
    launcher.enable_chrome_devtools(profile="confluence-otp")

    args = _args_du_dernier_lancement()
    assert "--isolated" not in args, f"un profil persistant exclut --isolated : {args}"
    assert "--userDataDir" in args, f"option de profil persistant absente : {args}"
    chemin = args[args.index("--userDataDir") + 1]
    assert "confluence-otp" in chemin, chemin


def test_deux_profils_nommes_ne_partagent_jamais_le_meme_repertoire():
    """Un profil nomme reintroduit le risque que `--isolated` evitait : deux agents paralleles
    qui se partagent un user-data-dir se bloquent mutuellement."""
    a = launcher.build_server_args(profile="agent-a")
    b = launcher.build_server_args(profile="agent-b")

    assert a[a.index("--userDataDir") + 1] != b[b.index("--userDataDir") + 1]


def test_fenetre_visible_et_profil_persistant_ensemble():
    """Le cas reel de l'OTP : l'humain saisit son code dans une fenetre, et sa session survit."""
    args = launcher.build_server_args(visible_window=True, profile="otp")

    assert "--headless" not in args
    assert "--isolated" not in args
    assert "--userDataDir" in args


# ── Le piege : reactivation avec des arguments differents ──────────────────────

def test_reactivation_avec_des_arguments_differents_relance_le_transport():
    """LE scenario vecu : l'agent avait DEJA allume Chrome (headless) avant de tomber sur la page
    de login. Repondre "deja actif" reproduirait le bug a l'identique."""
    launcher.enable_chrome_devtools()
    premier = FauxTransport.CREES[-1]

    msg = launcher.enable_chrome_devtools(visible_window=True, profile="otp")

    assert premier.arrete is True, "l'ancien transport headless doit etre arrete"
    assert len(FauxTransport.CREES) == 2, "un nouveau transport doit etre demarre"
    assert launcher._TRANSPORTS[threading.get_ident()] is FauxTransport.CREES[-1]
    assert "--headless" not in _args_du_dernier_lancement()
    assert "already active" not in msg.lower(), msg


def test_reactivation_avec_les_memes_arguments_reste_idempotente():
    """L'idempotence par agent est conservee quand rien ne change : pas de Chrome relance pour rien."""
    launcher.enable_chrome_devtools()
    msg = launcher.enable_chrome_devtools()

    assert "already active" in msg
    assert len(FauxTransport.CREES) == 1
    assert FauxTransport.CREES[0].arrete is False


# ── L'outil expose reellement ces options a l'agent ───────────────────────────

def test_le_schema_de_l_outil_expose_les_options_et_dit_quand_s_en_servir():
    launcher.register_bootstrap_tools()

    outil = tool_registry.get_tool("EnableChromeDevtools")
    props = outil.schema["input_schema"]["properties"]
    assert "visible_window" in props, "l'agent ne peut pas demander une fenetre visible"
    assert "profile" in props, "l'agent ne peut pas demander un profil persistant"

    texte = json.dumps(outil.schema).lower()
    for indice in ("otp", "sso", "captcha"):
        assert indice in texte, f"le schema doit dire QUAND s'en servir (manque: {indice})"


def test_l_outil_transmet_ses_parametres_au_lancement():
    launcher._enable_tool_func({"visible_window": True, "profile": "otp"}, {})

    args = _args_du_dernier_lancement()
    assert "--headless" not in args
    assert "--userDataDir" in args


def test_l_outil_sans_parametre_garde_le_defaut():
    launcher._enable_tool_func({}, {})

    assert _args_du_dernier_lancement() == DEFAUT
