"""Index en mémoire des définitions d'un dépôt, invalidé fichier par fichier.

Chaque appel relit la liste des fichiers (`git ls-files`, donc .gitignore respecté) et
leur (mtime, taille) : seuls les fichiers modifiés sont ré-analysés. Rien n'est écrit
sur disque, et l'index ne peut pas être périmé après un Edit.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path

from .extract import CODE_EXTS, Def, FileInfo, extract

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "dist", "build", "site-packages", ".idea", ".vscode"}
VENDOR_DIRS = {"vendor", "vendors", "third_party", "thirdparty", "bower_components"}
MAX_FILES = 20000
MAX_BYTES = 1_000_000
AMBIGUOUS = 3  # au-delà de N homonymes, une référence par nom seul n'est pas résolue
# Méthodes des types de base : `d.get(...)` ne désigne pas la fonction `get` du dépôt.
COMMON_ATTRS = {n for t in (dict, list, str, set, bytes, int, object, Path) for n in dir(t)} | set(
    "append add get set run start stop close open read write send then catch push map filter "
    "forEach reduce call apply bind length find includes slice splice test exec match log error "
    "warn info debug emit on off once next value done resolve reject all".split())


def repo_root(start: Path) -> Path:
    """Plus proche ancêtre portant un `.git` (dossier ou fichier), sinon `start`."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _git_files(root: Path) -> list[str] | None:
    git = shutil.which("git")
    if not git or not (root / ".git").exists():
        return None
    try:
        out = subprocess.run([git, "-C", str(root), "ls-files", "-z", "-co", "--exclude-standard"],
                             capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in out.split("\0") if p]


def _ignore_patterns(root: Path) -> list[str]:
    try:
        text = (root / ".gitignore").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line.strip().rstrip("/") for line in text.splitlines()
            if line.strip() and not line.startswith(("#", "!"))]


def _ignored(name: str, patterns: list[str]) -> bool:
    return any(fnmatch(name, p) for p in patterns)


def _walk_files(root: Path) -> list[str]:
    """Hors dépôt git : parcours du disque, dossiers cachés et `.gitignore` racine exclus."""
    patterns = _ignore_patterns(root)
    found: list[str] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS and not d.startswith(".") and not _ignored(d, patterns)]
        rel_dir = Path(folder).relative_to(root)
        found += [(rel_dir / f).as_posix() for f in files if not _ignored(f, patterns)]
        if len(found) > MAX_FILES * 5:
            break
    return found


def code_files(root: Path) -> list[str]:
    listed = _git_files(root)
    if listed is None:
        listed = _walk_files(root)
    keep = [p for p in listed if Path(p).suffix.lower() in CODE_EXTS
            and not (SKIP_DIRS | VENDOR_DIRS).intersection(Path(p).parts[:-1])
            and ".min." not in Path(p).name]
    return sorted(keep)[:MAX_FILES]


def _local(info: FileInfo, name: str, attr: bool, owner: str) -> list[Def]:
    """Même fichier : une méthode de la même classe (par attribut), ou une définition de
    haut niveau (par nom nu)."""
    return [d for d in info.defs if d.name == name
            and (d.parent == owner if d.kind == "method" else not attr)]


def _family(rel: str) -> str:
    return "py" if rel.endswith(".py") else "js"


