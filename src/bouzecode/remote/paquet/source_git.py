"""D'ou la VM tire l'historique d'un projet : son remote GitLab (clone en cache + bundle INCREMENTAL des
seuls commits locaux absents du remote) ou, a defaut, le bundle complet d'avant (journalise).

Base du bundle incremental : parmi les refs `refs/remotes/origin/*` du depot local, celle dont le
merge-base avec HEAD laisse le MOINS de commits a transmettre. Ces refs viennent du remote : leurs
commits y existent (sauf branche supprimee ou reecrite depuis le dernier fetch — la VM verifie alors
la presence de la base et echoue en clair).
"""
import hashlib
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DELAI_LS_REMOTE_S = 60  # ls-remote GitLab : 8-9 s mesures a vide, > 20 s sous charge (execution 257445)
DELAI_BUNDLE_S = 900  # bundle complet d'un gros depot sous charge : >120 s mesure le 2026-10-06


def _git(depot: Path, *arguments: str, delai_s: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], cwd=depot, capture_output=True, text=True, timeout=delai_s)


def url_sans_identifiants(url: str) -> str:
    """https sans `user:mdp@` ; `git@hote:chemin` devient `https://hote/chemin` ; chemin local tel quel."""
    ssh = re.match(r"^[\w.-]+@([\w.-]+):(.+)$", url)
    if ssh:
        return f"https://{ssh.group(1)}/{ssh.group(2)}"
    morceaux = urlsplit(url)
    if morceaux.scheme in ("http", "https") and "@" in morceaux.netloc:
        return urlunsplit(morceaux._replace(netloc=morceaux.netloc.rsplit("@", 1)[1]))
    return url


def nom_de_cache(url: str) -> str:
    """Nom du clone en cache sur la VM, stable par depot et COURT : `<depot>_<8 hex de l'url>.git`."""
    dernier = re.split(r"[/\\:]", url.rstrip("/\\").removesuffix(".git"))[-1]
    return f"{re.sub(r'[^A-Za-z0-9._-]+', '_', dernier).strip('_.') or 'depot'}_" \
           f"{hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]}.git"


def _meilleure_base(depot: Path) -> tuple[str, int] | None:
    refs = _git(depot, "for-each-ref", "--format=%(refname)", "refs/remotes/origin").stdout.split()
    candidats = []
    for ref in refs:
        base = _git(depot, "merge-base", "HEAD", ref).stdout.strip()
        if base:
            candidats.append((int(_git(depot, "rev-list", "--count", f"{base}..HEAD").stdout.strip()), base))
    return (min(candidats)[1], min(candidats)[0]) if candidats else None


def analyser(depot: Path) -> dict:
    """{"source": "remote", url, cache, base, commits_a_envoyer} ou {"source": "bundle_complet", raison}."""
    url = _git(depot, "remote", "get-url", "origin").stdout.strip()
    if not url:
        return {"source": "bundle_complet", "raison": "pas de remote origin"}
    try:
        joignable = _git(depot, "ls-remote", "--heads", "origin", delai_s=DELAI_LS_REMOTE_S).returncode == 0
    except subprocess.TimeoutExpired:
        joignable = False
    if not joignable:
        return {"source": "bundle_complet", "raison": f"remote origin injoignable ({url_sans_identifiants(url)})"}
    meilleure = _meilleure_base(depot)
    if meilleure is None:
        return {"source": "bundle_complet", "raison": "aucun commit commun avec refs/remotes/origin/*"}
    propre = url_sans_identifiants(url)
    return {"source": "remote", "url": propre, "cache": nom_de_cache(propre),
            "base": meilleure[0], "commits_a_envoyer": meilleure[1]}


def ecrire_bundle(depot: Path, branche: str, source: dict, destination: Path) -> str | None:
    """Bundle incremental `base..HEAD` (None si rien a envoyer) ou complet ; rend la ref transportee."""
    ref = "HEAD" if branche == "HEAD" else f"refs/heads/{branche}"
    if source["source"] == "remote":
        if source["commits_a_envoyer"] == 0:
            return None
        _git(depot, "bundle", "create", str(destination), ref, f"^{source['base']}",
             delai_s=DELAI_BUNDLE_S).check_returncode()
        return ref
    _git(depot, "bundle", "create", str(destination), ref, delai_s=DELAI_BUNDLE_S).check_returncode()
    return ref
