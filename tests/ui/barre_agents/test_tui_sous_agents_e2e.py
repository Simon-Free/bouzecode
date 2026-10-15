# [desc] Le vrai REPL interactif pilote au clavier (entree prompt_toolkit en pipe) face a un faux LLM HTTP : main lance 2 sous-agents, la barre les montre, fleches + Entree basculent de vue, Echap revient a main, la question d'un enfant remonte a main (qui y repond, meme reveille a l'invite), un message atteint le bon enfant. [/desc]
"""Tout est reel sauf le modele (faux LLM HTTP sans etat, faux_llm_agents.py) et l'ecran
(une sortie vt100 en memoire, dont on relit le texte). Le REPL tourne dans un fil ; le test
tape au clavier et attend chaque etat avant la touche suivante."""
from __future__ import annotations

import contextlib
import io
import re
import sys
import threading
import time

from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

from bouzecode.backend.multi_agent.en_process.fiche import FINI, PRINCIPAL

from .faux_llm_agents import MODELE, FauxLlmAgents

BAS, ENTREE, ECHAP = "\x1b[B", "\r", "\x1b"
_ECHAPPEMENTS = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Za-z0-9]|\x1b[=>]|\r")


class _Ecran(Vt100_Output):
    """Terminal de 40 x 140 en memoire ; la hauteur sous le curseur est connue (sinon
    prompt_toolkit n'affiche pas la barre du bas)."""

    def __init__(self) -> None:
        self.flux = io.StringIO()
        super().__init__(self.flux, lambda: Size(rows=40, columns=140), term="xterm",
                         enable_cpr=False)

    def get_rows_below_cursor_position(self) -> int:
        return 30

    def texte(self) -> str:
        return _ECHAPPEMENTS.sub("", self.flux.getvalue())


def _attendre(condition, quoi: str, delai: float = 20.0, etat=None):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"jamais atteint : {quoi}" + (f" — {etat()}" if etat else ""))


def _resultats_d_outil(state, nom: str) -> list[str]:
    return [str(m.get("content")) for m in state.messages
            if m.get("role") == "tool" and m.get("name") == nom]


def config_contre_le_faux_llm(monkeypatch, llm, dossier) -> dict:
    """La config d'un REPL branche sur le faux LLM local, ses sessions et journaux dans le
    dossier du test, et les globaux que repl() fixe restaures a la fin du test."""
    from bouzecode.backend.core.config import load_config
    from tests import cache_conversation_helpers

    #  Le garde-fou « pas de vrai LLM » vise le gateway : ici l'URL est le faux LLM local.
    monkeypatch.setattr(cache_conversation_helpers, "LIVE_API_ALLOWED", True)
    for cle in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(cle, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", llm.url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-factice")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    #  repl() fixe ce global de rendu : le restaurer pour les tests suivants du worker.
    from bouzecode.ui import rendering
    monkeypatch.setattr(rendering, "_RICH_LIVE", rendering._RICH_LIVE)
    from bouzecode.ui.barre_agents import rendu
    monkeypatch.setattr(rendu, "_source_pied", None)  # repl() pose la barre en pied : restauree
    monkeypatch.setattr(rendu, "_pied_dessine", False)
    from bouzecode.backend.core import tool_registry  # repl() active la flotte locale : restauree
    monkeypatch.setattr(tool_registry, "_flotte_locale", False)
    #  Sessions (principal ET sous-agents) et journaux de payloads : dans le dossier du test.
    from bouzecode.backend.core import config as module_config
    monkeypatch.setattr(module_config, "DAILY_DIR", dossier / "daily")
    monkeypatch.setattr(module_config, "CONFIG_DIR", dossier)
    config = load_config()
    config.update(model=MODELE, permission_mode="accept-all", rich_live=False)
    return config


@contextlib.contextmanager
def _tui_pilote(monkeypatch, llm, dossier, prompt_de_lancement=None):
    """Le REPL interactif dans un fil, branche sur un clavier en pipe et un ecran en memoire
    (avec, s'il est donne, le prompt passe au lancement) ; a la sortie, ses sous-agents sont
    interrompus et le REPL quitte par /exit."""
    from bouzecode.ui.repl import repl

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    config = config_contre_le_faux_llm(monkeypatch, llm, dossier)
    ecran = _Ecran()
    with create_pipe_input() as clavier:
        def lancer_le_repl():
            with create_app_session(input=clavier, output=ecran):
                with contextlib.suppress(SystemExit):
                    repl(config, initial_prompt=prompt_de_lancement)

        fil = threading.Thread(target=lancer_le_repl, daemon=True)
        fil.start()
        _attendre(lambda: "_tui_agents" in config, "REPL interactif arme")
        try:
            yield clavier, ecran, config
        finally:
            registre = config["_tui_agents"]
            for fiche in registre.sous_agents():
                registre.interrompre(fiche.id)
            _attendre(lambda: not registre.actifs(), "sous-agents arretes", 10)
            #  Echap seulement dans la vue d'un sous-agent : dans la vue main il n'est lie a rien,
            #  et prompt_toolkit le colle au « / » qui suit (Alt+/) — « exit » partait a main.
            if config["_attente_lot"].__self__.nav.vue != PRINCIPAL:
                clavier.send_text(ECHAP)
                time.sleep(0.3)
            clavier.send_text("/exit" + ENTREE)
            fil.join(15)
            assert not fil.is_alive(), "le REPL n'a pas quitte"


