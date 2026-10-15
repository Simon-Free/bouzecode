# [desc] Vue d'un agent (main ou sous-agent) dans le TUI : en-tete, conversation rejouee puis suivie en direct (meme rendu que le fil principal), et sa question en attente. [/desc]
from __future__ import annotations

import re

from bouzecode.backend.multi_agent.en_process.fiche import LIBELLES, PRINCIPAL, FicheAgent

from ..ansi import clr
from .rendu import conso, duree


def entete(fiche: FicheAgent) -> str:
    if fiche.id == PRINCIPAL:
        #  main n'a ni description ni etat de fin : son modele et sa conso suffisent.
        details = " · ".join(x for x in (fiche.modele, conso(fiche)) if x)
        return f"╭─ main · {details}" if details else "╭─ main"
    etat = f"{fiche.icone} {LIBELLES.get(fiche.etat, fiche.etat)}"
    details = " · ".join(x for x in (etat, conso(fiche), duree(fiche.duree())) if x)
    return f"╭─ sous-agent « {fiche.description} » ({fiche.type_agent}) · {details}"


def afficher(fiche: FicheAgent):
    """Rejoue toute la conversation de l'agent, main compris (le terminal sert de
    defilement) ; rend le `DerouleConversation` qui poursuit le suivi en direct au meme
    rendu (un appel encore en vol imprimera son resultat a son arrivee)."""
    from ..replay import replay_messages
    print()
    print(clr(entete(fiche), "cyan", "bold"))
    deroule = replay_messages(list(fiche.state.messages), en_cours=fiche.actif)
    if not fiche.actif and fiche.resultat:
        print(clr(f"  ⎿ résultat rendu au parent : {premiere_ligne(fiche.resultat, 160)}", "dim"))
    for texte in lignes_question(fiche):
        print(clr(texte, "magenta", "bold"))
    return deroule


def lignes_question(fiche: FicheAgent) -> list[str]:
    question = fiche.question
    if question is None or question.reponse is not None:
        return []
    lignes = [f"  ? {fiche.description} demande : {question.texte}"]
    lignes += [f"    [{i}] {o.get('label', '')}" for i, o in enumerate(question.options, 1)]
    lignes.append("    (tape ta réponse puis Entrée)")
    return lignes


def question_ouverte(registre, agent_id: str):
    """La question en attente de l'agent affiche, au moment ou l'invite s'ouvre."""
    fiche = registre.fiche(agent_id)
    return fiche.question if fiche is not None and fiche.id != PRINCIPAL else None


def transmettre(registre, agent_id: str, saisie: str, ouverte) -> str:
    """Texte tape dans la vue d'un sous-agent. Sa question prise entre-temps (par son parent,
    en_process/questions.py) : il n'est PAS transmis — la premiere reponse l'emporte."""
    if ouverte is not None and ouverte.reponse is not None:
        return clr(f"  → question déjà répondue par {ouverte.par} (« {ouverte.reponse} ») : "
                   "ton texte n'est pas transmis", "yellow")
    return clr(f"  → {registre.envoyer(agent_id, saisie)}", "dim")


def premiere_ligne(texte: str, largeur: int) -> str:
    lignes = [x for x in str(texte).strip().splitlines() if x.strip()]
    premiere = lignes[0].strip() if lignes else ""
    suite = f" (+{len(lignes) - 1} lignes)" if len(lignes) > 1 else ""
    return (premiere[:largeur] + ("…" if len(premiere) > largeur else "")) + suite


_DEPUIS_RE = re.compile(r" depuis \d+ s")


def comptes_progression(progression: str) -> str:
    """Ce qui merite une nouvelle ligne dans l'onglet : n/N, ✅❌⏭ et -n. Le test le plus
    long et les secondes d'attente en file changent a chaque sondage : ils n'en font pas une."""
    return _DEPUIS_RE.sub("", progression.split(" · le plus long", 1)[0])
