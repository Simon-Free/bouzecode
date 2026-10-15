# [desc] Instantané du seed du bac à sable : empreinte, attente du repos, archive tar.zst, restauration avec réécriture du chemin du HOME (fichiers texte + SQLite). [/desc]
"""Instantané du seed du bac à sable — appelé par `run_sandbox.sh start --snapshot`.

    snapshot.py fingerprint                 # empreinte des fichiers qui font le seed
    snapshot.py archive-path                # chemin de l'archive pour l'empreinte courante
    snapshot.py wait-idle URL [secondes]    # attend qu'aucun agent ne travaille
    snapshot.py create HOME [SECS] [EMPREINTE]  # archive HOME (sans .run/)
    snapshot.py restore HOME [ARCHIVE]      # vide HOME, extrait l'archive, réécrit les chemins

Pourquoi une réécriture : le HOME d'origine apparaît en chemin ABSOLU dans les sessions,
`projects.json`, les fichiers `.git` / `gitdir` des worktrees et les bases SQLite (tickets,
micros). L'archive mémorise son HOME d'origine (`.snapshot.json`) ; à la restauration dans un
autre HOME, chaque occurrence est remplacée — en octets dans les fichiers texte, par
`UPDATE … SET col = replace(col, ancien, nouveau)` sur chaque colonne TEXT des bases SQLite.
Les objets git (compressés) ne portent pas le HOME et ne sont pas touchés.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get("BZ_SNAPSHOT_DIR", Path.home() / ".cache" / "bz-sandbox"))
META = ".snapshot.json"

#  Ce qui FAIT le contenu du seed. Une modification de l'un de ces fichiers rend l'archive
#  périmée : le script de seed et le faux LLM (ce qui est joué), le lanceur (l'environnement),
#  et les modules qui écrivent le FORMAT des données sur disque (session d'agent, état IPC du
#  runner, index de sessions, schémas SQLite des tickets / tâches / décisions).
EMPREINTE = [
    "tests/sandbox/seed.py",
    "tests/sandbox/mock_llm_server.py",
    "tests/sandbox/run_sandbox.sh",
    "tests/sandbox/snapshot.py",
    "src/bouzecode/backend/commands/session/session.py",
    "src/bouzecode/web_v2/runtime/runner/agent_fiche.py",
    "src/bouzecode/web_v2/runtime/ipc.py",
    "src/bouzecode/web_v2/services/sessions/store.py",
    "src/bouzecode/web_v2/services/work/_persistence.py",
    "src/bouzecode/web_v2/services/work/_store_connection.py",
    "src/bouzecode/web_v2/services/work/micros.py",
    "src/bouzecode/web_v2/services/work/tasks.py",
    "src/bouzecode/web_v2/services/work/decisions.py",
]

#  États d'un nœud de /api/agents/tree qui veulent dire « un agent travaille encore ».
ACTIFS = {"running", "starting", "provisioning", "waiting_children"}


#  BZ_SNAPSHOT_LOOSE=1 : empreinte réduite aux fichiers du bac à sable. Utile quand le code
#  applicatif bouge sans cesse (refacto en cours) et qu'un seed légèrement ancien suffit ;
#  risque assumé : un changement de FORMAT sur disque passerait inaperçu.
SANDBOX_SEULEMENT = 4


def fingerprint() -> str:
    h = hashlib.sha256()
    fichiers = EMPREINTE[:SANDBOX_SEULEMENT] if os.environ.get("BZ_SNAPSHOT_LOOSE") == "1" else EMPREINTE
    for rel in fichiers:
        p = REPO / rel
        h.update(rel.encode())
        #  Normalise les fins de ligne : une conversion CRLF↔LF ne change pas le seed.
        h.update(p.read_bytes().replace(b"\r\n", b"\n") if p.exists() else b"<absent>")
    return h.hexdigest()[:16]


def archive_path(fp: str | None = None) -> Path:
    return CACHE / f"seed-{fp or fingerprint()}.tar.zst"


def _tree(url: str) -> list[dict]:
    with urllib.request.urlopen(f"{url}/api/agents/tree?offset=0&limit=500", timeout=30) as r:
        data = json.load(r)
    return data.get("nodes", data) if isinstance(data, dict) else data


def wait_idle(url: str, timeout: float = 240) -> None:
    """Attend qu'aucun agent ne travaille (ni phase de démarrage) : l'instantané fige un
    parc AU REPOS, sinon la restauration montrerait un agent « en cours » sans processus."""
    fin = time.time() + timeout
    actifs: list[str] = []
    while time.time() < fin:
        actifs = [n.get("key", "?") for n in _tree(url)
                  if n.get("state") in ACTIFS or n.get("phase")]
        if not actifs:
            print("[snapshot] parc au repos")
            return
        time.sleep(1.5)
    sys.exit(f"[snapshot] parc jamais au repos après {timeout:.0f} s : {actifs}")


def create(home: Path, seed_seconds: float | None = None, fp: str | None = None) -> Path:
    """Archive `home` sous l'empreinte `fp` — celle calculée AVANT le seed. Si le code a bougé
    pendant le seed, l'archive porte l'ancienne empreinte et le prochain run re-seedera :
    on préfère un seed de trop à un instantané étiqueté avec un code qui ne l'a pas produit."""
    home = home.resolve()
    fp = fp or fingerprint()
    (home / META).write_text(json.dumps({
        "origine": str(home), "empreinte": fp,
        "cree_le": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed_secondes": seed_seconds,
    }), encoding="utf-8")
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = archive_path(fp)
    tmp = dest.with_suffix(".tmp")
    tar = subprocess.Popen(["tar", "-C", str(home), "--exclude=./.run", "-cf", "-", "."],
                           stdout=subprocess.PIPE)
    subprocess.run(["zstd", "-q", "-T0", "-f", "-o", str(tmp)], stdin=tar.stdout, check=True)
    if tar.wait() != 0:
        sys.exit("[snapshot] tar a échoué")
    tmp.replace(dest)
    #  Une seule archive vivante : les anciennes empreintes ne resserviront jamais.
    for old in CACHE.glob("seed-*.tar.zst"):
        if old != dest:
            old.unlink()
    print(f"[snapshot] archive : {dest} ({dest.stat().st_size // 1024} Ko)")
    return dest


