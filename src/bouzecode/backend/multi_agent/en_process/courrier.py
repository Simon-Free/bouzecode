# [desc] Boites aux lettres et questions des agents du TUI (melangees dans RegistreAgents) : deposer/relever un message, router une saisie vers un agent (reponse, file, reprise), poser une question et y repondre — la premiere reponse l'emporte. [/desc]
"""Partie « courrier » du registre : meme `Condition`, memes notifications (`_notifier`).

Une question posee avec `au_parent=True` (AskUserQuestion d'un sous-agent) part aussi a son
parent : voir questions.py.
"""
from __future__ import annotations

from typing import Optional

from . import questions
from .fiche import ANNULE, EN_COURS, PRINCIPAL, QUESTION, FicheAgent, Question


class CourrierAgents:
    def deposer(self, agent_id: str, texte: str) -> None:
        with self._cond:
            self._boites.setdefault(agent_id, []).append(texte)
            self._notifier()

    def relever(self, agent_id: str) -> list[str]:
        with self._cond:
            return self._boites.pop(agent_id, [])

    def a_du_courrier(self, agent_id: str) -> bool:
        """Un message attend CET agent (sans le consommer)."""
        with self._cond:
            return bool(self._boites.get(agent_id))

    def courrier(self, agent_id: str) -> list[str]:
        with self._cond:
            return list(self._boites.get(agent_id, []))

    def retirer(self, agent_id: str, texte: str) -> bool:
        """Retire un message pas encore lu ; False s'il a deja ete releve."""
        with self._cond:
            boite = self._boites.get(agent_id, [])
            if texte not in boite:
                return False
            boite.remove(texte)
            self._notifier()
            return True

    def envoyer(self, agent_id: str, texte: str, par: str = questions.UTILISATEUR) -> str:
        """Route un message (de l'utilisateur, ou d'un agent par MessageAgent) vers CET
        agent, selon son etat."""
        fiche = self.fiche(agent_id)
        if fiche is None:
            return f"agent {agent_id} inconnu : message non transmis"
        nom = fiche.description or fiche.id
        if fiche.question is not None and fiche.question.reponse is None:
            if self.repondre(agent_id, texte, par):
                return f"réponse transmise à « {nom} »"
            return f"sa question vient d'être répondue par {fiche.question.par} : message non transmis"
        if fiche.actif or agent_id == PRINCIPAL:
            self.deposer(agent_id, texte)
            return f"message mis en file pour « {nom} » : lu à sa prochaine étape"
        if fiche.reprendre is None:
            return f"« {nom} » ne peut pas être relancé : message non transmis"
        fiche.reprendre(texte)
        return f"« {nom} » reprend avec ton message"

    def poser_question(self, agent_id: str, texte: str, options=None, texte_libre=True,
                       au_parent: bool = False) -> str:
        """Appele depuis le fil du sous-agent : bloque jusqu'a la reponse (ou l'interruption).
        `au_parent` : la question part AUSSI a son parent (questions.py) — jamais pour une
        permission, que seul l'utilisateur accorde."""
        options = [{"label": o} if isinstance(o, str) else o for o in (options or [])]
        fiche = self._fiches[agent_id]
        with self._cond:
            question = Question(texte=texte, options=options, texte_libre=texte_libre,
                                numero=len(self._questions) + 1)
            self._questions.append(question)
            fiche.question, fiche.etat = question, QUESTION
            if au_parent:
                questions.transmettre(self, fiche, question)
            self._notifier()
            while question.reponse is None and not _annule(fiche):
                self._cond.wait(0.2)
                if au_parent and question.reponse is None:
                    questions.reacheminer(self, fiche, question)
            fiche.question = None
            fiche.etat = EN_COURS
            if au_parent and question.reponse is None:  # interrompue : l'avis non lu part
                questions.cloturer(self, question)
            self._notifier()
        return question.reponse if question.reponse is not None else "(interrompu par l'utilisateur)"

    def repondre(self, agent_id: str, texte: str, par: str = questions.UTILISATEUR) -> bool:
        """La premiere reponse l'emporte : False si la question est deja prise."""
        fiche = self.fiche(agent_id)
        question = fiche.question if fiche is not None else None
        if question is None:
            return False
        brut = texte.strip()
        if brut.isdigit() and 1 <= int(brut) <= len(question.options):
            brut = question.options[int(brut) - 1].get("label", brut)
        with self._cond:
            if question.reponse is not None:
                return False
            question.reponse, question.par = brut or "(pas de réponse)", par
            if question.avis:  # AUSSITOT : un avis perime couperait l'attente du parent
                questions.cloturer(self, question)
            self._notifier()
        return True

    def question_numero(self, numero: int) -> Optional[Question]:
        with self._cond:
            return self._questions[numero - 1] if 1 <= numero <= len(self._questions) else None


def _annule(fiche: FicheAgent) -> bool:
    return bool(fiche.tache is not None and fiche.tache._cancel_flag) or fiche.etat == ANNULE
