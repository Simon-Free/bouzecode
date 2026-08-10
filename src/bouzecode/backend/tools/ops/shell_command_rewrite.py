# [desc] Pre-execution command rewrites: unwrap a redundant nested PowerShell invocation, spill inline `python -c` code to a temp script. [/desc]
"""Two deterministic rewrites applied to a Bash command before it reaches Popen.

Both turn a guaranteed failure (or a refusal) into a correct execution, so the
agent never burns a turn on them. Measurements: `docs/investigations/refused_tool_attempts.md`.

1. `unwrap_nested_powershell` — the Bash tool ALREADY executes PowerShell. When
   the model additionally wraps its command in `powershell -Command "..."` there
   are two shells: the outer one interpolates `$f`, `$env:X`, `$input` before the
   inner one ever sees them, so `$f='a'; (Get-Content $f)` reaches the child as
   `='a'; (Get-Content )` — a parse error. 45 % of nested calls fail, against
   1.8 % of non-nested ones.

2. `spill_inline_python` — `python -c "<code>"` used to be refused outright. The
   refusal cost a round-trip and taught nothing, so we now do what it asked for:
   write the code to a `temp_*.py` scratch file and run that file instead.
"""
import hashlib
import re

_POWERSHELL_HOST_RE = re.compile(r"^\s*powershell(?:\.exe)?(?=\s)", re.IGNORECASE)

# powershell.exe (PS 5.1) CLI switches. A switch may be abbreviated to any
# unambiguous prefix and introduced by '-' or '/', so we resolve by prefix.
_HOST_FLAGS = (
    "psconsolefile", "version", "nologo", "noexit", "sta", "mta", "noprofile",
    "noninteractive", "inputformat", "outputformat", "windowstyle",
    "encodedcommand", "configurationname", "file", "executionpolicy", "command",
)

# The ONLY switches we accept on a wrapper we are about to delete, because they
# are no-ops once unwrapped: we already launch PowerShell with -NonInteractive
# and capture its output (no logo), and our own launcher loads the profile, so
# dropping -NoProfile only makes MORE names visible to the body, never fewer.
_NO_OP_FLAGS = {"nologo", "noprofile", "noninteractive"}


def _resolve_flag(token: str) -> str | None:
    """Canonical name of a powershell.exe switch, honouring prefix abbreviation."""
    if len(token) < 2 or token[0] not in "-/":
        return None
    body = token[1:].lower()
    matches = [flag for flag in _HOST_FLAGS if flag.startswith(body)]
    if len(matches) == 1:
        return matches[0]
    # '-c'/'-co'/'-com' are ambiguous with -ConfigurationName on paper, but
    # powershell.exe documents and accepts them as -Command.
    return "command" if "command" in matches else None


def read_quoted(text: str, start: int = 0) -> tuple[str, int] | None:
    """Read the PowerShell-quoted string at `text[start]`.

    Returns (content, index just past the closing quote), or None when the token
    is unterminated or carries a backtick escape other than `"` — those we cannot
    unescape losslessly, and a lossy rewrite is worse than no rewrite.
    """
    quote = text[start]
    chars: list[str] = []
    i = start + 1
    while i < len(text):
        char = text[i]
        if char == quote:
            if text[i + 1:i + 2] == quote:  # doubled quote = escaped quote
                chars.append(quote)
                i += 2
                continue
            return "".join(chars), i + 1
        if quote == '"' and char == "`":
            if text[i + 1:i + 2] != '"':
                return None
            chars.append('"')
            i += 2
            continue
        chars.append(char)
        i += 1
    return None


