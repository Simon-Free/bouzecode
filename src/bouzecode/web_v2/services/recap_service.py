"""Le front reste bête : tout le tri/regroupement des diffs est fait ici, côté serveur.

Ordre produit :
  1. fichiers non-test présents dans recap.changes, dans l'ordre exact de changes ;
  2. fichiers non-test absents de recap.changes (section « Autres modifications »), alpha ;
  3. fichiers de test (test_*.py) en fin, is_test=true : nouveaux tests d'abord, puis corrigés.

Fallback : recap absent → tous les diffs triés alphabétiquement (l'appelant renvoie recap=null).
"""
from __future__ import annotations

import difflib
import os
import re

from .sessions.recap_diffs import build_recap_payload


def _is_test_file(path: str) -> bool:
    base = os.path.basename(path)
    return base.startswith("test_") and base.endswith(".py")


# …/worktrees/<repo>/<ticket>/<relpath> → <relpath>. Le worktree est jetable ; afficher son
# chemin absolu Windows dans chaque en-tête de diff est illisible. On retombe sur le chemin
# relatif au dépôt (qui matche aussi recap.changes[].file → meilleur tri).
_WORKTREE_RE = re.compile(r"[\\/]worktrees[\\/][^\\/]+[\\/][^\\/]+[\\/](.+)$")


def _display_path(path: str) -> str:
    """Chemin lisible : retire le préfixe worktree jetable → relatif au dépôt, slashes avant.
    Un chemin déjà relatif (ou hors worktree) est renvoyé tel quel (slashes normalisés)."""
    m = _WORKTREE_RE.search(path)
    return (m.group(1) if m else path).replace("\\", "/")


def _build_patch(path: str, before: str, after: str) -> tuple[str, int, int]:
    """Diff unifié brut (str) + compteurs +n/-n, sans HTML."""
    lines = list(difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
        n=3,
    ))
    patch = "\n".join(lines)
    additions = sum(
        1 for l in lines if l.startswith("+") and not l.startswith("+++")
    )
    deletions = sum(
        1 for l in lines if l.startswith("-") and not l.startswith("---")
    )
    return patch, additions, deletions


def _entry(path: str, snapshot: dict) -> dict:
    before = snapshot.get("before") or ""
    after = snapshot.get("after") or ""
    display = _display_path(path)   # relatif au dépôt : en-têtes de diff lisibles + tri exact
    patch, additions, deletions = _build_patch(display, before, after)
    return {
        "file": display,
        "patch": patch,
        # `original`/`modified` = contenus COMPLETS avant/après (pas le patch unifié).
        # Alimentent directement Monaco createDiffEditor côté front (diff fiable, pas de
        # reconstruction depuis le patch). Vides ("") pour un fichier neuf/supprimé.
        "original": before,
        "modified": after,
        "is_test": _is_test_file(display),
        "is_new": bool(snapshot.get("is_new")),
        "additions": additions,
        "deletions": deletions,
    }


def _change_order_key(changes: list) -> dict[str, int]:
    """path/basename du fichier dans recap.changes → rang. Match exact prioritaire,
    basename en repli pour tolérer les chemins relatifs divergents."""
    order: dict[str, int] = {}
    for rank, change in enumerate(changes or []):
        if not isinstance(change, dict):
            continue
        file = change.get("file")
        if not isinstance(file, str) or not file:
            continue
        order.setdefault(file, rank)
        order.setdefault(os.path.basename(file), rank)
    return order


def _rank_of(path: str, order: dict[str, int]) -> int | None:
    if path in order:
        return order[path]
    base = os.path.basename(path)
    return order.get(base)


def assemble_recap_diffs(recap: dict | None, snapshots: dict) -> list[dict]:
    """Assemble et trie les diffs par fichier selon les règles ci-dessus.

    recap None/vide → tri purement alphabétique (fallback sessions historiques)."""
    entries = [_entry(path, snap or {}) for path, snap in (snapshots or {}).items()]

    changes = recap.get("changes") if isinstance(recap, dict) else None
    if not changes:
        ordered = sorted(entries, key=lambda e: e["file"].lower())
        return [{**e, "section": "all"} for e in ordered]

    order = _change_order_key(changes)

    tests = [e for e in entries if e["is_test"]]
    code = [e for e in entries if not e["is_test"]]

    in_changes = [e for e in code if _rank_of(e["file"], order) is not None]
    in_changes.sort(key=lambda e: _rank_of(e["file"], order))
    others = sorted(
        (e for e in code if _rank_of(e["file"], order) is None),
        key=lambda e: e["file"].lower(),
    )

    new_tests = sorted((e for e in tests if e["is_new"]), key=lambda e: e["file"].lower())
    fixed_tests = sorted((e for e in tests if not e["is_new"]), key=lambda e: e["file"].lower())

    return (
        [{**e, "section": "changes"} for e in in_changes]
        + [{**e, "section": "other"} for e in others]
        + [{**e, "section": "tests"} for e in (*new_tests, *fixed_tests)]
    )


