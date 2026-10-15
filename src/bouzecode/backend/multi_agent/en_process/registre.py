# [desc] Registre thread-safe des agents du TUI : arbre principal/sous-agents, alertes Signaler, interruption et attente. Boites aux lettres et questions : courrier.py. Aucun terminal ici. [/desc]
"""Le registre est l'unique verite partagee entre les fils des sous-agents et l'ecran.

Les fils d'execution (execution.py) l'ecrivent ; la barre et la navigation (ui/barre_agents)
le lisent. Tout passe par une `Condition` : chaque changement incremente `version` et reveille
ceux qui attendent (outil Agent en attente, ecran qui suit un agent).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from .courrier import CourrierAgents
from .fiche import PRINCIPAL, FicheAgent, Question


class RegistreAgents(CourrierAgents):
    """Fiches, arbre, alertes, interruption ; boites aux lettres et questions : courrier.py."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._fiches: dict[str, FicheAgent] = {}
        self._boites: dict[str, list[str]] = {}
        self._alertes: list[str] = []
        self._questions: list[Question] = []  # toutes, numerotees a partir de 1
        #  Effaces par /clear : masques de la barre, mais leur fiche reste lisible par leur fil.
        self._purges: set[str] = set()
        self.version = 0
        #  Pose par l'ecran : attend (fini, noms d'outils) en laissant naviguer l'utilisateur.
        self.hote_attente: Optional[Callable] = None

    # ── fiches ────────────────────────────────────────────────────────────
    def declarer_principal(self, state, modele: str) -> FicheAgent:
        fiche = FicheAgent(id=PRINCIPAL, type_agent=PRINCIPAL, modele=modele, state=state)
        with self._cond:
            self._fiches[PRINCIPAL] = fiche
            self._notifier()
        return fiche

    def ajouter(self, fiche: FicheAgent) -> FicheAgent:
        with self._cond:
            self._fiches[fiche.id] = fiche
            self._notifier()
        return fiche

    def fiche(self, agent_id: str) -> Optional[FicheAgent]:
        return self._fiches.get(agent_id)

    def changer(self, agent_id: str, **champs) -> None:
        with self._cond:
            fiche = self._fiches[agent_id]
            for cle, valeur in champs.items():
                setattr(fiche, cle, valeur)
            self._notifier()

    def sous_agents(self) -> list[FicheAgent]:
        return [f for f in list(self._fiches.values())
                if f.id != PRINCIPAL and f.id not in self._purges]

    def vider(self) -> tuple[int, int]:
        """/clear : interrompt les sous-agents en cours et retire tous les sous-agents de la
        barre ; rend (interrompus, termines effaces)."""
        interrompus = effaces = 0
        with self._cond:
            for fiche in self.sous_agents():
                if fiche.actif:
                    if fiche.tache is not None:
                        fiche.tache._cancel_flag = True
                    interrompus += 1
                else:
                    effaces += 1
                self._purges.add(fiche.id)
                self._boites.pop(fiche.id, None)
            self._notifier()
        return interrompus, effaces

    def actifs(self) -> list[FicheAgent]:
        return [f for f in self.sous_agents() if f.actif]

    def enfants_de(self, agent_id: str) -> list[FicheAgent]:
        return [f for f in self.sous_agents() if (f.parent_id or PRINCIPAL) == agent_id]

    def arbre(self) -> list[FicheAgent]:
        """Le principal puis chaque sous-agent sous son parent (ordre de lancement)."""
        ordre: list[FicheAgent] = []

        def descendre(agent_id: str) -> None:
            for enfant in self.enfants_de(agent_id):
                ordre.append(enfant)
                descendre(enfant.id)

        principal = self.fiche(PRINCIPAL)
        if principal is not None:
            ordre.append(principal)
        descendre(PRINCIPAL)
        return ordre

    def descendants(self, agent_id: str) -> list[FicheAgent]:
        tous = []
        for enfant in self.enfants_de(agent_id):
            tous += [enfant, *self.descendants(enfant.id)]
        return tous

    # ── alertes, interruption, attente ────────────────────────────────────
    def signaler(self, agent_id: str, gravite: str, titre: str) -> None:
        fiche = self._fiches[agent_id]
        with self._cond:
            fiche.alertes.append(f"[{gravite}] {titre}")
            self._alertes.append(f"⚑ [{gravite}] {titre} — sous-agent {fiche.description or fiche.id}")
            self._notifier()

    def alertes_nouvelles(self) -> list[str]:
        with self._cond:
            nouvelles, self._alertes = self._alertes, []
        return nouvelles

    def interrompre(self, agent_id: str) -> list[str]:
        """Interrompt cet agent ET ses descendants encore actifs ; rend leurs ids."""
        fiche = self.fiche(agent_id)
        if fiche is None or fiche.id == PRINCIPAL:
            return []
        cibles = [f for f in [fiche, *self.descendants(agent_id)] if f.actif and f.tache]
        with self._cond:
            for cible in cibles:
                cible.tache._cancel_flag = True
            self._notifier()
        return [c.id for c in cibles]

    def attendre_changement(self, delai: float) -> None:
        with self._cond:
            version = self.version
            self._cond.wait_for(lambda: self.version != version, timeout=delai)

    def _notifier(self) -> None:
        self.version += 1
        self._cond.notify_all()
