# [desc] Ce qui s'est passé à un tour, en marqueurs lisibles : enforcement, relance, erreur, question, sous-agent, clôture, compaction, cache raté. [/desc]
"""Les marqueurs d'un tour, déduits du payload envoyé et de la réponse reçue.

Un tour « anormal » est ce qu'on regarde en premier quand un agent déraille : un cache
raté, un saut de contexte, un rappel à l'ordre (enforcement), une erreur d'outil ou une
clôture refusée.
"""
from __future__ import annotations

import re

_ERREUR = re.compile(r"^\s*(?:Traceback \(most recent|[\w.]*Error:|✗ Error|ERROR:|.*exit code [1-9])",
                     re.MULTILINE)
#  Contenus de fichiers : un mot « erreur » dans du code lu n'est pas une erreur d'outil.
_LECTURES = frozenset({"Read", "Snippet", "Grep", "Glob", "Methodology", "WebFetch"})
_RELANCE = ("Tous tes enfants ont fini", "Continue là où", "Vérification faite",
            "[Retour", "Ton intégration")

ANORMAUX = frozenset({"cache_rate", "saut_contexte", "enforcement", "erreur",
                      "cloture_refusee"})

LIBELLES = {
    "entree": "Message d'entrée", "relance": "Relance / réveil", "enforcement": "Rappel à l'ordre",
    "erreur": "Erreur d'outil", "question": "Question à l'utilisateur", "sous_agent": "Sous-agent lancé",
    "cloture_acceptee": "Clôture acceptée", "cloture_refusee": "Clôture refusée",
    "compaction": "Note compactée", "cache_rate": "Cache raté", "saut_contexte": "Saut de contexte",
    "changement_fournisseur": "Changement de fournisseur",
}

# Parties du préfixe journalisées à chaque appel (backend/agent/providers/backends/empreinte.py).
PARTIES_DU_PREFIXE = {
    "system": "message système", "tools": "liste des outils",
    "note": "note (bloc qui suit le système)", "messages": "historique des messages",
}
# Passes du harnais qui réécrivent la note, journalisées (champ `phase`) entre deux appels.
REECRITURES_DE_LA_NOTE = {
    "note_snippet_cleanup": "purge d'extraits périmés",
    "note_deep_compaction": "compaction profonde de la note (juge)",
    "note_prose_compaction": "compaction de la note (résumé de la prose)",
    "note_emergency_prune": "filet (élagage d'urgence de la note)",
}
# Un cache lu tombé à moins de la moitié du tour précédent, sur plus de 1 024 tokens : raté.
_CHUTE_MIN = 1024


def texte(contenu) -> str:
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "\n".join(texte(b.get("text", b) if isinstance(b, dict) else b) for b in contenu)
    return str(contenu or "")


def _message_d_entree(dump: dict | None) -> str:
    users = [m for m in (dump or {}).get("messages", []) if m.get("role") == "user"]
    return texte(users[-1].get("content")) if users else ""


def _marqueurs_d_entree(dump: dict | None, tour: int) -> set[str]:
    entree = _message_d_entree(dump)
    if not entree.strip():
        return set()
    if "ENFORCEMENT" in entree:
        return {"enforcement"}
    if tour > 1 and any(motif in entree[:400] for motif in _RELANCE):
        return {"relance"}
    return {"entree"}


def _est_une_erreur(nom: str | None, corps: str) -> bool:
    """Une lecture de fichier n'est en erreur que si l'OUTIL l'annonce (« Error: file not
    found ») ; son contenu, lui, peut contenir n'importe quel mot."""
    if nom in _LECTURES:
        return corps.lstrip().startswith(("Error", "✗"))
    return bool(_ERREUR.search(corps[:1500]))


def _marqueurs_de_reponse(reponse: dict | None) -> set[str]:
    if not reponse:
        return set()
    noms = {tc.get("name") for tc in reponse["assistant"].get("tool_calls") or []}
    marques = {m for n, m in (("AskUserQuestion", "question"), ("Agent", "sous_agent")) if n in noms}
    for resultat in reponse["resultats"]:
        corps = texte(resultat.get("content"))
        if resultat.get("name") == "FinalAnswer":
            marques.add("cloture_refusee" if "REFUSÉE" in corps[:200] else "cloture_acceptee")
        elif _est_une_erreur(resultat.get("name"), corps):
            marques.add("erreur")
    return marques