def unwrap_nested_powershell(command: str) -> str | None:
    """Return the body of a redundant `powershell -Command "..."` wrapper, else None.

    DECISION BOUNDARY — we unwrap only when the wrapper is provably a no-op, i.e.
    ALL of the following hold. A wrong unwrap changes behaviour, which is worse
    than the nesting it fixes, so anything else is left strictly alone:
      - the host is `powershell` / `powershell.exe` — NOT `pwsh` (PowerShell 7 is
        a genuinely different runtime) and not a path to some other host;
      - it is the very first token of the command (no `cmd | powershell ...`);
      - the only switches before -Command are -NoLogo/-NoProfile/-NonInteractive.
        `-ExecutionPolicy`, `-File`, `-Version`, `-EncodedCommand`, `-NoExit`,
        `-InputFormat`… all mean the nesting was deliberate → keep it;
      - the body is either a single quoted token that runs to the END of the
        command (a trailing `| Select-Object` means the model composed with the
        CHILD's output, which we must not change), or an unquoted remainder with
        no shell composition character.
    """
    host = _POWERSHELL_HOST_RE.match(command)
    if host is None:
        return None
    index = host.end()
    while True:
        while index < len(command) and command[index].isspace():
            index += 1
        if index >= len(command):
            return None
        token_start = index
        while index < len(command) and not command[index].isspace():
            index += 1
        flag = _resolve_flag(command[token_start:index])
        if flag == "command":
            return _wrapper_body(command[index:])
        if flag not in _NO_OP_FLAGS:
            return None


def _wrapper_body(remainder: str) -> str | None:
    """The command text carried by -Command, or None if it is not safely extractable."""
    remainder = remainder.strip()
    if not remainder:
        return None
    if remainder[0] in "\"'":
        quoted = read_quoted(remainder)
        if quoted is None:
            return None
        body, end = quoted
        if remainder[end:].strip():  # trailing composition on the CHILD's output
            return None
        return body.strip() or None
    if any(char in remainder for char in "|;&"):
        return None
    return remainder


_INLINE_PYTHON_RE = re.compile(
    r"(?:^|\||\;|\&\&|\|\|)\s*(python[23]?|py)\s+-c\s+",
    re.IGNORECASE,
)


def _write_temp_python(code: str) -> tuple[str, str]:
    """Write inline code to a session-scratch `temp_inline_<hash>.py`.

    Returns (logical name, real path). The file is registered in the scratch
    registry, so the agent can Read/Edit/Grep it by its logical `temp_` name and
    the session cleanup disposes of it — same channel as `Write(temp=True)`.
    """
    from .scratch import resolve_scratch_path
    digest = hashlib.sha1(code.encode("utf-8", "replace")).hexdigest()[:8]
    logical = f"temp_inline_{digest}.py"
    real = resolve_scratch_path(logical)
    real.write_text(code, encoding="utf-8")
    return logical, str(real)


def spill_inline_python(command: str) -> tuple[str, list[tuple[str, str]]] | None:
    """Rewrite every `python -c "<code>"` of `command` into `python '<temp_*.py>'`.

    Returns (rewritten command, [(logical name, real path)]), or None when the
    inline code is not a single quoted argument we can extract losslessly — the
    caller then falls back to refusing, as before.
    """
    pieces: list[str] = []
    spilled: list[tuple[str, str]] = []
    position = 0
    while True:
        match = _INLINE_PYTHON_RE.search(command, position)
        if match is None:
            break
        if command[match.end():match.end() + 1] not in ("\"", "'"):
            return None
        quoted = read_quoted(command, match.end())
        if quoted is None:
            return None
        code, end = quoted
        logical, real = _write_temp_python(code)
        pieces.append(command[position:match.end(1)])  # up to and including `python`
        pieces.append(f" '{real}'")
        position = end
        spilled.append((logical, real))
    if not spilled:
        return None
    pieces.append(command[position:])
    return "".join(pieces), spilled


def spill_note(spilled: list[tuple[str, str]]) -> str:
    """The line prepended to the tool result so a failing spill can be inspected."""
    listing = ", ".join(f"{logical} -> {real}" for logical, real in spilled)
    return (
        f"i inline `python -c` was spilled to {listing} and run from there "
        "(inline quoting is fragile). Read or Edit that file to iterate on it, "
        "or write your own temp_*.py next time."
    )