def is_test_path(rel: str) -> bool:
    parts = rel.lower().split("/")
    name = parts[-1]
    return (any(p in ("test", "tests", "__tests__", "spec") for p in parts[:-1])
            or name.startswith("test_") or name == "conftest.py"
            or name.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts")))


class RepoIndex:
    def __init__(self, root: Path):
        self.root = root
        self.files: dict[str, FileInfo] = {}
        self._stamps: dict[str, tuple[int, int]] = {}
        self.defs_by_name: dict[str, list[Def]] = {}
        self.refs_by_name: dict[str, list[Def]] = {}
        self.modules: dict[str, str] = {}
        self._suffix_cache: dict[str, str | None] = {}

    def refresh(self) -> None:
        """Ré-analyse les fichiers dont (mtime, taille) a changé ; retire les disparus."""
        changed = False
        seen = set()
        for rel in code_files(self.root):
            seen.add(rel)
            changed |= self._refresh_file(rel)
        for gone in set(self.files) - seen:
            self.files.pop(gone, None)
            self._stamps.pop(gone, None)
            changed = True
        if changed or not self.defs_by_name:
            self._rebuild_maps()

    def _refresh_file(self, rel: str) -> bool:
        path = self.root / rel
        try:
            st = path.stat()
        except OSError:
            return False
        stamp = (st.st_mtime_ns, st.st_size)
        if self._stamps.get(rel) == stamp:
            return False
        self._stamps[rel] = stamp
        if st.st_size > MAX_BYTES:
            self.files[rel] = FileInfo([])
            return True
        text = path.read_text(encoding="utf-8", errors="replace")
        self.files[rel] = extract(rel, text)
        return True

    def _rebuild_maps(self) -> None:
        defs, refs, modules = defaultdict(list), defaultdict(list), {}
        for rel, info in self.files.items():
            for d in info.defs:
                defs[d.name].append(d)
                for name in {n.lstrip(".") for n in d.refs}:
                    refs[name].append(d)
            if info.module_refs:
                module = Def("(module)", "(module level)", "module", rel, 0, 0,
                             refs=info.module_refs)
                for name in {n.lstrip(".") for n in info.module_refs}:
                    refs[name].append(module)
            if rel.endswith(".py"):
                dotted = rel[:-3].replace("/", ".").removesuffix(".__init__")
                modules[dotted] = rel
        self.defs_by_name, self.refs_by_name, self.modules = dict(defs), dict(refs), modules
        self._suffix_cache = {}

    # ------------------------------------------------------------ résolution

    def module_file(self, module: str) -> str | None:
        """Fichier d'un module importé : nom pointé exact, sinon suffixe unique (src/…)."""
        if module in self.modules:
            return self.modules[module]
        if module not in self._suffix_cache:
            hits = [rel for dotted, rel in self.modules.items() if dotted.endswith("." + module)]
            self._suffix_cache[module] = hits[0] if len(hits) == 1 else None
        return self._suffix_cache[module]

    def resolve(self, user: Def, ref: str) -> list[Def]:
        """Les définitions que `ref`, référencé depuis `user`, désigne : même fichier
        (même classe pour une méthode), puis import, puis nom seul s'il n'est pas ambigu.
        `.nom` (vu seulement comme attribut) ne passe pas par les imports, et un nom de
        méthode des types de base n'est pas résolu hors du fichier."""
        info = self.files.get(user.file)
        if info is None:
            return []
        name, attr = ref.lstrip("."), ref.startswith(".")
        local = _local(info, name, attr, user.parent or user.name)
        if local:
            return local
        if attr:
            return [] if name in COMMON_ATTRS else self._by_name(user, name, attr)
        return self._imported(info, name, depth=0) or self._by_name(user, name, attr)

    def _by_name(self, user: Def, name: str, attr: bool) -> list[Def]:
        """Nom seul, même langage ; une méthode ne se désigne que par attribut, et le code
        ne dépend jamais d'un fichier de test par un simple nom."""
        family, from_test = _family(user.file), is_test_path(user.file)
        candidates = [d for d in self.defs_by_name.get(name, [])
                      if _family(d.file) == family and (attr or d.kind != "method")
                      and (from_test or not is_test_path(d.file))]
        return candidates if len(candidates) <= AMBIGUOUS else []

    def _imported(self, info: FileInfo, name: str, depth: int) -> list[Def]:
        module, original = info.imports.get(name, ("", ""))
        target = self.module_file(module) if module else None
        if target is None or not original:
            return []
        found = [d for d in self.files[target].defs if d.name == original and d.kind != "method"]
        if found or depth >= 2:
            return found
        return self._imported(self.files[target], original, depth + 1)  # ré-export

    def callers(self, target: Def) -> list[tuple[Def, int]]:
        """(utilisateur, ligne) : le code d'abord, les tests ensuite."""
        found = []
        for user in self.refs_by_name.get(target.name, []):
            ref = next((r for r in (target.name, "." + target.name)
                        if r in user.refs and target in self.resolve(user, r)), None)
            if ref and user is not target:
                found.append((user, user.refs[ref]))
        return sorted(found, key=lambda ul: (is_test_path(ul[0].file), ul[0].file, ul[1]))

    def callees(self, user: Def) -> list[tuple[Def, int]]:
        out, seen = [], set()
        for name, line in sorted(user.refs.items(), key=lambda kv: kv[1]):
            for d in self.resolve(user, name):
                if d is not user and id(d) not in seen:
                    seen.add(id(d))
                    out.append((d, line))
        return out


_INDEXES: dict[str, RepoIndex] = {}
_LOCK = threading.Lock()


def get_index(root: Path) -> RepoIndex:
    """L'index à jour de `root` (créé au premier appel, rafraîchi à chaque appel)."""
    with _LOCK:
        index = _INDEXES.setdefault(str(root), RepoIndex(root))
        index.refresh()
        return index
