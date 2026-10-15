# [desc] Empreintes courtes du préfixe envoyé au LLM (système, outils, note, historique) et première partie changée depuis l'appel précédent du même rôle ; pour la note et l'historique, allongement pur ou réécriture (position du premier caractère différent, court extrait) : de quoi dire si un raté de cache vient de nous ou du fournisseur. [/desc]
"""Empreinte du préfixe d'un appel LLM.

Un raté de cache (essai DeepSeek via DeepInfra : 2 048 tokens lus en cache sur 17 586, contre
≈ 12 000 aux tours voisins) a deux explications possibles : nous avons changé un octet du
préfixe, ou le fournisseur a perdu son cache. Le journal des payloads ne garde ni le système ni
les outils : on ne pouvait pas trancher. On journalise donc, à chaque appel, un sha256 tronqué
et la longueur de chaque partie du préfixe, dans l'ordre où le modèle les lit :

- ``system`` : le bloc système stable (noyau + profil) ;
- ``tools`` : les outils (schémas natifs sérialisés canoniquement, ou doc XML des outils) ;
- ``note`` : l'enveloppe ``<working_notes>`` (note Methodology, delta, amorce) en tête du
  premier message user — dans le système jusqu'au 2026-10-07 ;
- ``messages`` : l'historique, dont on compare les messages que l'appel précédent avait déjà
  envoyés (sauf son dernier, qui porte les rappels du tour et change donc toujours).

La note change à chaque tour (elle grossit) : « note » seul ne distinguait pas une note
simplement ALLONGÉE (l'ancienne tête cachable est un préfixe exact de la nouvelle : le cache doit
tenir, un raté vient du fournisseur) d'une note RÉÉCRITE plus haut (purge d'extraits,
compaction, filet… : c'est nous qui cassons le cache). On garde donc en mémoire, par session
(sur l'``AgentState``) et par rôle, les textes de l'appel précédent — jamais au journal — et on
journalise seulement : allongement pur ou non, position du premier caractère différent, taille
perdue et deux courts extraits (avant / après) autour de cette position. Idem pour l'historique.

Rien n'est envoyé au LLM ; le calcul est un hachage par message, négligeable devant l'appel.
"""
from __future__ import annotations

import hashlib
import json
import os

_TAILLE = 12
# Extrait journalisé autour d'une divergence : 20 caractères avant, 40 après.
_AVANT, _APRES = 20, 40
# Mémoire des textes de l'appel précédent, par rôle, posée sur l'état de la session.
_MEMOIRE = "_prefixes_precedents"


def _texte(valeur) -> str:
    """Le texte tel quel ; une structure (outils, message) en JSON canonique."""
    if isinstance(valeur, str):
        return valeur
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=str)


def _court(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:_TAILLE]


def _cumul(textes: list[str]) -> list[str]:
    """``cumul[k]`` = empreinte des k premiers messages."""
    h, cumul = hashlib.sha256(), []
    cumul.append(h.hexdigest()[:_TAILLE])
    for texte in textes:
        h.update(texte.encode("utf-8"))
        cumul.append(h.hexdigest()[:_TAILLE])
    return cumul


def calculer(ordre: tuple[str, ...], parties: dict, messages: list,
             note_stable: int | None = None) -> dict:
    """Empreintes d'un appel. ``parties`` : system / tools / note tels qu'envoyés.
    ``note_stable`` : longueur de la tête CACHABLE de la note (note + delta), le reste (contexte
    de session, règle finale) changeant à chaque tour par construction ; toute la note si None.
    Les clés ``_…`` restent en mémoire (comparaison avec l'appel suivant), jamais au journal."""
    textes_messages = [_texte(m) for m in messages]
    cumul = _cumul(textes_messages)
    n = len(messages)
    textes = {nom: _texte(v) for nom, v in parties.items()}
    empreintes = {nom: _court(t) for nom, t in textes.items()}
    longueurs = {nom: len(t) for nom, t in textes.items()}
    empreintes["messages"] = cumul[max(n - 1, 0)]
    longueurs["messages"] = sum(len(t) for t in textes_messages)
    note = textes.get("note", "")
    return {"ordre": list(ordre), "empreintes": empreintes, "longueurs": longueurs,
            "n_messages": n, "_cumul": cumul, "_note": note,
            "_note_stable": len(note) if note_stable is None else note_stable,
            "_messages": textes_messages}


def premiere_partie_changee(courant: dict, precedent: dict) -> str:
    """"aucune", ou la première partie (dans l'ordre de lecture) qui diffère de l'appel précédent."""
    for nom in courant["ordre"]:
        if nom == "messages":
            deja_envoyes = max(int(precedent.get("n_messages", 0)) - 1, 0)
            cumul = courant["_cumul"]
            if deja_envoyes >= len(cumul) or cumul[deja_envoyes] != precedent["empreintes"].get(nom):
                return nom
        elif courant["empreintes"].get(nom) != precedent["empreintes"].get(nom):
            return nom
    return "aucune"


