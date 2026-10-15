# [desc] Saisie du TUI avec la barre des agents sous la ligne de commande : lecture (prompt_toolkit + patch_stdout), suivi en direct de l'agent affiche, routage de la saisie, attente interactive des sous-agents. [/desc]
"""`EcranAgents` remplace la lecture du REPL quand des sous-agents peuvent exister.

- `saisir(invite)` : la saisie du REPL au repos. Le texte tape dans la vue d'un sous-agent
  lui est envoye ; dans la vue `main` (ou une /commande) il est rendu au REPL. Une question
  d'un sous-agent remontee a main (en_process/questions.py) ferme l'invite (saisie vide) et
  devient un tour de main : main y repond ou la relaie, sans attendre l'utilisateur.
- `attente(fini, noms)` : pose sur la config du principal (`_attente_lot`). Quand l'outil
  Agent / CheckAgentResult du principal attend, la saisie et la barre restent ouvertes ;
  un texte tape dans la vue `main` part dans sa boite aux lettres (lu a sa prochaine etape).
"""
from __future__ import annotations

import threading
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from bouzecode.backend.core.sortie_agent import routage
from bouzecode.backend.multi_agent.en_process import questions
from bouzecode.backend.multi_agent.en_process.fiche import LIBELLES, PRINCIPAL

from ..ansi import clr
from . import vue
from .rendu import duree, fragments
from .clavier import Navigation, _sortir, touches

STYLE = Style.from_dict({
    "paste-badge": "fg:ansicyan italic", "bottom-toolbar": "noreverse",
    "bottom-toolbar.text": "", "barre.selection": "reverse bold",
    "barre.question": "fg:ansimagenta bold", "barre.erreur": "fg:ansired",
    "barre.fini": "fg:ansigreen", "barre.annule": "fg:ansibrightblack",
    "barre.aide": "fg:ansibrightblack italic"})

INVITE_ATTENTE = clr("\n[main attend ses sous-agents] ", "dim") + clr("» ", "cyan", "bold")
_OUTILS_QUI_ATTENDENT = frozenset({"Agent", "CheckAgentResult"})


