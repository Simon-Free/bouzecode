# [desc] Détecte un mandat READ-ONLY écrit en prose alors que la typologie accorde des outils d'écriture. [/desc]
"""« READ-ONLY » dans un prompt ne provisionne RIEN.

Le manager `31b01ead` a briefé trois tickets « MISSION READ-ONLY (aucune écriture de code
produit, aucune migration) » en leur donnant la typologie `coder` — qui accorde Write, Edit
et Bash. L'un d'eux (`e6846ab5`) a écrit du code de production ET une migration : il n'a
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
# compter ferait passer tout dispatcheur pour un écrivain. `LancerAgent` (donné au manager pour
# Rundeck) délègue de même : c'est l'agent lancé qui écrit, sous SA typologie.
_OUTILS_DE_FLOTTE = frozenset({"Agent", "MessageAgent", "Fleet", "SendMessage", "LancerAgent"})

# Objets d'interdiction qui NE SONT PAS le dépôt : une base, une API, un jeu de données.
# Interdire d'y écrire ne dit rien des fichiers de code, et c'est la cause n°1 des faux
# positifs relevés.
_CIBLE_HORS_DEPOT = re.compile(
    r"\b(base|bases|bdd|db|demodb|table|tables|sql|select|schema|api|endpoint|"
    r"seed|source de donnees|sources de donnees|donnees|prod|production)\b")

#  « code de production » et « fichier de production », c'est LE DÉPÔT, pas une source de
#  données. Les classer hors dépôt via `production` faisait rater trois mandats read-only
#  réels (« MISSION READ-ONLY (aucune ecriture de code/fichier de production) », prompts de
#  tests/scope_guard_prompts.py) : le seul segment porteur du marqueur était écarté, donc
#  aucun mandat détecté. On réécrit la tournure en « code produit » AVANT l'analyse ;
#  `production` employé seul (« ne touche pas à la production ») reste hors dépôt.
_CODE_DE_PRODUCTION = re.compile(r"\b(code|fichier|fichiers) (?:de )?production\b")

#  Une écriture explicitement JETABLE n'est pas une écriture dans le dépôt : « tu peux écrire
#  des scripts d'investigation JETABLES uniquement, n'introduis AUCUN fichier tracké » est un
#  mandat read-only, pas son contraire. Sans cette exception, le veto d'écriture (jusqu'ici
#  appliqué à TOUT le prompt d'un coup) désarmait la détection sur ce seul mot.
_ECRITURE_JETABLE = re.compile(
    r"jetable|jetables|temporaire|temporaires|scratch|non tracke|non trackes|"
    r"aucun fichier tracke|pas de fichier tracke")

# L'interdiction est BORNÉE (tout sauf X) : le ticket écrit quelque part, il n'est pas
# read-only.
_PORTEE_RESTREINTE = re.compile(
    r"\b(hors de|hors du|hors des|en dehors|autre fichier|autres fichiers|autre que|"
    r"sauf|excepte|a part|d'autre|hormis)\b")

# Écriture explicitement accordée : veto sur tout le prompt.
_AUTORISE_ECRITURE = re.compile(
    r"ecriture autorisee|ecriture permise|autorise a ecrire|autorisee sur le seul|"
    r"tu peux (?:ecrire|modifier|creer)|le seul fichier|uniquement (?:le |dans le )?fichier")


def _plier(text: str) -> str:
    decompose = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def declares_read_only(prompt: str) -> bool:
    """Le prompt interdit-il d'écrire DANS LE DÉPÔT ?

    La question n'est pas « le prompt parle-t-il d'interdiction d'écriture » : quatre
    tickets bien cadrés d'affilée (2026-08-25) ont été signalés à tort parce que leur
    interdiction visait une SOURCE DE DONNÉES (« SELECT uniquement sur DEMODB »,
    « ne lance pas le seed en écriture sur la base partagée ») ou une PORTÉE restreinte
    (« ne touche à aucun autre fichier du dépôt », écriture autorisée sur un fichier
    nommé). Un avertissement qui crie sur les tickets corrects n'est plus lu du tout.
    On ne le retire pas — on ne le lève que sur l'objet qu'il prétend surveiller.
    """
    plie = _CODE_DE_PRODUCTION.sub("code produit", _plier(prompt))
    segments = re.split(r"[.;:!?\n]+", plie)
    # Une autorisation d'écriture explicite tranche à elle seule : le ticket ÉCRIT, ses
    # interdictions ne sont que le cadrage de cette écriture. Elle est cherchée SEGMENT par
    # segment et non sur tout le prompt : un fichier de travail jetable, autorisé dans sa
    # propre phrase, n'accorde aucune écriture dans le dépôt.
    for segment in segments:
        if _AUTORISE_ECRITURE.search(segment) and not _ECRITURE_JETABLE.search(segment):
            return False
    for segment in segments:
        if not _MARQUEUR_RE.search(segment):
            continue
        if _CIBLE_HORS_DEPOT.search(segment) or _PORTEE_RESTREINTE.search(segment):
            continue  # l'interdiction ne porte pas sur le dépôt
        return True
    return False


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

    Sur les chemins RÉELS (route `POST /api/projects/<slug>/tickets`) le registre est complet et le garde est
    juste. Le seul appelant de `push_local_overlay()` en production est Focus
    (`focus/agents/bouzecode_adapter/tool_wrappers.py::register_focus_tools`) ; dans `src/`
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