def divergence(ancien: str, nouveau: str) -> int | None:
    """None si ``nouveau`` commence par ``ancien`` (allongement pur), sinon la position du premier
    caractère différent."""
    if nouveau.startswith(ancien):
        return None
    return len(os.path.commonprefix([ancien, nouveau]))


def extrait(texte: str, position: int) -> str:
    """Court extrait lisible autour de ``position`` : « … » aux bords coupés, retours à la ligne
    rendus visibles (⏎) pour tenir sur une ligne."""
    debut, fin = max(position - _AVANT, 0), min(position + _APRES, len(texte))
    corps = texte[debut:fin].replace("\r\n", "⏎").replace("\n", "⏎")
    return ("…" if debut else "") + corps + ("…" if fin < len(texte) else "")


def comparer_note(courant: dict, precedent: dict) -> dict:
    """Champs journalisés pour la note : allongement pur de la tête cachable précédente, ou
    réécriture (position, taille perdue, extraits avant / après)."""
    ancienne, nouvelle = precedent["_note"], courant["_note"]
    position = divergence(ancienne[:precedent["_note_stable"]], nouvelle)
    if position is None:
        return {"note_allongee": True, "note_divergence": None}
    return {"note_allongee": False, "note_divergence": position,
            "note_perdue": len(ancienne) - position,
            "note_extrait": extrait(ancienne, position),
            "note_extrait_nouveau": extrait(nouvelle, position)}


def _premier_message_different(anciens: list[str], nouveaux: list[str]) -> int | None:
    for i, ancien in enumerate(anciens):
        if i >= len(nouveaux) or nouveaux[i] != ancien:
            return i
    return None


def comparer_messages(courant: dict, precedent: dict) -> dict:
    """Champs journalisés pour l'historique : les messages déjà envoyés (sauf le dernier de
    l'appel précédent, porteur des rappels du tour) sont-ils repris à l'identique ? Sinon,
    position (en caractères, dans l'historique sérialisé) du premier caractère différent."""
    anciens = precedent["_messages"][:max(len(precedent["_messages"]) - 1, 0)]
    nouveaux = courant["_messages"]
    i = _premier_message_different(anciens, nouveaux)
    if i is None:
        return {"messages_allonges": True, "messages_divergence": None}
    dans_le_message = len(os.path.commonprefix([anciens[i], nouveaux[i] if i < len(nouveaux) else ""]))
    return {"messages_allonges": False,
            "messages_divergence": sum(len(t) for t in anciens[:i]) + dans_le_message,
            "messages_divergence_message": i,
            "messages_perdus": sum(len(t) for t in anciens[i:]) - dans_le_message,
            "messages_extrait": extrait(anciens[i], dans_le_message)}


def _changement(courant: dict, precedent: dict, memoire: dict | None) -> tuple[str, dict]:
    """``prefixe_change`` et champs de détail. La note précise « note_allongee » /
    « note_reecrite » quand l'appel précédent est en mémoire ; « note » sinon (reprise)."""
    change = premiere_partie_changee(courant, precedent)
    if memoire is None:
        return change, {}
    details = {**comparer_note(courant, memoire), **comparer_messages(courant, memoire)}
    if change == "note":
        change = "note_allongee" if details["note_allongee"] else "note_reecrite"
    return change, details


def completer(entree: dict, empreinte: dict | None, state) -> None:
    """Ajoute ``prefixe`` et ``prefixe_change`` (+ détails note / historique) à une entrée
    ``llm_call``/``side_call`` avant son ajout au journal de ``state``. Le rôle comparé : même
    événement et même libellé d'appel annexe (une compaction n'a pas le système d'un
    classifieur). Pas de référence → pas de ``prefixe_change``."""
    if not empreinte:
        return
    journal = state.compaction_log
    entree["prefixe"] = {k: v for k, v in empreinte.items() if not k.startswith("_")}
    role = (entree.get("event"), entree.get("label", ""))
    memoires = getattr(state, _MEMOIRE, None)
    if memoires is None:
        memoires = {}
        setattr(state, _MEMOIRE, memoires)
    memoire = memoires.get(role)
    memoires[role] = empreinte
    precedent = next((e for e in reversed(journal)
                      if (e.get("event"), e.get("label", "")) == role), None)
    if precedent and precedent.get("prefixe"):
        entree["prefixe_change"], details = _changement(empreinte, precedent["prefixe"], memoire)
        entree.update(details)
