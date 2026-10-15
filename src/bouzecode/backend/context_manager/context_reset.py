# [desc] ResetContext : archive la note Methodology dans un fichier persistant lié à la session et la repart des seuls blocs ## User / ## Harnais, du résumé du modèle et d'un renvoi vers l'archive. [/desc]
"""ResetContext — le modèle nettoie lui-même son contexte quand la tâche change.

Demande du 2026-10-07 : quand le dernier message utilisateur ouvre une tâche sans rapport avec
la note, le modèle appelle ``ResetContext(reason, summary)``. La note ENTIÈRE est écrite telle
quelle dans un fichier à côté du fichier de session (``<session>.context_<n>.md``) : il survit
à la fin de session et à ``/resume``, contrairement au scratch. La nouvelle note garde :

- les blocs ``## User`` (la mission ; regex stricte : un tampon d'ajout ``### T<n>`` clôt le
  bloc, sinon le travail archivé y retomberait ; un ajout sans tampon, hors boucle au tour 0,
  reste collé au bloc qui le précède) ;
- les blocs ``## Harnais @…`` (contexte_fige : contrat de worktree, jamais perdu) ;
- un bloc ``## Contexte archivé`` : chemin, raison, résumé, consigne de relecture.

Chaque archive est la note d'avant, qui portait elle-même le bloc ``## Contexte archivé`` du
reset précédent : les archives sont donc chaînées.

Cache : la note réécrite n'est plus un prolongement du préfixe envoyé — elle repart en entier
une fois (écrite en cache), puis redevient append-only. L'instantané de cache est remis à zéro
comme après une compaction, et la timeline journalise un remplacement complet.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .contexte_fige import ENTETE_NOTE_DE_CONTEXTE
from .methodology import _APPEND_LOCK, _record_timeline
from .state import ContextState, METHODOLOGY_NOTE, resolve_context_state

ARCHIVE_HEADER = "## Contexte archivé"

# Blocs gardés : ## User et ## Harnais @…, chacun jusqu'au prochain titre ``## `` ou au prochain
# tampon de tour ``### T<n>`` (ce qui suit un message utilisateur est du travail, archivé).
_KEPT_BLOCK_RE = re.compile(
    r"(^(?:## User(?:\s+@[^\n]*)?|" + re.escape(ENTETE_NOTE_DE_CONTEXTE) + r"[^\n]*)\n.*?)"
    r"(?=\n## |\n### T\d+|\Z)",
    re.DOTALL | re.MULTILINE)


def kept_blocks(note: str) -> str:
    """Les blocs ``## User`` et ``## Harnais @…`` de la note, dans leur ordre d'origine."""
    return "\n\n".join(m.group(1).rstrip() for m in _KEPT_BLOCK_RE.finditer(note))


def session_file_of(config: dict) -> Path:
    """Le fichier de session de cet agent : ``_session_file`` (agent web, --session-file),
    sinon ``_session_path`` (repl), sinon celui que la prochaine sauvegarde utilisera."""
    chemin = config.get("_session_file") or config.get("_session_path")
    if chemin:
        return Path(chemin)
    from ..commands.session.session import _get_or_create_session_path
    return _get_or_create_session_path(config)


def next_archive_path(config: dict) -> Path:
    """``<session sans .json>.context_<n>.md`` à côté de la session, premier n libre."""
    session = session_file_of(config)
    session.parent.mkdir(parents=True, exist_ok=True)
    racine = session.name[:-len(".json")] if session.name.endswith(".json") else session.name
    numero = 1
    while (session.parent / f"{racine}.context_{numero}.md").exists():
        numero += 1
    return session.parent / f"{racine}.context_{numero}.md"


def _archive_block(archive: Path, reason: str, summary: str) -> str:
    # Un titre ``## `` dans le résumé ouvrirait un autre bloc de la note : rétrogradé en ``### ``.
    resume = "\n".join("#" + ligne if ligne.startswith("## ") else ligne
                       for ligne in summary.split("\n"))
    lignes = [f"{ARCHIVE_HEADER} @{time.strftime('%Y-%m-%d %H:%M:%S')}",
              f"Raison : {reason}",
              f"Ancienne note archivée dans : {archive}"]
    if resume:
        lignes.append(f"Acquis du contexte précédent : {resume}")
    lignes.append("Relis-la avec Read(file_path=...) si un fait de l'ancienne tâche redevient "
                  "utile ; elle renvoie elle-même aux archives plus anciennes.")
    return "\n".join(lignes)


def reset_context_tool(params: dict, config: dict) -> str:
    context_state: ContextState | None = resolve_context_state(config)
    if context_state is None:
        return "Error: no context state available"
    reason = (params.get("reason") or "").strip()
    if not reason:
        return ("Error: `reason` is required (why the current task differs from the context "
                "in the note). Nothing was archived.")
    summary = (params.get("summary") or "").strip()

    with _APPEND_LOCK:
        ancienne = context_state.notes.get(METHODOLOGY_NOTE, "")
        archive = next_archive_path(config)
        archive.write_text(ancienne, encoding="utf-8")
        gardes = kept_blocks(ancienne)
        bloc = _archive_block(archive, reason, summary)
        context_state.notes[METHODOLOGY_NOTE] = f"{gardes}\n\n{bloc}" if gardes else bloc
        context_state._methodology_cache_snapshot = None
        context_state.allegements = getattr(context_state, "allegements", 0) + 1
    _record_timeline(config, context_state)
    return (f"context reset: previous note ({len(ancienne)} chars) archived to {archive}; "
            f"note now {len(context_state.notes[METHODOLOGY_NOTE])} chars "
            "(## User and ## Harnais blocks kept). Re-read the archive with Read if needed.")


RESET_CONTEXT_SCHEMA = {
    "name": "ResetContext",
    "description": (
        "Archive ta note de travail quand le dernier message utilisateur ouvre une tâche sans "
        "rapport avec elle (autre projet, autre bug, tâche précédente close). La note entière "
        "est écrite dans un fichier .md à côté de la session ; la nouvelle note garde les "
        "blocs « ## User », les blocs « ## Harnais @… », ton `summary` et le chemin de "
        "l'archive, à relire avec Read si besoin. Place-le en premier dans le lot, avant "
        "Methodology. Une suite ou un raffinement de la même tâche n'en relève pas."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string",
                       "description": "En quoi la nouvelle demande diffère du contexte de la note."},
            "summary": {"type": "string",
                        "description": "Optionnel : les acquis de l'ancienne tâche encore utiles."},
        },
        "required": ["reason"],
    },
}


def register() -> None:
    from ..core.tool_registry import ToolDef, register_tool
    register_tool(ToolDef(name="ResetContext", schema=RESET_CONTEXT_SCHEMA,
                          func=reset_context_tool, read_only=False, concurrent_safe=False))
