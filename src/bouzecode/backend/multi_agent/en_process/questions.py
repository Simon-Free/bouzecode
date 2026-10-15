# [desc] Questions des sous-agents du TUI : remontees au PARENT (ou au premier ancetre vivant, main en dernier) comme un message de sa boite aux lettres ; le parent y repond (MessageAgent question=N) ou la relaie (AskUserQuestion) ; l'utilisateur peut toujours repondre depuis la vue du sous-agent — la premiere reponse l'emporte. [/desc]
"""La voie d'une question posee par un sous-agent (`AskUserQuestion` dans son fil).

- `transmettre` : l'avis part dans la boite du destinataire ; il le lit a sa prochaine
  frontiere de lot, son attente d'enfants (Agent, CheckAgentResult) s'interrompt, et main au
  repos est reveille par l'ecran (`a_traiter`).
- `reacheminer` : destinataire fini ou interrompu → l'avis passe au premier ancetre vivant.
- `cloturer` : une fois repondue, l'avis non lu est retire ; deja lu et repondu par un autre,
  le destinataire est prevenu de ne plus y repondre.
"""
from __future__ import annotations

from .fiche import PRINCIPAL, FicheAgent, Question

UTILISATEUR = "l'utilisateur"


def destinataire(registre, fiche: FicheAgent) -> str:
    """Le parent s'il travaille encore, sinon le premier ancetre vivant ; main en dernier."""
    courant = fiche.parent_id or PRINCIPAL
    while courant != PRINCIPAL:
        ancetre = registre.fiche(courant)
        if ancetre is None:
            return PRINCIPAL
        if ancetre.actif and courant in {f.id for f in registre.sous_agents()}:
            return courant
        courant = ancetre.parent_id or PRINCIPAL
    return PRINCIPAL


def nom(registre, agent_id: str) -> str:
    fiche = registre.fiche(agent_id)
    return (fiche.description or fiche.id) if fiche is not None and agent_id != PRINCIPAL else "main"


def avis(fiche: FicheAgent, question: Question, pour: str) -> str:
    """Ce que lit le modele du destinataire : la question et ses DEUX gestes possibles."""
    options = " · ".join(f"[{i}] {o.get('label', '')}" for i, o in enumerate(question.options, 1))
    relais = "l'utilisateur" if pour == PRINCIPAL else "ton propre parent"
    repondre = f"MessageAgent(ticket_id='{fiche.id}', text='<réponse>', question={question.numero})"
    return "\n".join(x for x in [
        f"[Question n°{question.numero} du sous-agent « {fiche.description or fiche.id} » "
        f"(id {fiche.id})] Il est BLOQUÉ jusqu'à ce qu'on lui réponde :",
        question.texte,
        f"Options : {options}" if options else "",
        "Traite-la, de l'une de ces deux façons :",
        f"1. Tu connais la réponse : réponds-lui toi-même avec {repondre}.",
        f"2. Tu ne la connais pas : remonte-la avec AskUserQuestion (elle va à {relais}), puis "
        f"transmets la réponse obtenue avec {repondre}.",
        "L'utilisateur peut aussi répondre depuis la vue de ce sous-agent : la première réponse "
        "l'emporte (MessageAgent te dit si elle est déjà prise).",
    ] if x)


def transmettre(registre, fiche: FicheAgent, question: Question) -> None:
    question.destinataire = destinataire(registre, fiche)
    question.avis = avis(fiche, question, question.destinataire)
    registre.deposer(question.destinataire, question.avis)


def reacheminer(registre, fiche: FicheAgent, question: Question) -> None:
    """Destinataire parti (fini, erreur, interrompu, efface) sans repondre : l'ancetre suivant."""
    ancien = question.destinataire
    if ancien == PRINCIPAL or destinataire(registre, fiche) == ancien:
        return
    registre.retirer(ancien, question.avis)
    transmettre(registre, fiche, question)


def cloturer(registre, question: Question) -> None:
    """Repondue : l'avis encore non lu disparait ; deja lu, le destinataire apprend que
    quelqu'un d'autre a repondu (sans le reveiller : `a_traiter` ne voit que les questions)."""
    if question.reponse is None:  # interrompue : rien a dire, l'avis non lu est retire
        registre.retirer(question.destinataire, question.avis)
        return
    if registre.retirer(question.destinataire, question.avis) or question.par == nom(
            registre, question.destinataire):
        return
    lecteur = registre.fiche(question.destinataire)
    if question.destinataire != PRINCIPAL and (lecteur is None or not lecteur.actif):
        return  # parti entre-temps : une relance ne doit pas lire un avis perime
    registre.deposer(question.destinataire,
                     f"[Question n°{question.numero} : {question.par} y a déjà répondu "
                     f"(« {question.reponse} ») — n'y réponds plus.]")


def a_traiter(registre, agent_id: str) -> bool:
    """Une question d'un sous-agent attend CET agent, et il n'en a pas encore lu l'avis."""
    boite = registre.courrier(agent_id)
    return any(f.question is not None and f.question.reponse is None
               and f.question.destinataire == agent_id and f.question.avis in boite
               for f in registre.sous_agents())


def repondre_a(registre, fiche: FicheAgent, numero: int, texte: str, par: str) -> str:
    """MessageAgent(question=N) : repond a la question N de cet enfant, sauf si deja prise."""
    question = fiche.question
    if question is not None and question.numero == numero and registre.repondre(fiche.id, texte, par):
        return "réponse transmise, il repart avec"
    deja = registre.question_numero(numero)
    if deja is not None and deja.reponse is not None:
        return (f"question n°{numero} DÉJÀ répondue par {deja.par} (« {deja.reponse} ») : ton "
                "texte n'est PAS transmis")
    return (f"aucune question n°{numero} en attente chez lui : ton texte n'est PAS transmis "
            "(renvoie-le sans `question` pour un simple message)")