def _rewrite_sqlite(path: Path, old: str, new: str) -> int:
    n = 0
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            for _cid, col, typ, *_ in con.execute(f'PRAGMA table_info("{t}")'):
                if typ and "INT" in typ.upper() or (typ and "REAL" in typ.upper()):
                    continue
                cur = con.execute(
                    f'UPDATE "{t}" SET "{col}" = replace("{col}", ?, ?) '
                    f'WHERE typeof("{col}") = \'text\' AND instr("{col}", ?) > 0',
                    (old, new, old))
                n += cur.rowcount
        con.commit()
    finally:
        con.close()
    return n


def _rewrite(home: Path, old: str, new: str) -> tuple[int, int]:
    ob, nb = old.encode(), new.encode()
    fichiers = lignes = 0
    for p in home.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        if "/.git/objects/" in str(p):
            continue
        #  Journaux SQLite : jamais réécrits en octets (sommes de contrôle) ; ouvrir la base
        #  principale avec sqlite3 les rejoue avant la réécriture de ses colonnes.
        if p.name.endswith(("-wal", "-shm", "-journal")):
            continue
        with p.open("rb") as f:
            head = f.read(16)
        if head.startswith(b"SQLite format 3"):
            lignes += _rewrite_sqlite(p, old, new)
            continue
        data = p.read_bytes()
        if ob in data:
            p.write_bytes(data.replace(ob, nb))
            fichiers += 1
    return fichiers, lignes


def restore(home: Path, src: Path | None = None) -> None:
    src = src or archive_path()
    if not src.exists():
        sys.exit(f"[snapshot] aucune archive pour l'empreinte courante ({src})")
    t0 = time.time()
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    home = home.resolve()
    unz = subprocess.Popen(["zstd", "-q", "-dc", str(src)], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-C", str(home), "-xf", "-"], stdin=unz.stdout, check=True)
    unz.wait()
    meta = json.loads((home / META).read_text(encoding="utf-8"))
    old = meta["origine"]
    if old != str(home):
        f, l = _rewrite(home, old, str(home))
        print(f"[snapshot] chemins réécrits {old} → {home} : {f} fichiers, {l} lignes SQLite")
    print(f"[snapshot] restauré en {time.time() - t0:.1f} s depuis {src.name}")


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "fingerprint":
        print(fingerprint())
    elif cmd == "archive-path":
        print(archive_path())
    elif cmd == "wait-idle":
        wait_idle(argv[2], float(argv[3]) if len(argv) > 3 else 240)
    elif cmd == "create":
        create(Path(argv[2]), float(argv[3]) if len(argv) > 3 else None,
               argv[4] if len(argv) > 4 else None)
    elif cmd == "restore":
        restore(Path(argv[2]), Path(argv[3]) if len(argv) > 3 else None)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
