# [desc] Persistent methodology note exposed to the model via Methodology + Snippet tools. [/desc]
from .state import GCState, ContextState, METHODOLOGY_NOTE
from .notes import inject_notes
from .audit import build_verbatim_audit_note, prepend_verbatim_audit, _summarize_args

__all__ = [
    "GCState", "ContextState", "METHODOLOGY_NOTE",
    "inject_notes",
    "build_verbatim_audit_note", "prepend_verbatim_audit",
]
