# [desc] Strips heavy Methodology/turn-protocol sections from the system prompt for lean typologies like the manager.
# 
# Strips heavy Methodology/turn-protocol sections from the system prompt for lean typologies like the manager. [/desc]

_LEAN_DROP_SECTIONS = ("# Pourquoi cette forme", "# Discipline Methodology", "# Avant de penser")


def apply_lean_turn_protocol(text: str) -> str:
    """Strip the heavy Methodology/turn-protocol sections from the system prompt.

    Used for lightweight typologies (e.g. the read-only manager) that don't do
    Methodology bookkeeping. Removes the whole-section blocks listed in
    _LEAN_DROP_SECTIONS (a section runs until the next top-level '# ' header).
    """
    lines = text.split("\n")
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("# "):
            skipping = any(line.startswith(h) for h in _LEAN_DROP_SECTIONS)
        if not skipping:
            out.append(line)
    return "\n".join(out)
