# [desc] Détecte un mandat READ-ONLY écrit en prose alors que la typologie accorde des outils d'écriture. [/desc]
"""« READ-ONLY » dans un prompt ne provisionne RIEN.

Le manager `ba5eba11` a briefé trois tickets « MISSION READ-ONLY (aucune écriture de code
produit, aucune migration) » en leur donnant la typologie `coder` — qui accorde Write, Edit
et Bash. L'un d'eux (`badc0ffe`) a écrit du code de production ET une migration : il n'a
enfreint aucune barrière, il n'y en avait aucune.

C'est le même mode d'échec que `work_branch` écrit en prose, que le profil du manager
signale déjà comme « le plus coûteux de la chaîne, il ne se voit pas ». Ici on le rend
visible AU DISPATCH, avant que l'agent n'écrive quoi que ce soit.
"""
from __future__ import annotations

import re
import unicodedata

READONLY_FLAG_KEY = "readonly_mandate_unenforced"

# Formulations réellement employées dans les prompts du dépôt. Volontairement EXIGEANTES :
# « investigation » seul ne vaut pas mandat, sinon tout ticket d'analyse serait signalé.
_MARQUEURS = (
    r"read[\s-]?only",
    r"lecture seule",
    r"aucune ecriture",
    r"sans ecrire",
    r"n[e']?\s*(?:modifie|ecris|cree)\s+aucun",
    r"ne modifie aucun fichier",
    r"aucun fichier (?:de )?produit",
)
_MARQUEUR_RE = re.compile("|".join(_MARQUEURS))

# `Agent`/`MessageAgent`/`Fleet` pilotent la flotte sans toucher un octet du dépôt : les
# compter ferait passer tout dispatcheur pour un écrivain.
_OUTILS_DE_FLOTTE = frozenset({"Agent", "MessageAgent", "Fleet", "SendMessage"})


def _plier(text: str) -> str:
    decompose = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def declares_read_only(prompt: str) -> bool:
    """Le prompt revendique-t-il un mandat de lecture seule ?"""
    return bool(_MARQUEUR_RE.search(_plier(prompt)))


def _ecrit_dans_le_depot(outil: str) -> bool | None:
    """Source de vérité : le drapeau `read_only` du `ToolDef` enregistré.

    `None` = inconnu de ce processus ; l'appelant le compte écrivain, repli prudent délibéré.

    PIÈGE MESURÉ (2026-07-29, re-mesuré et re-diagnostiqué) : ce repli suppose que l'`import`
    ci-dessous a bien peuplé le registre GLOBAL. Ce n'est pas garanti, et la cause n'est PAS
    un cycle d'imports — les deux ordres (`registration` d'abord, `multi_agent.tools` d'abord)
    donnent 42 outils sur 42, vérifié en sous-processus propre.

    La vraie cause est l'overlay thread-local. Si `push_local_overlay()` est actif au moment
    du PREMIER import de `registration`, ses 35 enregistrements par effet de bord tombent dans
    `_local.registry` — et `pop_local_overlay()` les JETTE. Le module reste dans `sys.modules`,
    donc plus aucun ré-import ne repeuple le global : il garde définitivement les 7 outils
    enregistrés hors overlay (ceux de `multi_agent.tools`). `get_tool("Read")` rend alors
    `None` pour toute la vie du processus, le repli prudent dénonce `Read, Glob, Grep` comme
    outils d'écriture, et tout mandat read-only sain est signalé.

    Sur les chemins RÉELS (route `/api/dispatch`) le registre est complet et le garde est
    juste. Le seul appelant de `push_local_overlay()` en production est une application
    tierce qui embarque bouzecode et enregistre ses propres outils ; dans `src/`
    de bouzecode il n'y en a aucun, les autres appelants sont des tests. Le remède est de
    garantir que les enregistrements par effet de bord atteignent le registre global — pas
    de rustiner ici : compter l'inconnu comme lecteur échangerait ce faux positif contre
    trois détections manquées (vérifié).
    """
    if outil in _OUTILS_DE_FLOTTE:
        return False
    import bouzecode.backend.tools.registration  # noqa: F401 — peuple le registre
    from bouzecode.backend.core.tool_registry import get_tool
    tool = get_tool(outil)
    return None if tool is None else not tool.read_only


def write_tools_of(typology: str) -> list[str]:
    """Les outils d'écriture réellement accordés par cette typologie.

    Une typologie sans liste d'outils déclarée n'a AUCUNE restriction : elle accorde tout,
    donc l'écriture. C'est le cas de `general-purpose` (`tools: []`).
    """
    from bouzecode.backend.profiles import resolve_agent_profile
    nom = (typology or "").strip()
    profil = resolve_agent_profile(nom) if nom else None
    declares = list(getattr(profil, "tools", None) or []) if profil is not None else []
    if not declares:
        return ["(aucune restriction d'outils)"]
    return [outil for outil in declares if _ecrit_dans_le_depot(outil) is not False]


def unenforced_read_only(prompt: str, typology: str) -> list[str]:
    """Les outils d'écriture accordés à un ticket qui se déclare READ-ONLY.

    Liste vide = pas de contradiction (soit le prompt n'est pas read-only, soit la
    typologie ne peut effectivement rien écrire).
    """
    if not declares_read_only(prompt):
        return []
    return write_tools_of(typology)


def readonly_comment(write_tools: list[str]) -> str:
    """Commentaire posé sur le ticket ET rendu au manager."""
    outils = ", ".join(write_tools)
    return (f"⚠️ MANDAT READ-ONLY NON TENU : le prompt impose la lecture seule, mais la "
            f"typologie choisie accorde des outils d'écriture ({outils}). Écrire "
            f"« READ-ONLY » dans le prompt ne provisionne RIEN — l'agent PEUT écrire du "
            f"code de production et des migrations, et le fera. Choisis une typologie sans "
            f"outil d'écriture, ou assume que ce ticket est un ticket d'écriture.")


def readonly_warning(write_tools: list[str]) -> str:
    """Version courte, destinée au `tool_result` du manager."""
    return (f"MANDAT READ-ONLY NON TENU — prompt en lecture seule mais typologie accordant "
            f"{', '.join(write_tools)}. La prose ne provisionne rien : choisis une "
            f"typologie sans outil d'écriture.")
