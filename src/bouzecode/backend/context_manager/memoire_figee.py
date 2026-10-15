# [desc] Mémoire du projet figée au premier appel d'une session : la section « # Memory » du system ne bouge plus, ses changements (cd vers un autre projet, fichier mémoire modifié) deviennent des notes de harnais empilées dans la note. [/desc]
"""La section « # Memory » du system ne bouge plus une fois envoyée.

Elle est dans la moitié STABLE du system, donc AVANT la note et l'historique : relue à chaque
message, elle faisait sortir du cache tout ce qui la suit dès que la mémoire visible changeait —
`LoadProjectConfig(cd=true)` ou un worktree vers un projet qui a un autre `.bouzecode/memory`,
ou un fichier mémoire écrit pendant la session (aucun outil dédié : `Write`/`Edit`/`Bash`).

Même mécanisme que le contexte de session (contexte_fige.py) : la mémoire du premier appel est
gardée dans `ContextState` et sauvegardée avec la session ; un changement ultérieur produit UNE
note « [harnais] … » empilée UNE fois à la fin de la note Methodology (partie cachée), jamais
renvoyée ensuite en <harness_notes>.

Forme de la note : la plus courte de la mémoire entière et de la liste des changements. Une
entrée est une ligne d'index (nom + description, pas le corps du fichier) : la liste des
changements est donc compacte quand un fichier bouge, et la mémoire entière l'emporte quand
presque tout change (autre projet : tout retiré, tout ajouté).
"""
from __future__ import annotations

_TETE = "[harnais] La mémoire du projet a changé."
_RAPPEL_ENTIERE = ("Elle remplace la section « # Memory » du system prompt, qui est celle du "
                   "début de la session. Nouvelle mémoire :")
_RAPPEL_CHANGEMENTS = ("Ces changements s'appliquent à la section « # Memory » du system prompt, "
                       "qui est celle du début de la session, et la remplacent pour ces entrées :")


def memoire_de_l_appel(context_state) -> str:
    """La mémoire à mettre dans le system : celle du premier appel de la session.

    Sans `context_state` (appel annexe, agent hôte, aperçu), la mémoire de l'instant, comme
    avant. Un changement depuis l'appel précédent empile sa note (`empiler_note_de_contexte` ;
    comparaison du contenu, pas des dates)."""
    from ..core.context import entrees_de_memoire
    entrees = entrees_de_memoire()
    if context_state is None:
        return "\n".join(entrees.values())
    if context_state.memoire_figee is None:
        context_state.memoire_figee = "\n".join(entrees.values())
    else:
        note = note_de_changement_de_memoire(context_state.memoire_vue, entrees)
        if note:
            from .contexte_fige import empiler_note_de_contexte
            empiler_note_de_contexte(context_state, note)
    context_state.memoire_vue = entrees
    return context_state.memoire_figee


def note_de_changement_de_memoire(avant: dict, apres: dict) -> str:
    """La note qui décrit le passage de `avant` à `apres` ({chemin : ligne}), "" si la mémoire
    visible est la même."""
    if avant == apres:
        return ""
    entiere = "\n".join([f"{_TETE} {_RAPPEL_ENTIERE}", *(apres.values() or ["(vide)"])])
    changees = [ligne for chemin, ligne in apres.items() if avant.get(chemin) != ligne]
    retirees = [chemin for chemin in avant if chemin not in apres]
    lignes = [f"{_TETE} {_RAPPEL_CHANGEMENTS}"]
    if changees:
        lignes += ["Ajoutées ou modifiées :", *changees]
    if retirees:
        lignes += ["Retirées : " + ", ".join(_nom_de_fichier(c) for c in retirees)]
    changements = "\n".join(lignes)
    return entiere if len(entiere) <= len(changements) else changements


def _nom_de_fichier(chemin: str) -> str:
    return chemin.replace("\\", "/").rsplit("/", 1)[-1]