class EcranAgents:
    def __init__(self, registre, config: dict) -> None:
        self.registre, self.config, self.nav = registre, config, Navigation()
        self.fil_repl = threading.get_ident()
        self.occupe = False
        self._session = None
        self._construction = threading.Lock()
        self._vue_affichee = PRINCIPAL
        self._deroules: dict[str, object] = {}  # agent -> DerouleConversation (replay.py)
        self._etats: dict[str, str] = {}
        self._questions: dict[str, object] = {}
        self._progressions: dict[str, str] = {}  # agent -> comptes deja imprimes

    # ── prompt_toolkit ────────────────────────────────────────────────────
    def session(self) -> PromptSession:
        with self._construction:  # une seule session, quel que soit le fil qui la demande
            if self._session is None:
                from ..paste_input import main_session_with
                self._session = main_session_with(
                    touches(self), session_class=_classe_session(self),
                    refresh_interval=0.25, style=STYLE)
        return self._session

    def barre(self):
        return fragments(self.registre, self.nav, get_app().output.get_size().columns - 1)

    def lire(self, invite: str, fin=None):
        from ..paste_input import _read_with_badges
        arret = threading.Event()
        #  La session est construite AVANT le suivi, qui recoit celle-la : sinon, a la 1re
        #  lecture (prompt de lancement : pendant une attente de main) et sur une machine
        #  chargee (construction > 0,25 s), le suivi en construisait une seconde, la gardait,
        #  et guettait une invite qui ne tournait jamais — Entree seule rendait la main.
        session = self.session()
        #  patch_stdout pose son propre sys.stdout (ecrit au-dessus de l'invite) : le routage
        #  par agent se remet par-dessus, sinon un sous-agent y ecrirait chez main.
        with patch_stdout(raw=True), routage():
            suivi = threading.Thread(target=self._suivre, args=(arret, fin, session), daemon=True)
            suivi.start()
            try:
                return _read_with_badges(invite, session)
            finally:
                arret.set()
                suivi.join(1.0)

    def _suivre(self, arret: threading.Event, fin, session: PromptSession) -> None:
        """Tant que l'invite est ouverte : nouveautes a l'ecran ; des que `fin()` est vrai, la
        fermer — redemande a chaque pas jusqu'a ce que `lire` rende la main, l'invite pouvant
        n'avoir pas encore demarre (ou sa boucle pas encore posee) quand `fin()` devient vrai."""
        while not arret.wait(0.25):
            if fin is not None and fin():
                app = session.app
                boucle = app.loop
                if app.is_running and boucle is not None and not boucle.is_closed():
                    boucle.call_soon_threadsafe(_sortir, app, ("fin",))
                continue
            self.imprimer_nouveautes()

    # ── affichage ─────────────────────────────────────────────────────────
    def imprimer_nouveautes(self) -> None:
        """Alertes Signaler, changements d'etat des sous-agents, suivi de l'agent affiche."""
        for alerte in self.registre.alertes_nouvelles():
            print(clr(f"  {alerte}", "red" if "[bloquant]" in alerte else "yellow"))
        for fiche in self.registre.sous_agents():
            if self._etats.get(fiche.id, "") != fiche.etat and (fiche.id in self._etats or not fiche.actif):
                print(clr(f"  {fiche.icone} sous-agent « {fiche.description} » : "
                          f"{LIBELLES.get(fiche.etat, fiche.etat)} ({duree(fiche.duree())})", "dim"))
            self._etats[fiche.id] = fiche.etat
        fiche = self.registre.fiche(self.nav.vue)
        if fiche is None or fiche.id == PRINCIPAL or self._vue_affichee != fiche.id:
            return
        #  Meme rendu que le rejeu de la bascule (vue.afficher), poursuivi la ou il s'est arrete.
        deroule = self._deroules.get(fiche.id)
        if deroule is not None:
            deroule.avancer(list(fiche.state.messages))
        progression = getattr(fiche, "progression", "")
        comptes = vue.comptes_progression(progression)
        if progression and self._progressions.get(fiche.id) != comptes:
            self._progressions[fiche.id] = comptes
            print(clr(f"  {progression}", "dim"))
        if fiche.question is not None and self._questions.get(fiche.id) is not fiche.question:
            self._questions[fiche.id] = fiche.question
            for texte in vue.lignes_question(fiche):
                print(clr(texte, "magenta", "bold"))

    def traiter(self, action) -> None:
        """Afficher l'agent X — main compris : un seul chemin, sa conversation rejouee."""
        _type, agent_id = action
        if agent_id == self._vue_affichee:
            return
        fiche = self.registre.fiche(agent_id)
        self._deroules[agent_id] = vue.afficher(fiche)
        self._questions[agent_id] = fiche.question
        self._vue_affichee = agent_id

    def invite(self, invite_principale: str) -> str:
        fiche = self.registre.fiche(self.nav.vue)
        if fiche is None or fiche.id == PRINCIPAL:
            return invite_principale
        verbe = "répondre à" if fiche.question is not None else "→"
        return clr(f"\n[{verbe} {fiche.description}] ", "magenta") + clr("» ", "cyan", "bold")

    # ── boucles ───────────────────────────────────────────────────────────
    def saisir(self, invite_principale: str) -> str:
        """Saisie du REPL au repos : rend le texte destine a main (ou une /commande)."""
        principal = self.registre.fiche(PRINCIPAL)
        principal.modele = self.config.get("model", principal.modele)
        while True:
            self.imprimer_nouveautes()
            ouverte = vue.question_ouverte(self.registre, self.nav.vue)
            saisie = self.lire(self.invite(invite_principale), fin=self._question_pour_main)
            if saisie == ("fin",):
                tour = self._tour_de_question()
                if tour:
                    return tour
            elif isinstance(saisie, tuple):
                self.traiter(saisie)
            elif self.nav.vue == PRINCIPAL or saisie.lstrip().startswith("/"):
                return saisie
            elif saisie.strip():
                print(vue.transmettre(self.registre, self.nav.vue, saisie, ouverte))

    def _question_pour_main(self) -> bool:
        """Reveil de main au repos — jamais sur un texte en cours de frappe."""
        return (not self.session().default_buffer.text
                and questions.a_traiter(self.registre, PRINCIPAL))

    def _tour_de_question(self) -> str:
        """Le courrier de main (dont l'avis de question) devient son tour, vue main."""
        if self.nav.vue != PRINCIPAL:
            self.traiter(("vue", self.nav.echapper()))
        tour = "\n\n".join(self.registre.relever(PRINCIPAL))
        if tour:
            print(clr("  ? question d'un sous-agent : main la prend en charge", "magenta"))
        return tour

    def attente(self, fini, noms) -> None:
        """Hook `_attente_lot` : interactif sur le fil du REPL, sinon une courte pause."""
        if (threading.get_ident() != self.fil_repl or self.occupe
                or not _OUTILS_QUI_ATTENDENT & set(noms) or not self.registre.actifs()):
            time.sleep(0.1)
            return
        from ..rendering import flush_response
        from ..spinner import _start_tool_spinner, _stop_tool_spinner
        self.occupe = True
        _stop_tool_spinner()
        flush_response()
        print(clr("  ⏸ main attend ses sous-agents — ↓ (saisie vide) pour les parcourir ; un "
                  "message tapé ici est lu par main à sa prochaine étape", "dim"))
        try:
            while not fini():
                ouverte = vue.question_ouverte(self.registre, self.nav.vue)
                saisie = self.lire(self.invite(INVITE_ATTENTE), fin=fini)
                if saisie == ("fin",):
                    break
                if isinstance(saisie, tuple):
                    self.traiter(saisie)
                elif saisie.strip():
                    print(vue.transmettre(self.registre, self.nav.vue, saisie, ouverte))
        finally:
            self.occupe = False
            if self.nav.vue != PRINCIPAL:
                self.traiter(("vue", self.nav.echapper()))
            self.imprimer_nouveautes()
            _start_tool_spinner()


def _classe_session(ecran):
    """La barre se replie (aucune ligne) tant qu'il n'y a aucun sous-agent."""
    class SessionAvecBarre(PromptSession):
        @property
        def bottom_toolbar(self):
            return ecran.barre if ecran.registre.sous_agents() else None

        @bottom_toolbar.setter
        def bottom_toolbar(self, _valeur):
            pass

    return SessionAvecBarre