def test_main_lance_deux_sous_agents_et_on_navigue_entre_eux(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    with FauxLlmAgents() as llm, _tui_pilote(monkeypatch, llm, tmp_path) as (clavier, ecran, config):
        registre, nav = config["_tui_agents"], config["_attente_lot"].__self__.nav

        def ouvrir(fiche):
            """Fleche bas (focus sur le 1er sous-agent), bas jusqu'a lui, Entree."""
            clavier.send_text(BAS)
            _attendre(lambda: nav.focus, "focus dans la liste")
            from bouzecode.ui.barre_agents import rendu
            rang = [f.id for f in rendu.ordre(registre)].index(fiche.id)
            clavier.send_text(BAS * (rang - 1) + ENTREE)
            _attendre(lambda: nav.vue == fiche.id, f"vue {fiche.description}")

        # 1. L'utilisateur demande ; main lance alpha (qui pose une question) et beta, en
        #    parallele (leur ordre dans la barre depend de qui demarre en premier).
        clavier.send_text("[principal] lance deux enfants" + ENTREE)
        _attendre(lambda: len(registre.sous_agents()) == 2, "deux sous-agents")
        par_nom = {f.description: f for f in registre.sous_agents()}
        alpha, beta = par_nom["alpha"], par_nom["beta"]

        # 2. La question d'alpha remonte a main et coupe son attente : main y repond lui-meme
        #    (MessageAgent), personne n'a rien tape ; puis main livre.
        principal = registre.fiche(PRINCIPAL).state
        _attendre(lambda: alpha.etat == FINI and beta.etat == FINI, "alpha et beta livrent",
                  etat=lambda: [(f.description, f.etat, f.activite) for f in (alpha, beta)])
        assert any("bleu" in r for r in _resultats_d_outil(alpha.state, "AskUserQuestion"))
        assert any("réponse transmise" in r for r in _resultats_d_outil(principal, "MessageAgent"))
        _attendre(lambda: principal.final_answer == "main a reçu les deux rapports", "main livre",
                  etat=lambda: [str(m.get("content"))[:120] for m in principal.messages[-4:]])
        _attendre(lambda: "◯ ✓ general-purpose  alpha" in ecran.texte()
                  and "◯ ✓ general-purpose  beta" in ecran.texte(), "la barre les montre")
        assert "● main" in ecran.texte()
        #  Pendant que main retravaillait (invite fermee), la barre etait sous son spinner.
        assert "general-purpose  alpha" in capsys.readouterr().out

        # 3. Fleches + Entree : la vue passe a beta ; Echap revient a main.
        ouvrir(beta)
        clavier.send_text(ECHAP)
        _attendre(lambda: nav.vue == PRINCIPAL, "retour a main")

        # 4. Au repos : ecrire a beta (fini) le fait reprendre ; alpha ne recoit rien.
        ouvrir(beta)
        clavier.send_text("encore" + ENTREE)
        _attendre(lambda: beta.resultat == "reprise B", "beta repris",
                  etat=lambda: (beta.etat, beta.activite, beta.resultat,
                                getattr(beta.tache, "_cancel_flag", None),
                                getattr(beta.tache, "status", None),
                                beta.state.close_reason, beta.state.close_detail,
                                beta is registre.fiche(beta.id), len(registre.sous_agents()),
                                [str(m.get("content"))[:60] for m in beta.state.messages[-3:]]))
        assert any(m.get("content") == "encore" for m in beta.state.messages)
        assert not any(m.get("content") == "encore" for m in alpha.state.messages)


def test_main_au_repos_est_reveille_par_la_question_d_un_sous_agent(monkeypatch, tmp_path):
    """Invite ouverte, personne ne tape : la question de q devient un tour de main, qui y
    repond — l'utilisateur n'a rien eu a faire."""
    monkeypatch.chdir(tmp_path)
    with FauxLlmAgents() as llm, _tui_pilote(monkeypatch, llm, tmp_path) as (clavier, ecran, config):
        registre, ecran_agents = config["_tui_agents"], config["_attente_lot"].__self__
        nav, principal = ecran_agents.nav, registre.fiche(PRINCIPAL).state
        clavier.send_text("[principal:repos] lance q" + ENTREE)
        _attendre(lambda: principal.final_answer == "main a fini", "main livre une 1re fois")
        q = registre.sous_agents()[0]
        #  L'utilisateur relance q depuis sa vue, puis ne tape plus rien.
        clavier.send_text(BAS)
        _attendre(lambda: nav.focus, "focus dans la liste")
        clavier.send_text(ENTREE)
        _attendre(lambda: nav.vue == q.id, "vue q")
        clavier.send_text("[reprise:Q] repose ta question" + ENTREE)
        #  main, au repos, est reveille : il repond lui-meme a q, qui livre.
        _attendre(lambda: q.resultat == "Q a reçu sa réponse", "q livre la réponse de main",
                  etat=lambda: (q.etat, registre.courrier(PRINCIPAL), nav.vue,
                                [str(m.get("content"))[:80] for m in principal.messages[-3:]]))
        assert any("vert" in r for r in _resultats_d_outil(q.state, "AskUserQuestion"))
        assert any("réponse transmise" in r for r in _resultats_d_outil(principal, "MessageAgent"))
        assert any("[Question n°1 du sous-agent « q »" in str(m.get("content"))
                   for m in principal.messages if m.get("role") == "user")
        assert nav.vue == PRINCIPAL  # reveille, main reprend la vue
        _attendre(lambda: ecran_agents.session().app.is_running, "invite rouverte apres le tour")
