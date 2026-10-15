# [desc] Ce que le harnais ajoute au fil, balisé côté user : la note en <working_notes> en tête du premier message user, ses consignes en <harness_notes> après les tool_results. [/desc]
"""Encapsulation côté user de la note et des consignes du harnais.

Refus `content_filter` de claude-opus-5-5 sur la préprod du gateway, rejeu des payloads réels du
2026-10-07, 10 essais par variante (Methodology déjà retirée du fil) : tour 9 de bb991b7c
10/10 refus → note dans le premier message user 3/10 → et consignes hors des tool_results
0/10 ; tours 10 (bb991b7c) et 13 (4802718c) : 8/10 → 0/10. Un texte écrit par le modèle (la
note) en rôle system, et des consignes déguisées en données d'outil, ressemblent à une
injection pour le classifieur. Comme Claude Code, on les balise côté user.

La note garde ses `cache_control` (parties de contenu) : outils + system + note restent un
préfixe caché, et le nombre de points de cache ne change pas (au plus 4).
"""
from __future__ import annotations

from ...snippet_wire import HARNESS_NOTE_KEY

OUVERTURE_NOTE = "<working_notes>\n"
FERMETURE_NOTE = "\n</working_notes>\n\n"

# Marque le message user <harness_notes> : les convertisseurs Anthropic le fusionnent dans le
# message user qui porte les tool_result (bloc text en fin), au lieu d'un message à part.
NOTES_DU_HARNAIS = "_notes_du_harnais"


def parties_de_la_note(blocs_caches: list[dict], textes: list[str]) -> list[dict]:
    """Les parties de la note, balisées : blocs à `cache_control` (note, delta) d'abord, tels
    quels — leur texte bout à bout reste un préfixe de celui du tour suivant —, puis les textes
    sans point de cache (amorce d'une note vide, autres notes) et la balise fermante."""
    parties = [dict(b) for b in blocs_caches]
    libres = "\n\n".join(t for t in textes if t and t.strip())
    if not parties and not libres:
        return []
    parties.append({"type": "text", "text": (libres + FERMETURE_NOTE) if libres else FERMETURE_NOTE})
    parties[0] = {**parties[0], "text": OUVERTURE_NOTE + parties[0]["text"]}
    return parties


def _suivie_de(parties: list[dict], contenu) -> list[dict]:
    """Les parties de la note puis le contenu du message : une liste se met à la suite, un texte
    se colle à la balise fermante (pas de partie de plus, aucun séparateur à deviner)."""
    if isinstance(contenu, list):
        return parties + list(contenu)
    fin = parties[-1]["text"] + contenu if contenu else parties[-1]["text"].rstrip()
    return parties[:-1] + [{**parties[-1], "text": fin}]


def avec_la_note(messages: list, parties: list[dict]) -> list:
    """Le fil, la note en tête de son premier message — un message user à part s'il ne commence
    pas par un user (le préfixe caché doit précéder tout l'historique)."""
    if not parties:
        return messages
    fil = list(messages)
    if fil and fil[0].get("role") == "user":
        fil[0] = {**fil[0], "content": _suivie_de(parties, fil[0].get("content"))}
        return fil
    return [{"role": "user", "content": _suivie_de(parties, "")}, *fil]


def avec_les_notes_du_harnais(messages: list, inventaire: str) -> list:
    """Le fil, suivi après son dernier tool_result d'un message user <harness_notes> : les
    consignes posées sur les résultats (HARNESS_NOTE_KEY) puis l'inventaire des résultats encore
    en contexte. Rien s'il n'y a rien à dire ou pas de tool_result. Les changements de contexte
    (worktree, cd, mémoire) n'y passent plus : ils sont empilés dans la note, en cache
    (contexte_fige.empiler_note_de_contexte)."""
    outils = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    consignes = [messages[i][HARNESS_NOTE_KEY] for i in outils if messages[i].get(HARNESS_NOTE_KEY)]
    lignes = [*consignes, *([inventaire] if inventaire else [])]
    if not lignes or not outils:
        return messages
    texte = "<harness_notes>\n" + "\n\n".join(lignes) + "\n</harness_notes>"
    fil = list(messages)
    fil.insert(outils[-1] + 1, {"role": "user", "content": texte, NOTES_DU_HARNAIS: True})
    return fil


def notes_du_harnais_suivantes(messages: list, i: int) -> str:
    """Le texte <harness_notes> si le message `i` est celui du harnais, sinon ""."""
    if i < len(messages) and messages[i].get(NOTES_DU_HARNAIS):
        return messages[i]["content"]
    return ""
