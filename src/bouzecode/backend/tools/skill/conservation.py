# [desc] Une skill chargée est figée UNE fois dans la note de travail : ni jetée après lecture, ni rechargée. [/desc]
"""Conservation d'une skill dans la note de travail (methodology).

Session c4fe6829 (2026-10-07, claude-opus-5-5) : `Skill(azure-deployment)` chargée
(10 065 caractères), résumée en deux lignes, jetée (`Snippet(discard=true)`, poussé par
l'inventaire « trash any you've already consumed ») — puis RECHARGÉE en entier trois
tours plus tard, quand le déploiement a échoué. La garder coûte ~4 k tokens relus en
cache par tour ; la recharger, ~4 k tokens d'entrée plus l'écriture en cache.

Le harnais fige donc lui-même la skill dans la note, par le chemin d'un `Snippet` (même
bloc, même compaction, même marquage si le fichier est modifié). Bornes :
- un seul bloc par skill : un rappel de la même skill rend un renvoi vers la note au
  lieu du texte (et n'ajoute rien) ;
- la compaction de la note juge ce bloc comme tout snippet : il disparaît quand il ne
  sert plus, et un rappel suivant le recharge.
Sans note de travail, sans fichier sur disque, ou avec des arguments (le texte rendu
diffère alors du fichier), rien ne change : la skill est rendue comme avant.
"""
from __future__ import annotations

from pathlib import Path

#  Marqueur de tête du résultat : les inventaires « à snippeter / à jeter » le reconnaissent.
CONSERVEE = "[Conservée dans ta note de travail"
_AVIS_CONSERVEE = (CONSERVEE + " jusqu'à la fin de la tâche (bloc `{entete}`) : ne la "
                   "snippete pas, ne la jette pas, ne la recharge pas — relis-la dans ta note.]")
_AVIS_DEJA_CHARGEE = ("Skill DÉJÀ dans ta note de travail (bloc `{entete}`) : relis-la là, "
                      "rien n'est rechargé.")


def skill_conservee(contenu: str) -> bool:
    """Ce résultat de Skill est-il déjà figé dans la note (donc rien à snippeter ni jeter) ?"""
    return CONSERVEE in (contenu or "")


def _entete(chemin: str, nb_lignes: int, nom: str) -> str:
    return f'## snippet: {chemin} L1-{nb_lignes} — "skill:{nom}"'


def _note(etat) -> str:
    from ...context_manager.state import METHODOLOGY_NOTE
    return etat.notes.get(METHODOLOGY_NOTE, "") or ""


def conserver_dans_la_note(skill, args: str, config: dict | None) -> tuple[str, bool]:
    """(avis à mettre en tête du résultat, True si la skill était DÉJÀ dans la note).

    Avis vide : la skill n'est pas conservée et le résultat reste celui d'avant."""
    etat = (config or {}).get("_context_state")
    chemin_brut = getattr(skill, "file_path", "") or ""
    if etat is None or args or not chemin_brut or not Path(chemin_brut).is_file():
        return "", False
    chemin = str(Path(chemin_brut))
    nb_lignes = len(Path(chemin).read_text(encoding="utf-8", errors="replace").splitlines())
    entete = _entete(chemin, nb_lignes, skill.name)
    if entete in _note(etat):
        return _AVIS_DEJA_CHARGEE.format(entete=entete), True
    from ...context_manager.methodology import snippet_tool
    snippet_tool({"file_path": chemin, "ranges": [[1, nb_lignes]],
                  "label": f"skill:{skill.name}"}, config)
    #  La compaction déclenchée par l'ajout a pu juger le bloc aussitôt : alors, rien
    #  n'est conservé et la skill est rendue en entier, comme avant.
    if entete not in _note(etat):
        return "", False
    return _AVIS_CONSERVEE.format(entete=entete), False