def _taille_note(dump: dict | None) -> int:
    notes = ((dump or {}).get("context_state") or {}).get("notes") or {}
    return sum(len(str(v)) for v in notes.values())


def _prompt_total(appel: dict) -> int:
    return int(appel.get("api_input_tokens", 0)) + int(appel.get("api_cache_read", 0))


def _chute_du_cache(appel: dict, precedent: dict) -> bool:
    lu, avant = appel.get("api_cache_read", 0), precedent.get("api_cache_read", 0)
    return lu < avant * 0.5 and avant - lu > _CHUTE_MIN


def _fournisseur(appel: dict) -> str:
    return appel.get("provider") or "inconnu"


def _cause_de_la_reecriture(appel: dict) -> str:
    """Passes du harnais journalisées depuis l'appel précédent ; à défaut, marqueur STALE vu
    dans l'extrait ; sinon, cause non identifiée."""
    passes = [REECRITURES_DE_LA_NOTE[p] for p in dict.fromkeys(appel.get("phases_note") or [])
              if p in REECRITURES_DE_LA_NOTE]
    if passes:
        return ", ".join(passes)
    extraits = f"{appel.get('note_extrait', '')} {appel.get('note_extrait_nouveau', '')}"
    if "snippet-stale" in extraits or "STALE" in extraits:
        return "marqueur STALE d'extrait périmé"
    return "cause non identifiée (aucune compaction journalisée depuis l'appel précédent)"


def _note_reecrite(appel: dict) -> str:
    position = appel.get("note_divergence")
    ou = (f" (à la position {position} : « {appel.get('note_extrait', '')} »)"
          if position is not None else "")
    return f"note réécrite chez nous{ou} : {_cause_de_la_reecriture(appel)}"


def cause_du_rate(appel: dict, precedent: dict | None) -> str | None:
    """Pourquoi le cache lu a chuté depuis le tour précédent, d'après l'empreinte du préfixe
    journalisée avec l'appel. None quand le cache n'a pas chuté. Une note seulement allongée
    garde le préfixe : le raté vient du fournisseur ; une note réécrite plus haut, de nous.
    Les sessions d'avant cette distinction portent « note » : formulation d'origine."""
    if precedent is None or not _chute_du_cache(appel, precedent):
        return None
    change = appel.get("prefixe_change")
    if change == "note_allongee":
        return f"note simplement allongée, préfixe intact : raté côté fournisseur ({_fournisseur(appel)})"
    if change == "note_reecrite":
        return _note_reecrite(appel)
    if change in PARTIES_DU_PREFIXE:
        return f"préfixe modifié chez nous : {PARTIES_DU_PREFIXE[change]}"
    if change == "aucune":
        return f"raté côté fournisseur ({_fournisseur(appel)}) : préfixe identique"
    return "cause inconnue : empreintes du préfixe non journalisées pour ce tour"


def _marqueurs_de_cache(appel: dict, precedent: dict | None) -> set[str]:
    if precedent is None:
        return set()
    marques = set()
    total = _prompt_total(appel)
    if (total and appel.get("api_cache_read", 0) / total < 0.5) or _chute_du_cache(appel, precedent):
        marques.add("cache_rate")
    avant = _prompt_total(precedent)
    if avant and total > avant * 1.3 and total - avant > 5000:
        marques.add("saut_contexte")
    # Chaque fournisseur OpenRouter a son propre cache : un changement explique un cache raté.
    if appel.get("provider") and precedent.get("provider") not in (None, "", appel["provider"]):
        marques.add("changement_fournisseur")
    return marques


def marqueurs(appel: dict, precedent: dict | None, dump: dict | None,
              dump_precedent: dict | None, reponse: dict | None) -> list[str]:
    """Marqueurs triés du tour : d'abord les anormaux, puis les autres."""
    marques = (_marqueurs_d_entree(dump, int(appel.get("turn") or 0))
               | _marqueurs_de_reponse(reponse) | _marqueurs_de_cache(appel, precedent))
    if dump_precedent is not None and _taille_note(dump) < _taille_note(dump_precedent):
        marques.add("compaction")
    return sorted(marques, key=lambda m: (m not in ANORMAUX, m))
