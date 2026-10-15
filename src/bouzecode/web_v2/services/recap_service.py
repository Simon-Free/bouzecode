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


def _par_nom(entries) -> list[dict]:
    return sorted(entries, key=lambda e: e["file"].lower())


def _code_ordonne(code: list[dict], changes: list) -> tuple[list[dict], list[dict]]:
    """(code cité dans `changes`, dans leur ordre ; autre code, alpha)."""
    order = _change_order_key(changes)
    rangs = {e["file"]: _rank_of(e["file"], order) for e in code}
    cites = sorted((e for e in code if rangs[e["file"]] is not None), key=lambda e: rangs[e["file"]])
    autres = _par_nom(e for e in code if rangs[e["file"]] is None)
    return cites, autres


def _sections(entries: list[dict], changes: list) -> list[dict]:
    """Code cité dans `changes`, autre code, puis tests (nouveaux d'abord)."""
    cites, autres = _code_ordonne([e for e in entries if not e["is_test"]], changes)
    tests = [e for e in entries if e["is_test"]]
    tests = _par_nom(e for e in tests if e["is_new"]) + _par_nom(e for e in tests if not e["is_new"])
    return (
        [{**e, "section": "changes"} for e in cites]
        + [{**e, "section": "other"} for e in autres]
        + [{**e, "section": "tests"} for e in tests]
    )


def assemble_recap_diffs(recap: dict | None, snapshots: dict) -> list[dict]:
    """Assemble et trie les diffs par fichier selon les règles du module.

    recap None/vide → tri purement alphabétique (fallback sessions historiques)."""
    entries = [_entry(path, snap or {}) for path, snap in (snapshots or {}).items()]
    changes = recap.get("changes") if isinstance(recap, dict) else None
    if not changes:
        return [{**e, "section": "all"} for e in _par_nom(entries)]
    return _sections(entries, changes)


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


def _partie_session(session_path: str, load_json) -> dict:
    data = load_json(session_path) if session_path else None
    recap = data.get("recap") if data else None
    has_recap = isinstance(recap, dict) and bool(recap)
    return {
        "recap": recap if has_recap else None,
        "diffs": session_recap_diffs(recap, data) if has_recap else [],
        "has_recap": has_recap,
    }


def _entree_enfant(agent, load_json) -> dict:
    """Une entrée de `aggregate_children_recaps` : récap + diffs si l'enfant en a un.

    Ce qui vient de la session de l'enfant (récap, diffs) est mémorisé par version de son
    fichier (`builder.memoriser`) : un manager de 100 sous-agents relisait sinon chacune de
    leurs sessions à chaque ouverture de son récap."""
    from ..runtime.context_viewer.builder import memoriser
    session_path = getattr(agent, "session_path", "") or ""
    partie = memoriser("recap_enfant", session_path,
                       lambda: _partie_session(session_path, load_json)) \
        if session_path else _partie_session(session_path, load_json)
    return {
        "agent_id": agent.agent_id,
        "title": (getattr(agent, "prompt", "") or "").strip().split("\n")[0][:90] or agent.agent_id,
        "recap": partie["recap"],
        "diffs": partie["diffs"],
        "has_recap": partie["has_recap"],
        "started_at": getattr(agent, "started_at", "") or "",
    }


def aggregate_children_recaps(agent_id: str, agents, load_json) -> list[dict]:
    """Le travail des sous-agents d'un manager, concaténé sans LLM, pour lire un lot d'un coup.

    Une entrée par enfant (`parent` = le manager), même sans récap, pour que le lien vers sa
    conversation reste présent : {agent_id, title, recap|None, diffs, has_recap,
    started_at}. Ordre de dispatch (started_at). Un step relancé produit deux sessions de
    même titre : on garde la plus récente. Dépendance injectée (`load_json`)
    pour tester sans runner ni store."""
    kids = [_entree_enfant(a, load_json) for a in agents
            if (getattr(a, "parent", "") or "") in (agent_id, f"agent/{agent_id}")]
    kids.sort(key=lambda k: k["started_at"])
    by_title: dict[str, dict] = {}
    for k in kids:
        by_title[k["title"]] = k  # le dernier (plus récent) écrase
    return list(by_title.values())
