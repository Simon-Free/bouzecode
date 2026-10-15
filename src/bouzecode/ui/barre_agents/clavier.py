# [desc] Clavier de la barre des agents : etat de navigation pur (vue, focus, selection — testable sans terminal) et touches prompt_toolkit (fleche bas vers la liste, haut/bas, Entree ouvre, Echap revient a main, x / Ctrl+X interrompt). [/desc]
"""Comme Claude Code : fleche bas (saisie vide) donne le focus a la liste ; haut/bas
choisissent ; Entree ouvre l'agent choisi ; Echap revient a l'agent principal."""
from __future__ import annotations

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from bouzecode.backend.multi_agent.en_process.fiche import PRINCIPAL


class Navigation:
    def __init__(self) -> None:
        self.vue = PRINCIPAL      # agent dont la conversation est affichee / recoit la saisie
        self.focus = False        # True : les fleches parcourent la liste, pas l'historique
        self.selection = 0        # index dans rendu.ordre (0 = main)
        self.debut = 0            # premier sous-agent visible (fenetre de rendu.FENETRE)

    def cadrer(self, nombre: int, fenetre: int) -> int:
        """Recale la fenetre pour que la selection reste visible ; rend son debut."""
        if self.focus and self.selection >= 1:
            index = self.selection - 1
            if index < self.debut:
                self.debut = index
            elif index >= self.debut + fenetre:
                self.debut = index - fenetre + 1
        self.debut = max(0, min(self.debut, nombre - fenetre))
        return self.debut

    def entrer_focus(self, ids: list[str]) -> bool:
        """Fleche bas sur une saisie vide. Rien a choisir sans sous-agent."""
        if len(ids) < 2:
            return False
        self.focus = True
        courant = ids.index(self.vue) if self.vue in ids else 0
        self.selection = 1 if courant == 0 else courant
        return True

    def descendre(self, ids: list[str]) -> None:
        self.selection = min(self.selection + 1, len(ids) - 1)

    def monter(self, ids: list[str]) -> None:
        """Fleche haut ; au-dessus de main, on rend la main a la zone de texte."""
        if self.selection <= 0:
            self.quitter_focus()
            return
        self.selection -= 1

    def selectionne(self, ids: list[str]) -> str:
        if not ids:
            return PRINCIPAL
        return ids[min(self.selection, len(ids) - 1)]

    def valider(self, ids: list[str]) -> str:
        """Entree dans la liste : l'agent choisi devient la vue courante."""
        self.vue = self.selectionne(ids)
        self.focus = False
        return self.vue

    def echapper(self) -> str:
        """Echap : quitte la liste et revient a l'agent principal."""
        self.focus = False
        self.vue = PRINCIPAL
        return self.vue

    def quitter_focus(self) -> None:
        self.focus = False


def _sortir(app, resultat) -> None:
    """Idempotent : le suivi peut le redemander a chaque pas jusqu'a la fermeture effective."""
    if app.future is not None and not app.future.done():
        app.exit(result=resultat)


def touches(ecran) -> KeyBindings:
    """`ecran` porte `registre` et `nav` ; une touche qui change de vue sort de la saisie avec
    ("vue", id) — l'ecran affiche alors la conversation de cet agent."""
    cles = KeyBindings()
    registre, nav = ecran.registre, ecran.nav

    def ids() -> list[str]:
        from .rendu import ordre
        return [f.id for f in ordre(registre)]

    focus = Condition(lambda: nav.focus)
    saisie_vide = Condition(lambda: not ecran.session().default_buffer.text)
    avec_agents = Condition(lambda: bool(registre.sous_agents()))
    dans_une_vue = Condition(lambda: nav.vue != PRINCIPAL)

    @cles.add("down", filter=~focus & saisie_vide & avec_agents, eager=True)
    def _vers_la_liste(event):
        nav.entrer_focus(ids())

    @cles.add("down", filter=focus, eager=True)
    def _bas(event):
        nav.descendre(ids())

    @cles.add("up", filter=focus, eager=True)
    def _haut(event):
        nav.monter(ids())

    @cles.add("enter", filter=focus, eager=True)
    def _ouvrir(event):
        _sortir(event.app, ("vue", nav.valider(ids())))

    @cles.add("escape", filter=focus | (dans_une_vue & saisie_vide), eager=True)
    def _revenir(event):
        _sortir(event.app, ("vue", nav.echapper()))

    @cles.add("x", filter=focus, eager=True)
    def _interrompre_selection(event):
        registre.interrompre(nav.selectionne(ids()))

    @cles.add("c-x", filter=dans_une_vue & ~focus, eager=True)
    def _interrompre_la_vue(event):
        registre.interrompre(nav.vue)

    #  Ctrl+C sur un sous-agent (vue ouverte ou selection dans la liste) n'interrompt QUE lui :
    #  sans ce binding, prompt_toolkit levait KeyboardInterrupt et tout le tour de main tombait.
    @cles.add("c-c", filter=focus, eager=True)
    def _ctrl_c_selection(event):
        registre.interrompre(nav.selectionne(ids()))

    @cles.add("c-c", filter=dans_une_vue & ~focus, eager=True)
    def _ctrl_c_la_vue(event):
        registre.interrompre(nav.vue)

    @cles.add(Keys.Any, filter=focus)
    def _taper_quitte_la_liste(event):
        nav.quitter_focus()
        event.current_buffer.insert_text(event.data)

    return cles
