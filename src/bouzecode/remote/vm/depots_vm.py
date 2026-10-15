"""Cote VM (stdlib seule) : depots en cache clones depuis GitLab + un worktree par execution.

Source `remote` : clone `--bare` du depot dans un cache PERSISTANT a nom fixe par depot
(`<cache>/<hote_chemin>.git`, assume comme les caches uv/navigateur), `git fetch` aux executions
suivantes, sous verrou fcntl (deux executions concurrentes ne se marchent pas dessus). Les commits
locaux absents du remote arrivent par le bundle incremental, recus sous `refs/bz/<run>/<slug>`.
Puis `git worktree add -B <branche_travail> <travail>/<slug> <sha>` : le worktree part du SHA local
exact. En fin d'execution : `worktree remove`, branche et ref supprimees ; le cache reste.
Source `bundle_complet` : clone du bundle comme avant (depot sans remote joignable).

Authentification GitLab : jeton en option Rundeck secrete (RD_OPTION_GIT_TOKEN), servi a git par
un GIT_ASKPASS qui ne contient QUE le nom de la variable ; `credential.helper` vide pour qu'aucun
assistant du noeud ne l'enregistre. L'URL ne porte jamais d'identifiants.
"""
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

CACHE_DEPOTS_DEFAUT = "/data/projects/bouzecode_remote/depots"


def cache_depots() -> Path:
    """Racine des clones en cache ; BZ_CACHE_DEPOTS la deplace (tests : VM jouee en local)."""
    return Path(os.environ.get("BZ_CACHE_DEPOTS", CACHE_DEPOTS_DEFAUT))
ASKPASS = '#!/bin/sh\ncase "$1" in Username*) echo "$RD_OPTION_GIT_USER" ;; *) echo "$RD_OPTION_GIT_TOKEN" ;; esac\n'


def _git(*arguments: str, cwd=None, env=None) -> str:
    sortie = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True, env=env)
    if sortie.returncode != 0:  # le message de git, pas un CalledProcessError muet
        raise RuntimeError(f"git {arguments[0] if arguments[0] != '-c' else arguments[2]} : {sortie.stderr.strip()[-500:]}")
    return sortie.stdout.strip()


def env_authentifie(travail: Path) -> tuple[dict, tuple]:
    """(env, options git) : askpass si un jeton est fourni, sinon rien (depots publics, tests)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if not os.environ.get("RD_OPTION_GIT_TOKEN"):
        return env, ()
    script = travail / "askpass.sh"
    script.write_text(ASKPASS)
    script.chmod(0o700)
    return dict(env, GIT_ASKPASS=str(script)), ("-c", "credential.helper=")


@contextmanager
def verrou(cache: Path):
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache.parent / f"{cache.name}.lock", "w") as fichier:
        if os.name == "nt":  # VM jouee en local par les tests
            import msvcrt
            msvcrt.locking(fichier.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fichier, fcntl.LOCK_EX)
        yield


def mettre_a_jour_cache(projet: dict, travail: Path) -> tuple[Path, str]:
    """Clone ou fetch le cache du depot ; rend (cache, "clone" | "fetch")."""
    cache = cache_depots() / projet["cache"]
    env, options = env_authentifie(travail)
    if (cache / "HEAD").is_file():
        _git(*options, "fetch", "--quiet", "--prune", "origin", cwd=cache, env=env)
        return cache, "fetch"
    _git(*options, "clone", "--quiet", "--bare", projet["url"], str(cache), env=env)
    _git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*", cwd=cache)
    _git(*options, "fetch", "--quiet", "origin", cwd=cache, env=env)
    return cache, "clone"


def worktree_depuis_cache(dossier_paquet: Path, projet: dict, travail: Path, run_id: str) -> tuple[Path, dict]:
    destination = travail / projet["slug"]
    with verrou(cache_depots() / projet["cache"]):
        cache, geste = mettre_a_jour_cache(projet, travail)
        ref_locale = f"refs/bz/{run_id}/{projet['slug']}"
        if projet.get("bundle"):
            _git("fetch", "--quiet", str((dossier_paquet / projet["bundle"]).resolve()),
                 f"{projet['ref_bundle']}:{ref_locale}", cwd=cache)
        try:
            if subprocess.run(["git", "cat-file", "-e", f"{projet['sha']}^{{commit}}"], cwd=cache,
                              capture_output=True).returncode != 0:
                raise RuntimeError(f"{projet['slug']} : SHA {projet['sha']} absent du cache (base "
                                   f"{projet.get('base')} absente du remote ?)")
            # Pas de `--quiet` : git 2.17 (la VM) ne le connait pas pour `worktree add` (execution 257448).
            _git("worktree", "add", "-B", projet["branche_travail"], str(destination), projet["sha"], cwd=cache)
        finally:  # la branche de travail porte desormais les commits : la ref de reception ne sert plus
            subprocess.run(["git", "update-ref", "-d", ref_locale], cwd=cache, capture_output=True)
    return destination, {"cache": str(cache), "geste": geste}


def retirer_worktree(projet: dict, destination: Path, trace: dict) -> None:
    cache = Path(trace["cache"])
    with verrou(cache):
        subprocess.run(["git", "worktree", "remove", "--force", str(destination)], cwd=cache, capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=cache, capture_output=True)
        subprocess.run(["git", "branch", "-D", projet["branche_travail"]], cwd=cache, capture_output=True)
