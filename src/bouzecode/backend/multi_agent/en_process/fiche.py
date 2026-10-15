# [desc] Fiche d'un agent du TUI (principal ou sous-agent en process) : identite, etat, question en attente, alertes, et sa conso lue sur la comptabilite des tours (AgentState). [/desc]
"""Une fiche par agent visible dans la barre du TUI.

La conso n'est PAS recomptee ici : elle se lit sur l'`AgentState` de l'agent, que la boucle
(`agent.loop._account_llm_call`) alimente a chaque appel LLM — la meme source que le bandeau
de fin de tour et que les sessions sur disque.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

PRINCIPAL = "main"

EN_COURS = "en_cours"
QUESTION = "question"
FINI = "fini"
ERREUR = "erreur"
ANNULE = "annule"

ETATS_ACTIFS = frozenset({EN_COURS, QUESTION})

#  L'etat se lit SANS couleur : une icone par etat (la couleur n'est qu'un plus).
ICONES = {EN_COURS: "▶", QUESTION: "?", FINI: "✓", ERREUR: "✗", ANNULE: "■"}
LIBELLES = {EN_COURS: "en cours", QUESTION: "attend ta réponse", FINI: "fini",
            ERREUR: "erreur", ANNULE: "interrompu"}


@dataclass
class Question:
    texte: str
    options: list = field(default_factory=list)
    texte_libre: bool = True
    reponse: Optional[str] = None
    numero: int = 0                # cite par le parent qui y repond (MessageAgent question=N)
    destinataire: str = ""         # agent a qui elle a ete transmise (parent, ou ancetre)
    avis: str = ""                 # le message depose dans sa boite aux lettres
    par: str = ""                  # qui a repondu : « l'utilisateur » ou un agent


@dataclass
class FicheAgent:
    id: str
    parent_id: str = ""
    type_agent: str = "general-purpose"
    description: str = ""
    modele: str = ""
    profondeur: int = 0
    etat: str = EN_COURS
    debut: float = field(default_factory=time.time)
    fin: Optional[float] = None
    state: Any = None              # AgentState de l'agent : messages et compteurs de tokens
    question: Optional[Question] = None
    alertes: list = field(default_factory=list)
    resultat: str = ""
    activite: str = ""             # outil en cours, pour la ligne de la barre
    progression: str = ""          # progression d'outil (pytest n/N) : imprimee dans SON onglet
    tache: Any = None              # SubAgentTask du gestionnaire (None pour le principal)
    reprendre: Optional[Callable[[str], None]] = None
    chemin_session: str = ""       # sa session sur disque (daily/<date>/session_*_<id>.json)
    journal: Any = None            # sa sortie stdout/stderr (core.sortie_agent.JournalAgent)

    @property
    def actif(self) -> bool:
        return self.etat in ETATS_ACTIFS

    @property
    def icone(self) -> str:
        return ICONES.get(self.etat, "·")

    def duree(self, maintenant: Optional[float] = None) -> float:
        bout = self.fin if self.fin is not None else (maintenant or time.time())
        return max(0.0, bout - self.debut)

    def tokens(self) -> dict:
        s = self.state
        return {"entree": int(getattr(s, "total_input_tokens", 0) or 0),
                "sortie": int(getattr(s, "total_output_tokens", 0) or 0),
                "cache_lu": int(getattr(s, "total_cache_read_tokens", 0) or 0),
                "cache_ecrit": int(getattr(s, "total_cache_creation_tokens", 0) or 0)}

    def cout(self) -> Optional[float]:
        """Cout en dollars, None si le modele n'a pas de tarif connu (jamais un faux 0 $)."""
        from ...agent.providers.registry import calc_cost, is_priced
        if not self.modele or not is_priced(self.modele):
            return None
        t = self.tokens()
        return calc_cost(self.modele, t["entree"], t["sortie"], t["cache_lu"], t["cache_ecrit"])

    def cache_courant(self):
        """Prefixe en cache apres le DERNIER appel (cache lu + ecrit), pas un cumul ; None
        sans appel avec cache (cf. agent.cache_courant)."""
        from ...agent.cache_courant import cache_courant
        return cache_courant(self.state)
