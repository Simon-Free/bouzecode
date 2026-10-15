# [desc] Contexte de session figé au premier appel d'une session ; ses changements en cours de route (worktree, sortie de worktree, cd, mode plan) deviennent des notes de harnais empilées une fois dans la note (partie cachée). [/desc]
"""Le bloc « # Contexte de session » ne bouge plus une fois envoyé.

Il est dans le system, donc AVANT la note et l'historique : le recalculer à chaque appel faisait
sortir du cache tout ce qui le suit dès que le répertoire changeait. Session c4fe6829 du
2026-10-07 (claude-opus-5-5) : `Environment(action='worktree')` l'a fait passer de 288 à 846
caractères, cache-read de 22 133 → 19 883 tokens et 2 809 réécrits ; la sortie du worktree en a
réécrit 3 544 de plus.

Désormais : le bloc envoyé est celui du premier appel (de la session, ou de la reprise d'une
session antérieure à ce mécanisme), gardé dans `ContextState` et sauvegardé avec la session.
Quand la situation change ensuite, une note « [harnais] … » est rédigée UNE fois et EMPILÉE
(`empiler_note_de_contexte`) : un bloc « ## Harnais @… » ajouté à la fin de la note Methodology,
qui est la partie cachée du payload (<working_notes>, append-only). Elle part une fois dans le
delta de la note (écrite en cache), puis est relue en cache aux appels suivants — entrée puis
sortie de worktree = deux blocs dans l'ordre, jamais réécrits. Le contrat de worktree (récolte,
branche de travail) reste donc visible du modèle sans repartir en <harness_notes> à chaque appel :
2026-10-07/08, 145 appels sur 219 portaient ces notes en fresh tokens (149 k caractères ; la même
note 28 fois dans la session f8894fc5). `notes_de_contexte` en garde le journal.
"""
from __future__ import annotations

import time

# Titre des blocs empilés dans la note. La compaction les garde intacts (compact_prose,
# compact_filet) : une note de contexte n'est jamais reformulée.
ENTETE_NOTE_DE_CONTEXTE = "## Harnais @"

# La date change à minuit sans que rien d'utile ne change pour l'agent : pas de note pour elle.
_SANS_NOTE = ("entete", "date")

_RAPPEL = ("(Le « Contexte de session » du system prompt est celui du début de la session : "
           "cette note le met à jour.)")


def contexte_de_l_appel(config: dict, context_state) -> str:
    """Le bloc de contexte à envoyer pour cet appel : celui du premier appel de la session.

    Sans `context_state` (appel annexe, agent hôte), le contexte de l'instant, comme avant.
    Un changement de situation depuis l'appel précédent empile sa note (cf. module)."""
    from ..core.context import situation_de_session
    situation = situation_de_session(config)
    if context_state is None:
        return "".join(situation["segments"].values())
    if not context_state.contexte_fige:
        context_state.contexte_fige = "".join(situation["segments"].values())
    elif context_state.situation_vue:
        note = note_de_changement(context_state.situation_vue, situation)
        if note:
            empiler_note_de_contexte(context_state, note)
    context_state.situation_vue = situation
    return context_state.contexte_fige


def empiler_note_de_contexte(context_state, note: str) -> None:
    """Ajoute la note à la FIN de la note Methodology (bloc « ## Harnais @… ») et au journal
    `notes_de_contexte`. Jamais réécrite ni retirée ensuite : le texte déjà envoyé reste un
    préfixe de celui de l'appel suivant, donc en cache. Un titre ``## `` dans la note (le
    gabarit du mode plan en a un) est rétrogradé en ``### `` : sinon la compaction y verrait
    le début d'un autre bloc, résumable."""
    from .methodology import _append_block
    horodatage = time.strftime("%Y-%m-%d %H:%M:%S")
    corps = "\n".join("#" + ligne if ligne.startswith("## ") else ligne
                      for ligne in note.strip().split("\n"))
    _append_block(context_state, f"{ENTETE_NOTE_DE_CONTEXTE}{horodatage}\n{corps}\n")
    context_state.notes_de_contexte.append(note)


def note_de_changement(avant: dict, apres: dict) -> str:
    """La note de harnais qui décrit le passage de `avant` à `apres`, "" si rien d'utile n'a
    changé. Une phrase de tête (entrée/sortie de worktree, nouveau répertoire), puis les lignes
    du contexte qui sont nouvelles — c'est là que voyage le contrat de worktree."""
    segments_avant = avant.get("segments") or {}
    segments_apres = apres.get("segments") or {}
    changes = [cle for cle, texte in segments_apres.items()
               if cle not in _SANS_NOTE and segments_avant.get(cle) != texte]
    retires = [cle for cle in segments_avant
               if cle not in _SANS_NOTE and cle not in segments_apres]
    if not changes and not retires:
        return ""
    lignes = [f"[harnais] {_phrase_de_tete(avant, apres, changes)} {_RAPPEL}"]
    lignes += [segments_apres[cle].strip() for cle in changes if cle != "repertoire"]
    if "plan" in retires:
        lignes.append("- Le mode plan est terminé.")
    return "\n".join(lignes)


def _phrase_de_tete(avant: dict, apres: dict, changes: list[str]) -> str:
    branche = f", branche {apres['branche']}" if apres.get("branche") else ""
    worktree_avant, worktree_apres = avant.get("worktree") or "", apres.get("worktree") or ""
    if worktree_apres and worktree_apres != worktree_avant:
        return f"Tu travailles désormais dans le worktree {worktree_apres}{branche}."
    if worktree_avant and not worktree_apres:
        return (f"Tu n'es plus dans le worktree {worktree_avant} : retour à "
                f"{apres['repertoire']}{branche}. Ses consignes (récolte, branche de travail) "
                "ne s'appliquent plus.")
    if "repertoire" in changes:
        return f"Ton répertoire de travail est désormais {apres['repertoire']}{branche}."
    return "Le contexte de session a changé."