def session_recap_diffs(recap: dict | None, data: dict) -> list[dict]:
    """Assemble les diffs sectionnés d'UNE session en réconciliant les deux sources.

    Deux sources de diff coexistent dans un session.json :
      - `file_snapshots` (before/after par fichier) → difflib via assemble_recap_diffs ;
      - `diff` (git diff TEXTE), persisté par integration._persist_coder_diff APRÈS la
        mort du codeur — la source PÉRENNE en flux headless web_v2, où file_snapshots
        n'est pas peuplé (le state module global des snapshots ne survit pas au process).

    Ordre de préférence : file_snapshots (riche, historique) → sinon git diff text →
    sinon fallback vide (comportement historique préservé). Ce fallback sur `diff` corrige
    le bug « récap Manager/Python sans diffs » : la route recap ne lisait que file_snapshots
    (vide) et ignorait le champ `diff` pourtant écrit pour elle."""
    snapshots = data.get("file_snapshots") or {}
    if snapshots:
        return assemble_recap_diffs(recap, snapshots)
    diff_text = data.get("diff") or ""
    if diff_text.strip():
        return build_recap_payload(recap, diff_text)["diffs"]
    return assemble_recap_diffs(recap, {})


def aggregate_children_recaps(agent_id: str, agents, load_json, find_verdict=None) -> list[dict]:
    """Concatène (SANS LLM) le travail des sous-agents d'un manager pour présenter tout
    un lot d'un seul coup. `agents` = itérable d'objets Agent (attributs
    agent_id/parent/session_path/prompt/started_at) ; `load_json(path)->dict|None` ;
    `find_verdict(agent)->"OK"|"KO"|None` (optionnel, injecté → testable).

    Retourne, dans l'ordre de dispatch (started_at), UNE entrée par enfant du manager
    (parent match), MÊME sans récap structuré — afin que le lien vers la conversation de
    l'enfant reste toujours présent (minimum demandé). Chaque entrée :
    {agent_id, title, recap(dict|None), diffs(list), has_recap(bool), verdict(str|None),
    started_at}. Un enfant AVEC récap porte recap+diffs (session_recap_diffs : file_snapshots
    OU git diff text, mêmes tri/sections que la vue codeur) et has_recap=True ; un enfant
    SANS récap → recap=None, diffs=[], has_recap=False (le front n'affiche alors qu'un
    lien vers sa conversation). Deps injectées → testable sans runner/store.

    POLITIQUE MULTI-RÉCAPS (déterministe) : un même step relancé (rework KO→OK) produit
    deux sessions de MÊME TITRE (1re ligne du prompt). On DÉDUPLIQUE par titre →
    l'entrée la plus RÉCENTE gagne (started_at max écrase l'ancien même titre). Les titres
    distincts restent une entrée chacun. L'ordre final est l'ordre de dispatch (started_at
    asc) des entrées retenues → narration du lot cohérente."""
    kids = []
    for a in agents:
        parent = getattr(a, "parent", "") or ""
        if parent not in (agent_id, f"agent/{agent_id}"):
            continue
        session_path = getattr(a, "session_path", "") or ""
        data = load_json(session_path) if session_path else None
        recap = data.get("recap") if data else None
        has_recap = isinstance(recap, dict) and bool(recap)
        kids.append({
            "agent_id": a.agent_id,
            "title": (getattr(a, "prompt", "") or "").strip().split("\n")[0][:90] or a.agent_id,
            "recap": recap if has_recap else None,
            "diffs": session_recap_diffs(recap, data) if has_recap else [],
            "has_recap": has_recap,
            "verdict": (find_verdict(a) if find_verdict else None),
            "started_at": getattr(a, "started_at", "") or "",
        })
    kids.sort(key=lambda k: k["started_at"])   # ordre de dispatch = narration du lot
    # Dédup par titre : le plus récent (dernier dans l'ordre started_at asc) gagne.
    by_title: dict[str, dict] = {}
    for k in kids:
        by_title[k["title"]] = k   # écrasement → dernier started_at conservé
    return list(by_title.values())
