# [desc] Sur quel commit ce process a démarré, et HEAD a-t-il bougé depuis : lecture de .git en pur Python (worktree, packed-refs, CRLF), sans lancer git. [/desc]
"""Version de code d'un process bouzecode (TUI, agent, serveur).

Un process garde en mémoire le code chargé à son démarrage. Sous Windows, TUI et agents
(`bouzecode.exe`) tournent des jours : le 21/09, des process du 09/09 servaient encore
des bugs corrigés depuis (session e3b38f9d), et `bouzecode_commit` — relu sur le disque à
chaque run — annonçait le NOUVEAU commit. Ce module fige le commit de démarrage et sait dire,
à coût quasi nul, que HEAD a bougé.

HEAD est lu dans les fichiers de `.git` plutôt qu'avec `git rev-parse` : quelques lectures de
fichiers par prompt au lieu d'un process, et aucune dépendance à `git.exe` dans le PATH (un
process lancé par un raccourci ou un service Windows ne l'a pas toujours)."""
from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parents[2]  # src/bouzecode


def _find_repo_root(start: Path) -> str:
    for p in (start, *start.parents):
        if (p / ".git").exists():
            return str(p)
    return ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _git_dirs(repo_root: str) -> tuple[Path | None, Path | None]:
    """(gitdir, commondir) : `.git` est un dossier (dépôt) ou un fichier « gitdir: … »
    (worktree), dont les refs de branche vivent dans le dépôt principal (commondir)."""
    dot_git = Path(repo_root) / ".git"
    if dot_git.is_dir():
        return dot_git, dot_git
    content = _read(dot_git)
    if not content.startswith("gitdir:"):
        return None, None
    gitdir = Path(content[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = (Path(repo_root) / gitdir).resolve()
    common = _read(gitdir / "commondir")
    if not common:
        return gitdir, gitdir
    common_dir = Path(common)
    if not common_dir.is_absolute():
        common_dir = (gitdir / common_dir).resolve()
    return gitdir, common_dir


def _resolve_ref(ref: str, gitdir: Path, common: Path) -> str:
    for base in (gitdir, common):
        sha = _read(base / ref)
        if sha:
            return sha
    for line in _read(common / "packed-refs").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "^")):
            sha, _, name = line.partition(" ")
            if name.strip() == ref:
                return sha
    return ""


def read_head_sha(repo_root: str) -> str:
    """SHA complet de HEAD de ``repo_root``, "" si introuvable. Ne lève jamais."""
    if not repo_root:
        return ""
    try:
        gitdir, common = _git_dirs(repo_root)
        if gitdir is None:
            return ""
        head = _read(gitdir / "HEAD")
        if head.startswith("ref:"):
            return _resolve_ref(head[len("ref:"):].strip(), gitdir, common)
        return head if len(head) >= 40 else ""
    except (OSError, ValueError):
        return ""


def _packed_object_count(common: Path) -> int:
    """Nombre d'objets des packs, lu dans l'en-tête de chaque `.idx` (fanout[255]) : c'est
    l'estimation dont git dérive la longueur de ses abrégés (`core.abbrev` auto)."""
    total = 0
    for idx in (common / "objects" / "pack").glob("*.idx"):
        with open(idx, "rb") as f:
            head = f.read(1032)
        offset = 1028 if head[:4] == b"\xfftOc" else 1020  # idx v2 (en-tête 8 o) ou v1
        total += int.from_bytes(head[offset:offset + 4], "big")
    return total


def _abbrev_len(object_count: int) -> int:
    """Longueur d'abrégé auto de git : ceil((msb(n) + 1) / 2), au moins 7."""
    return max(7, (object_count.bit_length() + 1) // 2)


def read_head_short(repo_root: str) -> str:
    """Équivalent de `git rev-parse --short HEAD` sans lancer git, "" si illisible.

    Même longueur que git dans le cas courant ; seul écart possible, un abrégé ambigu
    que git rallongerait d'un caractère — sans enjeu pour une estampille de version."""
    sha = read_head_sha(repo_root)
    if len(sha) < 40 or any(c not in "0123456789abcdef" for c in sha):
        return ""
    try:
        _, common = _git_dirs(repo_root)
        return sha[:_abbrev_len(_packed_object_count(common))]
    except (OSError, ValueError):
        return ""


class CodeVersion:
    """Commit de démarrage d'un process et détection de sa dérive."""

    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.boot_sha = read_head_sha(repo_root)
        self._warned = False

    def current_sha(self) -> str:
        return read_head_sha(self.repo_root)

    def state(self) -> dict:
        current = self.current_sha()
        return {"boot_sha": self.boot_sha, "current_head_sha": current,
                "drift": bool(self.boot_sha and current and current != self.boot_sha)}

    def drift_warning(self) -> str | None:
        """Message à afficher quand HEAD a bougé depuis le démarrage — UNE seule fois par
        process, à la première dérive. develop avance plusieurs fois par jour : prévenir à
        chaque nouvel HEAD encombrait le fil de main. `state()` reste exact à chaque appel."""
        if self._warned:
            return None
        st = self.state()
        if not st["drift"]:
            return None
        self._warned = True
        return (f"Le code de bouzecode a changé depuis le démarrage de ce process "
                f"(démarré sur {self.boot_sha[:8]}, dépôt maintenant sur "
                f"{st['current_head_sha'][:8]}) : ce process exécute l'ANCIEN code. "
                f"Relance-le pour avoir les derniers correctifs.")


REPO_ROOT: str = _find_repo_root(_PACKAGE_DIR)
# Figé à l'import : le code que ce process exécute est celui du disque à cet instant.
BOOT = CodeVersion(REPO_ROOT)
