# [desc] Cycle de vie d'un bac à sable isolé : provision / harvest / integrate / cleanup. [/desc]
"""Worktree git + venv jetables par tâche, avec intégration conflict-safe.

Décisions : worktrees sous ~/.bouzecode/worktrees/<repo>/<ticket>, branche
agent/<ticket>. L'intégration synchronise d'abord la base DANS la branche agent
(dans le worktree — c'est là qu'un agent résout les conflits, jamais dans le repo
principal), ce qui fait de la branche un descendant de la base MÊME si celle-ci a
avancé depuis le provisioning ; puis elle intègre la branche dans la base sans jamais
exiger que l'arbre principal soit checkout sur la base (avance de ref si la base n'est
pas checkout, vrai merge --no-ff sinon). On ne détruit jamais un worktree non intégré
(anti-perte)."""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import branch_rescue, existing_branch

_log = logging.getLogger(__name__)

try:
    from . import worktree_sources
except ImportError:  # pragma: no cover - module optionnel absent de ce worktree
    class _WorktreeSourcesShim:
        """Fallback no-op quand le module worktree_sources est absent.

        `link_editable_sources` n'est appelée que dans `_setup_venv` (best-effort,
        thread daemon, non couverte par les tests) : le no-op ne dégrade aucun
        comportement testé et évite un ImportError à la collecte pytest."""

        @staticmethod
        def link_editable_sources(worktree, repo_root):  # noqa: ARG004
            return None

    worktree_sources = _WorktreeSourcesShim()

WORKTREES_DIR = bouzecode_data_dir() / "worktrees"
_IDENT = ["-c", "user.name=bouzecode", "-c", "user.email=bouzecode@local"]

# Ce que `harvest` refuse DÉLIBÉRÉMENT de committer : `.agents.lock` est le lock
# d'orchestration du harness, jamais du produit. La MÊME pathspec sert au staging et au
# constat de saleté résiduelle — sinon un simple lock oublié ferait crier « livraison non
# commitée » sur un ticket parfaitement récolté.
_NOT_PRODUCT = [":(exclude,glob)**/.agents.lock", ":(exclude,glob).agents.lock",
                # Plans / exports écrits par le harnais dans le cwd de l'agent : jamais du produit.
                ":(exclude,glob).nano_claude/**", ":(exclude,glob)**/.nano_claude/**"]

# Sérialisation GLOBALE de l'intégration PAR BASE DE MERGE (repo_root, base). Quand N tickets
# validés visent le MÊME `develop` en parallèle, chacun merge dans l'arbre principal partagé :
# sans verrou, le premier gagne et les autres voient soit la base « avancée pendant
# l'intégration » (is-ancestor faux), soit l'arbre momentanément tracked-dirty PENDANT qu'un
# merge concurrent écrit ses fichiers → faux needs_attention transitoires (« les merges ne se
# déclenchent pas »). Un verrou par (repo, base) garantit qu'UN SEUL ticket touche une base
# donnée à la fois. (Style calqué sur workflow._advance_locks, mais clé = base de merge.)
_merge_locks: dict[tuple[str, str], threading.Lock] = {}
_merge_locks_guard = threading.Lock()


def _lock_for_base(repo_root: str, base: str) -> threading.Lock:
    with _merge_locks_guard:
        key = (repo_root, base)
        lock = _merge_locks.get(key)
        if lock is None:
            lock = _merge_locks[key] = threading.Lock()
        return lock


# Le verrou ci-dessus ne vaut que DANS un process. Or un sous-agent intègre depuis SON process
# (outil Environment → `integrate`) : deux enfants qui finissent ensemble intégraient en même
# temps dans la même base, et le second recevait « 'main' a avancé pendant l'intégration »
# (needs_attention) — constaté en e2e (scénario manager-worktree) dès que le démarrage des
# agents est devenu plus rapide. Un verrou de FICHIER dans le répertoire git commun du dépôt
# sérialise aussi entre process (flock sous POSIX, msvcrt sous Windows).
VERROU_DELAI_S = 600.0


def _fichier_de_verrou(repo_root: str, base: str) -> Path | None:
    res = _run(repo_root, "rev-parse", "--git-common-dir", timeout=30)
    commun = (res.stdout or "").strip() if res.returncode == 0 else ""
    if not commun:
        return None
    dossier = Path(commun) if Path(commun).is_absolute() else Path(repo_root) / commun
    nom = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80]
    return dossier / f"bouzecode-integrate-{nom}.lock"


def _prendre(fichier, delai_s: float) -> bool:
    import time
    fin = time.monotonic() + delai_s
    if sys.platform == "win32":
        import msvcrt
        while True:
            try:
                fichier.seek(0)
                msvcrt.locking(fichier.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                if time.monotonic() >= fin:
                    return False
                time.sleep(0.05)
    import fcntl
    while True:
        try:
            fcntl.flock(fichier.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.monotonic() >= fin:
                return False
            time.sleep(0.05)


def _rendre(fichier) -> None:
    if sys.platform == "win32":
        import msvcrt
        fichier.seek(0)
        msvcrt.locking(fichier.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fichier.fileno(), fcntl.LOCK_UN)


@contextmanager
def verrou_inter_process(repo_root: str, base: str, delai_s: float | None = None):
    """Verrou d'intégration partagé par TOUS les process sur (dépôt, base). Au-delà du délai,
    ou si le dépôt n'a pas de répertoire git lisible, on continue sans (comportement
    d'avant, journalisé) : un verrou ne doit jamais bloquer une intégration à vie."""
    chemin = _fichier_de_verrou(repo_root, base)
    if chemin is None:
        yield
        return
    with open(chemin, "a+b") as fichier:
        pris = _prendre(fichier, VERROU_DELAI_S if delai_s is None else delai_s)
        if not pris:
            _log.warning("verrou d'intégration %s non obtenu : intégration sans verrou", chemin)
        try:
            yield
        finally:
            if pris:
                _rendre(fichier)


def _run(cwd: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # encoding forcé UTF-8 : git émet de l'UTF-8, mais `text=True` décoderait avec la locale
    # (cp1252 sous Windows) → un diff avec du non-ASCII (accents FR, emojis) lève
    # UnicodeDecodeError, stdout devient None et harvest/validate/merge cassent (500).
    cmd = ["git", "-C", cwd, *args]
    for essai in (1, 2):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # Délai restant NÉGATIF (vécu : « timed out after -3994 seconds » pendant un
            # integrate) = l'horloge a sauté pendant l'appel, typiquement une mise en veille
            # que le temps monotone de Windows compte. Git avait fini : on relance UNE fois.
            if essai == 1 and exc.timeout is not None and exc.timeout < 0:
                _log.warning("git %s : saut d'horloge (%.0fs), relance", args[:1], exc.timeout)
                continue
            raise subprocess.TimeoutExpired(cmd, timeout, exc.output, exc.stderr) from None
    raise AssertionError("inatteignable")


def _out(cwd: str, *args: str) -> str | None:
    res = _run(cwd, *args)
    return res.stdout.strip() if res.returncode == 0 else None


def _tracked_dirty(repo_root: str) -> bool:
    """Y a-t-il des modifs TRACKED non commitées (staged ou non) dans l'arbre principal ?

    `git status --porcelain` liste aussi les fichiers UNTRACKED (préfixe '?? '). Ceux-là
    ne bloquent PAS un merge et ne sont JAMAIS écrasés silencieusement par git (il refuse
    proprement, arbre intact, si un untracked serait écrasé) — on les ignore donc ici.
    Seules des modifs tracked (M/A/D/R/C, staged ou non) risqueraient le travail de
    l'humain lors d'un merge et doivent bloquer."""
    lines = (_out(repo_root, "status", "--porcelain") or "").splitlines()
    return any(not ln.startswith("??") for ln in lines if ln)


def _has_untracked(repo_root: str) -> bool:
    """Y a-t-il des fichiers UNTRACKED (préfixe '?? ') dans l'arbre principal ? Un merge qui veut
    CRÉER le même chemin échoue sinon — on les met de côté (stash) avec le tracked avant merge."""
    lines = (_out(repo_root, "status", "--porcelain") or "").splitlines()
    return any(ln.startswith("??") for ln in lines if ln)


def default_branch(repo_root: str) -> str:
    """Branche de référence du dépôt, par ordre de préférence :

    1. `develop` s'il existe LOCALEMENT — c'est la branche d'intégration vive de ces dépôts ;
    2. sinon la branche annoncée par `origin/HEAD`, SI elle existe localement ;
    3. sinon `master`, puis `main` ;
    4. sinon la branche actuellement checkout ;
    5. sinon `""` — aucune base résoluble, à l'appelant de le dire proprement.

    Toute candidate est vérifiée en `refs/heads/<x>` : `git worktree add -b agent/x <path> <base>`
    ne fait AUCUN DWIM remote, donc une base qui n'est pas une branche LOCALE produit
    `fatal: invalid reference: <base>`. C'était le bug : le basename d'`origin/HEAD` était rendu
    sans vérification (dépôt dont origin/HEAD = main mais qui travaille sur `master`), `main`/`master`
    étaient testés sans préfixe `refs/heads/` (un tag homonyme suffisait à matcher), et le repli
    final inventait le littéral `"main"` sur un dépôt sans commit (HEAD non né).
    `master` passe avant `main` : les dépôts de ce parc travaillent sur `master`.

    `develop` local passe AVANT `origin/HEAD` parce que plusieurs dépôts annoncent
    `origin/HEAD = master` alors que tout le travail se fait sur `develop` (mesuré le 2026-08-26 sur
    `demo-application` et `demo-monorepo`) : suivre `origin/HEAD` y ferait partir les worktrees
    d'agents d'une branche morte.
    """
    def _local(name: str) -> bool:
        return bool(name) and _run(repo_root, "rev-parse", "--verify",
                                   f"refs/heads/{name}").returncode == 0

    if _local("develop"):
        return "develop"
    ref = _out(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if ref and _local(ref.rsplit("/", 1)[-1]):
        return ref.rsplit("/", 1)[-1]
    for cand in ("master", "main"):
        if _local(cand):
            return cand
    courante = _out(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or ""
    return courante if _local(courante) else ""


def current_branch(repo_root: str) -> str:
    """Branche VIVE = celle actuellement checkout dans l'arbre principal (ce que le serveur
    EXÉCUTE). Les worktrees d'agents doivent partir de LÀ (et y remerger via meta['base']),
    sinon ils développent sur une branche que le serveur ne sert pas — ex : `develop` alors
    qu'une branche de session en diverge et tourne, rendant tout fix invisible au serveur.
    HEAD détaché → repli sur default_branch."""
    head = _out(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    if head and head != "HEAD":
        return head
    return default_branch(repo_root)


# Issues possibles d'un provisionnement de venv. `SKIPPED` n'est PAS un échec — le projet
# n'est simplement pas Python. Les confondre (l'ancien `return False` commun) rendait
# impossible de dire à l'utilisateur si son environnement était absent ou CASSÉ.
VENV_OK = "ok"
VENV_FAILED = "failed"
VENV_SKIPPED = "skipped"


def _setup_venv(worktree: Path, repo_root: str = "") -> str:
    """uv venv + uv sync (le projet peut ne pas être Python → `VENV_SKIPPED`). repo_root permet
    de relier les deps editables relatives (`../repo`) aux vrais dépôts avant le sync,
    sinon `uv sync` échoue depuis un worktree isolé (siblings inexistants).

    Renvoie l'une des trois issues `VENV_*` plutôt qu'un booléen : l'appelant asynchrone doit
    pouvoir DIRE au ticket ce qui s'est passé, et « pas un projet Python » n'a jamais été un
    échec à signaler."""
    if not (worktree / "pyproject.toml").is_file():
        return VENV_SKIPPED
    if repo_root:
        worktree_sources.link_editable_sources(worktree, repo_root)
    uv = shutil.which("uv") or str(Path.home().parents[0] / "uv.exe")
    from ...runtime import venv_env
    env = venv_env.env_sans_venv_designe()  # uv vise `./.venv`, jamais un venv hérité (10-12)
    try:
        # `--python <patch>` et pas le `.python-version` du dépôt (une SÉRIE) : sinon uv grave
        # le lien roulant dans `pyvenv.cfg` et le prochain patch rend le venv « invalide » à
        # ses yeux — donc supprimable. Repli sur `uv venv` nu si ce patch n'est pas
        # installable ici : on n'échange pas une gravure fragile contre une panne dure.
        cree = subprocess.run([uv, "venv", "--python", _python_spec()],
                              cwd=worktree, capture_output=True, timeout=120, env=env)
        if cree.returncode != 0:
            _log.warning("uv venv --python %s a echoue dans %s, repli sur uv venv nu : %s",
                         _python_spec(), worktree,
                         (cree.stderr or b"").decode("utf-8", "replace")[-400:])
            subprocess.run([uv, "venv"], cwd=worktree, capture_output=True, timeout=120, env=env)
        sync = subprocess.run([uv, "sync", "--all-extras"], cwd=worktree, capture_output=True,
                              timeout=600, env=env)
    except (OSError, subprocess.SubprocessError):
        _discard_ghost_venv(worktree)
        return VENV_FAILED
    if sync.returncode != 0:
        _log.warning("uv sync --all-extras a echoue dans %s : %s", worktree,
                     (sync.stderr or b"").decode("utf-8", "replace")[-400:])
        _discard_ghost_venv(worktree)
        return VENV_FAILED
    return VENV_OK


def _python_spec() -> str:
    """`venv_env.pinned_python_spec()`, robuste à un `venv_env` PÉRIMÉ en mémoire.

    Vécu le 2026-09-21 : un process d'agent avait chargé `venv_env` avant l'ajout de
    `pinned_python_spec`, puis ce module-ci (import paresseux) après — « module ... has no
    attribute 'pinned_python_spec' », et l'agent a déclaré l'action venv cassée pour de bon.
    Le calcul est trivial (version de l'interpréteur courant) : on le refait sur place."""
    from ...runtime import venv_env
    spec = getattr(venv_env, "pinned_python_spec", None)
    return spec() if spec else "%d.%d.%d" % sys.version_info[:3]


def _discard_ghost_venv(worktree: Path) -> None:
    """Retire le `.venv` que `uv venv` a créé quand le `uv sync` qui suit a échoué.

    Sans ça, l'échec est PIRE que l'absence de venv : `uv venv` réussit toujours, donc il
    reste dans le worktree un `.venv` VIDE (site-packages = `_virtualenv.pth` et rien
    d'autre). Et un venv vide n'est pas inerte : c'est le venv le PLUS PROCHE, donc tout
    `uv run` / `python` lancé depuis ce dossier le préfère au venv de base et meurt en
    `ModuleNotFoundError`. L'agent se retrouvait moins bien équipé pour avoir demandé un
    environnement — et le message « ton environnement est INCHANGÉ » était faux sur le
    disque. On le rend vrai ici."""
    venv = worktree / ".venv"
    if not venv.exists():
        return
    shutil.rmtree(venv, ignore_errors=True)
    _log.info("venv fantome retire de %s (sync echoue) : le venv de base reste visible", worktree)


def main_repo_root(worktree: Path) -> str:
    """Le dépôt PRINCIPAL dont `worktree` est un worktree, "" si indéterminable.

    `_setup_venv` a besoin de ce chemin pour relier les dépendances editables relatives
    (`../repo`) avant le sync. Il lui venait uniquement du ticket
    (`ticket["worktree"]["repo_root"]`) : un agent lancé À LA MAIN n'a pas de ticket, donc
    recevait "", donc aucun relinkage, donc un `uv sync` condamné. Le worktree sait
    pourtant tout seul d'où il vient — `--git-common-dir` désigne le `.git` PARTAGÉ, dont
    le parent est le dépôt principal."""
    try:
        vu = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=worktree, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    if vu.returncode != 0:
        return ""
    git_dir = vu.stdout.decode("utf-8", "replace").strip()
    if not git_dir:
        return ""
    return str(Path(git_dir).parent)


def setup_venv_async(worktree: str, repo_root: str = "", on_result=None) -> None:
    """Lance uv venv + uv sync en fond (uv sync peut durer des minutes — ne doit
    jamais bloquer la requête de dispatch).

    `on_result(issue)` est rappelé avec l'issue `VENV_*` à la fin. Sans lui, ce provisionnement
    était un fire-and-forget TOTAL — assumé par sa propre docstring (« sans suivi de
    résultat ») : un `uv sync --all-extras` de plusieurs minutes n'avait aucun état visible, et
    son échec non plus, alors que c'est exactement ce qui laisse un agent dans un worktree sans
    dépendances. Le rappel reste best-effort côté appelant : ce module ne connaît ni les
    tickets ni l'UI, il rend juste son verdict à qui le lui demande."""
    def _provision_then_report() -> None:
        issue = _setup_venv(Path(worktree), repo_root)
        if on_result is not None:
            on_result(issue)

    threading.Thread(target=_provision_then_report, daemon=True).start()


_PROVISION_ATTEMPTS = 3  # 1 essai + 2 reprises. BORNÉ : jamais une boucle.


def _add_worktree_once(repo_root: str, worktree: Path, branch: str,
                       base: str) -> tuple[str, bool]:
    """UNE tentative de `git worktree add` → (motif d'échec ou "", délai dépassé ?).

    Un DÉPASSEMENT DE DÉLAI est ici un motif d'échec comme un autre, et non plus une exception
    qui traverse tout le dispatch : `subprocess.run(timeout=)` lève `TimeoutExpired`, et cette
    exception remontait jusqu'à `dispatch._launch_bg`. Le ticket restait alors sans run, sans
    worktree, et son manager parent attendait un verdict qui ne viendrait jamais (cas 60f34332
    du 2026-07-28 : `git worktree add` tué à 120 s, 27 minutes de silence)."""
    try:
        res = _run(repo_root, "worktree", "add", "-b", branch, str(worktree), base)
    except subprocess.TimeoutExpired as exc:
        return f"`git worktree add` n'a pas rendu la main en {exc.timeout:.0f} s", True
    if res.returncode == 0:
        return "", False
    return (res.stderr.strip() or f"code {res.returncode}"), False


def add_worktree_bounded(repo_root: str, ticket_id: str, worktree: Path, branch: str,
                         base: str, on_attempt=None) -> str:
    """`git worktree add` avec une reprise BORNÉE. "" au succès, sinon le journal des essais.

    POURQUOI UNE REPRISE plutôt qu'un délai de garde plus généreux : sur ce poste, un
    `git worktree add` coûte 50 s à vide pour 1209 fichiers suivis (antivirus d'entreprise qui
    inspecte chaque écriture) — la marge sur les 120 s du délai est de 2,4× seulement, et la
    charge (plusieurs agents, suites de tests) suffit à la consommer. Allonger le délai ne fait
    que déplacer le seuil tout en figeant le dispatch plus longtemps ; une reprise, elle, repart
    sur un cache de fichiers CHAUD et rend l'échec RÉCUPÉRABLE plutôt que fatal.

    Elle est BORNÉE et TRACÉE : nombre d'essais FIXE (`_PROVISION_ATTEMPTS`), une ligne de log
    par essai, et un motif final agrégé (tous les essais) quand elle renonce — l'appelant rend
    alors un échec net, jamais une nouvelle tentative.

    Elle ne rejoue QUE le dépassement de délai. Un échec DÉTERMINISTE (base inconnue, branche
    `agent/<id>` déjà existante) rendrait le même verdict aux essais suivants : le rejouer ne
    serait que du temps perdu, et surtout la purge ci-dessous effacerait alors un état que
    l'appelant n'a pas demandé de réclamer — décider du sort d'une branche existante appartient
    à `discard_stale`/`dispatch.reisolate`, jamais au provisionnement.

    Entre deux essais, l'état résiduel de NOTRE essai est purgé (`discard_stale`) : un
    `worktree add` tué en cours de route laisse derrière lui le dossier, l'entrée
    d'administration git ET la branche — le nouvel essai échouerait sinon sur « already exists ».

    `on_attempt(attempt, total, error)` est rappelé à chaque essai raté, AVANT le suivant : le
    journal des essais n'était rendu qu'à la toute fin, et seulement dans le log du serveur. Un
    ticket pouvait donc rester deux minutes et demie « en préparation » sans que rien ne dise
    qu'on en était au troisième essai — ce que l'appelant peut désormais afficher en direct."""
    journal: list[str] = []
    for attempt in range(1, _PROVISION_ATTEMPTS + 1):
        error, timed_out = _add_worktree_once(repo_root, worktree, branch, base)
        if not error:
            return ""
        journal.append(f"essai {attempt}/{_PROVISION_ATTEMPTS} : {error}")
        _log.warning("worktrees: provisionnement du ticket %s, essai %d/%d échoué : %s",
                     ticket_id, attempt, _PROVISION_ATTEMPTS, error)
        if on_attempt is not None:
            on_attempt(attempt, _PROVISION_ATTEMPTS, error)
        if not timed_out:
            break
        if attempt < _PROVISION_ATTEMPTS:
            discard_stale(repo_root, ticket_id, base_branch=base)
    return " | ".join(journal)


def provision(repo_root: str, ticket_id: str, base_branch: str = "",
              with_venv: bool = False, work_branch: str = "",
              on_attempt=None) -> dict[str, Any]:
    """Crée worktree agent/<ticket> sur une nouvelle branche depuis la base.

    `with_venv` est FAUX par défaut : un venv ne se provisionne QUE s'il a été demandé
    (isolation `worktree+venv`). Le défaut valait `True`, si bien qu'un appelant qui l'omettait
    infligeait un `uv sync --all-extras` — ~1 Go et plusieurs minutes — à un agent qui n'en
    avait pas demandé. Un worktree sans venv emprunte celui du dépôt de base
    (`dispatch.base_venv_for` → `runtime/venv_env.py`).

    `work_branch` renverse ce contrat : l'agent travaille SUR cette branche EXISTANTE au lieu
    d'en recevoir une neuve (cf. `existing_branch`). C'est la seule façon d'honorer « ta
    branche de travail = X » ; sans elle, `base_branch` ne fait que servir de point de départ
    et la demande était silencieusement remplacée par une branche neuve. Échec = erreur
    remontée telle quelle (branche inconnue ou déjà sortie ailleurs), jamais de repli."""
    if work_branch:
        meta = existing_branch.provision_on(repo_root, ticket_id, work_branch, WORKTREES_DIR)
        if meta.get("ok") and with_venv:
            meta["venv_ok"] = _setup_venv(Path(meta["worktree"]), repo_root) == VENV_OK
        return meta
    base = base_branch or default_branch(repo_root)
    if not base:
        # `default_branch` rend "" quand AUCUNE branche locale n'existe (dépôt sans commit,
        # HEAD non né). Inventer une base ici redonnerait `fatal: invalid reference: main` :
        # on remonte un motif lisible que Environment(action='worktree') affiche tel quel.
        return {"ok": False, "state": "error",
                "error": ("aucune branche de base résoluble dans " + repo_root +
                          " (dépôt sans commit, ou aucune branche locale develop/master/main) — "
                          "fais un premier commit ou passe base_branch explicitement")}
    name = re.sub(r"[^A-Za-z0-9_-]", "-", ticket_id)
    worktree = WORKTREES_DIR / Path(repo_root).name / name
    branch = f"agent/{name}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    error = add_worktree_bounded(repo_root, ticket_id, worktree, branch, base,
                                 on_attempt=on_attempt)
    if error:
        return {"ok": False, "error": error, "state": "error"}
    venv_ok = with_venv and _setup_venv(worktree, repo_root) == VENV_OK
    return {"ok": True, "state": "provisioned", "repo_root": repo_root,
            "worktree": str(worktree), "branch": branch, "base": base, "venv_ok": venv_ok}


def discard_worktree(repo_root: str, ticket_id: str) -> None:
    """Retire le RÉPERTOIRE de travail du ticket (et l'entrée d'administration git), en
    laissant la branche intacte. Idempotent : sûr si le worktree n'existe déjà plus."""
    name = re.sub(r"[^A-Za-z0-9_-]", "-", ticket_id)
    worktree = WORKTREES_DIR / Path(repo_root).name / name
    if worktree.exists():
        _run(repo_root, "worktree", "remove", "--force", str(worktree))
    _run(repo_root, "worktree", "prune")


def discard_stale(repo_root: str, ticket_id: str, base_branch: str = "") -> dict[str, Any]:
    """Purge idempotente d'un bac à sable ABANDONNÉ (crashé/reapé) AVANT une re-provision :
    retire le worktree résiduel et SUPPRIME la branche `agent/<id>` restée derrière. Le reaper
    enlève le worktree mais laisse la branche, or `provision` fait `worktree add -b agent/<id>`
    qui échouerait alors sur 'branch already exists'.

    La suppression passe par `branch_rescue.drop_branch` : une branche qui porte des commits
    absents de la base est TAGUÉE avant de disparaître. Cette purge s'appelait « à n'utiliser
    que pour un retry sans travail à sauver » — une consigne qu'aucun appelant ne pouvait
    honorer, puisque personne ne regardait ce que la branche portait. Renvoie le compte rendu
    de `drop_branch` (dont `rescue_tag`) pour que l'appelant puisse le dire au ticket."""
    discard_worktree(repo_root, ticket_id)
    return branch_rescue.drop_branch(repo_root, branch_rescue.agent_branch(ticket_id),
                                     base_branch or default_branch(repo_root))


def dir_exists(meta: Any) -> bool:
    """Le répertoire du worktree existe-t-il encore sur le disque ? Un vieux ticket peut
    porter un état 'provisioned'/'committed' alors que le worktree a été supprimé (cleanup
    manuel, purge). Y spawner un agent (cwd inexistant) lève NotADirectoryError → à éviter."""
    if not isinstance(meta, dict):
        return False
    wt = meta.get("worktree")
    return bool(wt) and Path(wt).is_dir()


def dirty_files(meta: dict) -> list[str]:
    """Chemins du worktree encore NON COMMITÉS, hors fichiers non-produit (`_NOT_PRODUCT`).

    Sert à prouver qu'une récolte a bien tout mis en sûreté : c'est le seul constat qui
    distingue « l'agent n'avait rien produit » de « son travail est toujours en péril »."""
    lines = (_out(meta["worktree"], "status", "--porcelain", "--", *_NOT_PRODUCT) or "").splitlines()
    return [line[3:].strip().strip('"') for line in lines if line.strip()]


def head_of(meta: dict) -> str:
    """SHA du tip de la branche du worktree (lecture seule), "" si illisible."""
    return _out(meta["worktree"], "rev-parse", meta["branch"]) or ""


_OPERATIONS_GIT = (("MERGE_HEAD", "un merge"), ("rebase-merge", "un rebase"),
                  ("rebase-apply", "un rebase"), ("CHERRY_PICK_HEAD", "un cherry-pick"),
                  ("REVERT_HEAD", "un revert"))


def _operation_en_cours(wt: str) -> str:
    """Nom de l'opération git inachevée dans `wt` (merge, rebase…), ou "".

    Un seul `rev-parse` pour les cinq chemins (une ligne chacun, dans l'ordre) : un appel git
    coûte 50 à 150 ms sous Windows, et ce constat passe deux fois par intégration."""
    demandes = [arg for ref, _ in _OPERATIONS_GIT for arg in ("--git-path", ref)]
    chemins = (_out(wt, "rev-parse", *demandes) or "").splitlines()
    for chemin, (_, nom) in zip(chemins, _OPERATIONS_GIT):
        if chemin and (Path(wt) / chemin).exists():  # relatif à wt, ou absolu (Path l'ignore)
            return nom
    return ""


def _marqueurs_introduits(wt: str) -> list[str]:
    """Conflits NON résolus que la récolte figerait : entrées non-mergées de l'index, ou
    marqueurs dans un fichier MODIFIÉ depuis HEAD ou non suivi. Un marqueur déjà committé
    (fixture de test, doc sur les conflits) ne bloque pas : sinon la récolte resterait
    suspendue à jamais sur ce dépôt, sans que l'agent ait rien à résoudre.
    `_conflict_residue` ne lit déjà que ces fichiers-là."""
    return _conflict_residue(wt)


def blocage_recolte(wt: str) -> dict[str, Any] | None:
    """Pourquoi la récolte NE DOIT PAS committer maintenant, ou None.

    Committer pendant un merge inachevé ou avec des marqueurs de conflit fige un état
    cassé dans l'historique (constaté : commit d1500e9, 3 marqueurs dans tinder.html,
    committé par une récolte au milieu d'une intégration en conflit)."""
    operation = _operation_en_cours(wt)
    conflits = _marqueurs_introduits(wt)
    if not operation and not conflits:
        return None
    cause = f"{operation} est en cours" if operation else "des marqueurs de conflit restent"
    return {"raison": "conflit_en_cours", "fichiers": conflits,
            "message": (f"Récolte suspendue : {cause} dans {wt}"
                        + (f" ({', '.join(conflits[:5])})" if conflits else "")
                        + ". Rien n'a été committé : termine le merge (résous puis `git add` + "
                          "`git commit`) ou annule-le (`git merge --abort`).")}


def harvest(meta: dict, title: str, body: str = "") -> dict[str, Any]:
    """Commit le travail non commité sur la branche agent + renvoie le diff vs base.

    `body` (optionnel) = corps de message riche (recap formaté du codeur, T7) ajouté
    via un 2e `-m` : le titre reste `agent: {title}` (tronqué à 72), le corps embarque
    le récap → il voyage dans l'historique quel que soit le mode d'intégration (le merge
    base peut être un fast-forward sans commit de merge).

    `dirty` = ce qui RESTE non commité après coup. Un harvest peut échouer sans lever
    (index git verrouillé par une opération concurrente, hook de commit qui refuse) :
    sans ce constat, l'appelant croyait le travail sauvé et le worktree finissait fauché
    avec lui. Vide = plus rien à perdre."""
    wt = meta["worktree"]
    committed = False
    bloque = blocage_recolte(wt)
    if bloque is None and _out(wt, "status", "--porcelain"):
        # `.agents.lock` = lock d'orchestration du harness (état local par worktree,
        # référence les scripts jetables temp_*), JAMAIS du produit. `add -A` l'aspirerait
        # comme tout untracked → il finit committé dans le merge d'agent. On l'exclut du staging via pathspec magic (aveugle au reste du
        # travail). Les fichiers temp=True, eux, vivent déjà HORS du worktree (scratch dir,
        # cf. tools/ops/scratch.py) : git ne les voit pas, rien à exclure côté temp.
        _run(wt, "add", "-A", "--", *_NOT_PRODUCT)
        commit_args = ["commit", "-m", f"agent: {title}"[:72]]
        if body.strip():
            commit_args += ["-m", body]
        res = _run(wt, *_IDENT, *commit_args)
        committed = res.returncode == 0
    diff = _out(wt, "diff", f"{meta['base']}...{meta['branch']}") or ""
    # SHA du tip FIGÉ juste après le commit, atomiquement avec le diff : c'est l'état EXACT
    # que le diff décrit. Qui relit une livraison doit ancrer sa relecture sur CE sha (git diff
    # base...<sha>), pas sur HEAD (ref mouvante) : un re-commit du codeur pendant la relecture
    # lui ferait juger un autre état que celui livré.
    return {"committed": committed, "diff": diff, "head": _out(wt, "rev-parse", meta["branch"]) or "",
            "dirty": dirty_files(meta), "bloque": bloque,
            "files": (_out(wt, "diff", "--name-only", f"{meta['base']}...{meta['branch']}") or "").splitlines()}


def _conflict_marker_files(repo_root: str, ref: str) -> list[str]:
    """Fichiers de `ref` portant des marqueurs de conflit non résolus (`<<<<<<< ` / `>>>>>>> `).
    Un agent peut committer une résolution ratée : on refuse alors d'intégrer du code cassé
    dans la branche de référence (cf. incident c1d0206 : app.py mergé avec marqueurs → serveur mort)."""
    out = _out(repo_root, "grep", "-lE", r"^(<<<<<<< |>>>>>>> )", ref) or ""
    return [ln.split(":", 1)[-1] for ln in out.splitlines() if ln]


_LOT_PATHSPEC = 8000  # caractères par appel : la ligne de commande Windows plafonne à ~32 K


def _fichiers_sales(repo_root: str) -> list[str]:
    """Fichiers modifiés depuis HEAD (indexés ou non, non-mergés compris) + non suivis non ignorés.

    `status` plutôt que `diff HEAD` : sur un index « racy » (worktree tout juste créé), git doit
    relire le contenu des fichiers ; `status` réécrit l'index rafraîchi, `diff` jamais — il
    repaierait cette relecture à chaque appel. `_run` et non `_out` : son `strip()` rognerait
    l'espace de tête du code « XY » de la première entrée."""
    res = _run(repo_root, "status", "--porcelain", "-z", "--untracked-files=all")
    champs = res.stdout.split("\0") if res.returncode == 0 else []
    sales, i = set(), 0
    while i < len(champs):
        entree = champs[i]
        i += 1
        if len(entree) < 4:
            continue
        sales.add(entree[3:])
        if "R" in entree[:2] or "C" in entree[:2]:
            i += 1  # renommage / copie : le champ suivant est le chemin d'origine
    return sorted(sales)


def _lots(chemins: list[str], plafond: int = _LOT_PATHSPEC) -> list[list[str]]:
    """Découpe `chemins` en lots dont la longueur cumulée reste sous `plafond`."""
    lots, lot, taille = [], [], 0
    for chemin in chemins:
        if lot and taille + len(chemin) + 1 > plafond:
            lots.append(lot)
            lot, taille = [], 0
        lot.append(chemin)
        taille += len(chemin) + 1
    return lots + [lot] if lot else lots


def _conflict_residue(repo_root: str) -> list[str]:
    """Fichiers de l'ARBRE DE TRAVAIL qui portent un conflit NON résolu : entrées non-mergées
    de l'index (`git ls-files -u`, état UU après un stash pop conflictuel) OU marqueurs
    `^<<<<<<< ` dans un fichier SALE (modifié depuis HEAD ou non suivi). Distinct de
    `_conflict_marker_files` qui grep un REF committé — ici on inspecte l'arbre vivant servi
    tel quel (cf. incident : conversations.js laissé en UU après un `stash pop` de
    restauration en conflit → JS cassé, page /conversations morte).

    Le grep ne lit QUE les fichiers sales : sur tout l'arbre, la première lecture des ~2 000
    fichiers suivis coûtait 12 à 15 s (antivirus), à chaque harvest et à chaque integrate.
    Un marqueur déjà committé dans un fichier intact n'est pas un conflit en cours."""
    unmerged = _out(repo_root, "ls-files", "-u", "-z") or ""
    paths = {ln.split("\t", 1)[-1] for ln in unmerged.split("\0") if "\t" in ln}
    for lot in _lots(_fichiers_sales(repo_root)):
        marked = _out(repo_root, "--literal-pathspecs", "grep", "--untracked", "-lzE",
                      r"^<<<<<<< ", "--", *lot) or ""
        paths.update(f for f in marked.split("\0") if f)
    return sorted(paths)


def integrate(meta: dict) -> dict[str, Any]:
    """Intègre la branche agent dans la base, SÉRIALISÉ globalement par base de merge.

    Les verrous `_lock_for_base(repo, base)` (threads du process) et `verrou_inter_process`
    (process : chaque agent intègre depuis le sien) garantissent qu'un seul ticket merge dans
    une base donnée à la fois → supprime la course entre N merges concurrents visant le même `develop`
    (plus de faux needs_attention transitoires). Le vrai travail est dans `_integrate_locked`."""
    with _lock_for_base(meta["repo_root"], meta["base"]), \
            verrou_inter_process(meta["repo_root"], meta["base"]):
        return _integrate_locked(meta)


def _integrate_locked(meta: dict) -> dict[str, Any]:
    """Synchronise la base dans la branche agent (worktree), puis intègre la branche
    dans la base côté repo principal, en gérant une base qui a AVANCÉ depuis le branchement.
    APPELÉ SOUS `_lock_for_base` — aucun merge concurrent ne touche la base pendant ce corps.

    Après la synchro, la branche est un descendant de la base : l'intégration est un
    fast-forward de la ref. On ne force jamais l'arbre principal à être sur la base :
      • base non checkout   → on avance la ref (`git branch -f`, FF garanti) ;
      • base checkout propre → vrai merge `--no-ff` dans l'arbre principal ;
      • base checkout sale   → needs_attention (merge manuel requis).
    Conflit de synchro → on N'ABORTE PAS : un agent le résout dans le worktree, le repo
    principal reste intact. `needs_attention` ne survient donc que sur cas réellement bloquant."""
    wt, repo, base, branch = meta["worktree"], meta["repo_root"], meta["base"], meta["branch"]

    # Garde-fou : un conflit résiduel dans l'arbre PRINCIPAL (marqueurs `<<<<<<<` ou entrées
    # UU laissés par une intégration antérieure) empoisonnerait toute nouvelle intégration —
    # et surtout, du code cassé (JS servi tel quel) serait en ligne. On refuse bruyamment et
    # on parke le ticket (retryable via /integrate) plutôt que d'empiler par-dessus.
    residue = _conflict_residue(repo)
    if residue:
        return {"ok": False, "state": "needs_attention", "retryable": False,
                "remede": "résoudre ces conflits à la main dans l'arbre principal",
                "error": f"résidu de conflit non résolu dans l'arbre principal "
                         f"({', '.join(residue[:4])}) — résoudre à la main avant d'intégrer"}

    # Travail EN PLACE (`work_branch`) : l'agent a commité directement sur la branche demandée,
    # la livraison y est DÉJÀ. Il n'y a aucune branche d'agent à y reverser — `base` n'est ici
    # qu'un SHA repère pour le diff de `harvest`, pas une cible de merge. On vérifie quand même
    # qu'on ne déclare pas « intégré » du code portant des marqueurs de conflit.
    if meta.get("in_place"):
        bad = _conflict_marker_files(repo, branch)
        if bad:
            return {"ok": False, "state": "needs_attention",
                    "error": f"marqueurs de conflit non résolus ({', '.join(bad[:4])}) sur "
                             f"'{branch}' — refus de déclarer la livraison intégrée"}
        return {"ok": True, "state": "integrated", "in_place": True}

    sync = _run(wt, *_IDENT, "merge", "--no-edit", base)
    if sync.returncode != 0:
        conflicts = (_out(wt, "diff", "--name-only", "--diff-filter=U") or "").splitlines()
        if conflicts:
            return {"ok": False, "state": "conflict", "files": conflicts}
        _run(wt, "merge", "--abort")
        return {"ok": False, "state": "error", "error": sync.stderr.strip()}

    bad = _conflict_marker_files(repo, branch)
    if bad:
        return {"ok": False, "state": "needs_attention",
                "error": f"marqueurs de conflit non résolus ({', '.join(bad[:4])}) — "
                         f"refus d'intégrer du code cassé dans '{base}'"}

    # La branche contient désormais la base → intégration = fast-forward de la ref.
    # Sous le verrou par base, ce cas est quasi-impossible (le sync ci-dessus a lu une base
    # stable) ; s'il survient (base avancée juste hors-verrou), il suffit de redemander
    # l'intégration — plus de retry automatique, c'est l'appelant qui relance /integrate.
    if _run(repo, "merge-base", "--is-ancestor", base, branch).returncode != 0:
        return {"ok": False, "state": "needs_attention", "retryable": True,
                "error": f"'{base}' a avancé pendant l'intégration — relancer l'intégration"}

    if _out(repo, "rev-parse", "--abbrev-ref", "HEAD") == base:
        return _merge_into_live_base(repo, branch, base)

    #  La base est sortie dans un AUTRE worktree (typiquement : le sous-agent intègre dans la
    #  branche de son parent, que le parent a sortie dans son propre worktree). git refuse d'y
    #  forcer la ref (« cannot force update the branch … used by worktree ») : on fusionne DANS
    #  ce worktree, comme le ferait son propriétaire.
    occupant = worktree_of_branch(repo, base)
    if occupant:
        return _merge_into_other_worktree(occupant, branch, base)

    upd = _run(repo, "branch", "-f", base, branch)
    if upd.returncode != 0:
        return {"ok": False, "state": "error", "error": upd.stderr.strip()}
    return {"ok": True, "state": "integrated"}


def worktree_of_branch(repo: str, branch: str) -> str:
    """Chemin du worktree où `branch` est sortie ('' si elle n'est sortie nulle part)."""
    chemin = ""
    for line in (_out(repo, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            chemin = line[len("worktree "):].strip()
        elif line.strip() == f"branch refs/heads/{branch}":
            return chemin
    return ""


def _fichiers_bloquants(cible: str, branch: str, base: str) -> list[str]:
    """Fichiers que `branch` apporte ET que le worktree `cible` a modifiés sans les commiter.

    Calculé depuis git (et non en lisant son message, traduit selon la locale : « seraient
    écrasées » sur un poste français)."""
    apportes = set((_out(cible, "diff", "--name-only", f"{base}...{branch}") or "").splitlines())
    sales: set[str] = set()
    for args in (("diff", "--name-only"), ("diff", "--name-only", "--cached"),
                 ("ls-files", "--others", "--exclude-standard")):
        sales.update((_out(cible, *args) or "").splitlines())
    return sorted(apportes & sales)


def _merge_into_other_worktree(cible: str, branch: str, base: str) -> dict[str, Any]:
    """Fusionne `branch` dans `base`, sortie dans le worktree `cible` (celui d'un autre agent).

    On ne met JAMAIS de côté les modifications non commitées de ce worktree : elles
    appartiennent à un agent qui travaille peut-être en ce moment. git refuse de lui-même un
    merge qui les écraserait ; on le dit alors clairement, sans promettre qu'un nouvel essai
    identique réussira."""
    merge = _run(cible, *_IDENT, "merge", "--no-ff", "--no-edit", branch)
    if merge.returncode == 0:
        return {"ok": True, "state": "integrated", "worktree_cible": cible}
    erreur = (merge.stderr or merge.stdout or "").strip()
    _run(cible, "merge", "--abort")
    bloquants = _fichiers_bloquants(cible, branch, base)
    if bloquants:
        return {"ok": False, "state": "bloque", "retryable": False, "files": bloquants,
                "error": (f"le worktree {cible} (branche '{base}') a des modifications non "
                          f"commitées sur des fichiers que tu apportes ({', '.join(bloquants[:6])})"),
                "remede": (f"son propriétaire (ton agent parent, en général) doit commiter ou "
                           f"ranger ces fichiers dans {cible} avant que tu intègres — "
                           f"préviens-le (MessageAgent) ou termine en le signalant")}
    return {"ok": False, "state": "bloque", "retryable": False, "error": erreur,
            "remede": f"fusion refusée par git dans {cible} : lis l'erreur ci-dessus"}


def _stash_arbre_sale(repo: str, branch: str) -> tuple[bool, str]:
    """(stashé ?, erreur). Met de côté les modifs trackées ET non suivies de l'arbre principal."""
    #  Suivi modifié OU non suivi = toute ligne de `status` : un seul appel git au lieu des
    #  deux de `_tracked_dirty` + `_has_untracked`.
    if not (_out(repo, "status", "--porcelain") or "").strip():
        return False, ""
    st = _run(repo, *_IDENT, "stash", "push", "--include-untracked",
              "-m", f"bouzecode-auto-integrate {branch}")
    if st.returncode != 0:
        return False, f"stash de l'arbre sale avant merge impossible : {st.stderr.strip()}"
    return "No local changes" not in (st.stdout or ""), ""


def _residu_de_conflit(repo: str, contexte: str) -> dict[str, Any] | None:
    """Défense en profondeur : aucune intégration ne doit laisser un conflit en ligne."""
    residue = _conflict_residue(repo)
    if not residue:
        return None
    return {"ok": False, "state": "needs_attention",
            "error": f"{contexte} ({', '.join(residue[:4])}) — intervention manuelle requise"}


def _restauration_en_conflit(repo: str, branch: str) -> dict[str, Any]:
    """Le `stash pop` a conflicté : le WIP humain touchait un fichier que le merge vient de
    réécrire. L'arbre resterait en état UU avec des marqueurs `<<<<<<<` (souvent du JS servi
    tel quel, qui casserait la page) : on le réaligne sur l'état mergé. Le WIP n'est PAS perdu,
    il reste dans le stash `bouzecode-auto-integrate {branch}`, qu'on remonte."""
    marked = _conflict_residue(repo)
    _run(repo, "reset", "--hard", "HEAD")
    msg = f"bouzecode-auto-integrate {branch}"
    stash_ref = next((ln.split(":", 1)[0] for ln in (_out(repo, "stash", "list") or "").splitlines()
                      if msg in ln), "")
    print(f"[integrate] restore en conflit sur {branch} : arbre principal réaligné sur "
          f"l'état mergé ; WIP humain SAUF dans {stash_ref or 'la pile git stash'} "
          f"(fichiers : {', '.join(marked) or '?'})", flush=True)
    residu = _residu_de_conflit(repo, "restauration en conflit et nettoyage incomplet de "
                                      "l'arbre principal")
    return residu or {"ok": True, "state": "integrated",
                      "restore_conflict": {"branch": branch, "stash_ref": stash_ref,
                                           "stash_message": msg, "files": marked}}


def _merge_into_live_base(repo: str, branch: str, base: str) -> dict[str, Any]:
    """Intègre `branch` quand `base` est CHECKOUT dans l'arbre principal (serveur ET agents
    partagent ce seul checkout). git ne peut pas avancer une branche checkout dont l'arbre
    porte des modifs non commitées : on met l'arbre sale de côté (stash tracked + untracked),
    on merge, puis on restaure — aucun travail perdu, le merge n'est plus otage d'un artefact
    orphelin.

    La branche descend déjà de la base (is-ancestor vérifié en amont) → le merge --no-ff ne peut
    pas conflicter sur le CONTENU. Seul le stash pop peut conflicter (cf. `_restauration_en_conflit`)."""
    stashed, erreur = _stash_arbre_sale(repo, branch)
    if erreur:
        return {"ok": False, "state": "needs_attention", "error": erreur}
    merge = _run(repo, *_IDENT, "merge", "--no-ff", "--no-edit", branch)
    if merge.returncode != 0:
        _run(repo, "merge", "--abort")
        if stashed:
            _run(repo, "stash", "pop")
        return {"ok": False, "state": "needs_attention", "error": merge.stderr.strip()}
    if stashed and _run(repo, "stash", "pop").returncode != 0:
        return _restauration_en_conflit(repo, branch)
    return (_residu_de_conflit(repo, "conflit résiduel dans l'arbre principal après intégration")
            or {"ok": True, "state": "integrated"})


def _branch_is_disposable(meta: dict, delete_branch: bool) -> bool:
    """Peut-on supprimer la branche de ce bac à sable ? NON pour un travail EN PLACE : la
    branche n'appartient pas au ticket, elle PRÉEXISTAIT et porte la livraison attendue —
    la faucher détruirait exactement ce qu'on venait d'y déposer."""
    return delete_branch and not meta.get("in_place")


def _arreter_ses_processus(worktree: str) -> None:
    """Au plus tard à la suppression du worktree : ce que les Bash d'agents y ont lancé
    (serveur de test, watcher) s'arrête avec lui au lieu de tourner dans un dossier disparu."""
    from ....backend.tools.ops.bash_bg import arreter_processus_du_worktree
    arretes = arreter_processus_du_worktree(worktree)
    if arretes:
        print(f"[worktree] {worktree} : processus d'agent arrêtés {arretes}", flush=True)


def cleanup(meta: dict, delete_branch: bool = True) -> dict[str, Any]:
    """Supprime le worktree (+venv) et la branche agent. À n'appeler qu'après intégration."""
    repo, wt, branch = meta["repo_root"], meta["worktree"], meta["branch"]
    _arreter_ses_processus(wt)
    _run(repo, "worktree", "remove", "--force", wt)
    if Path(wt).exists():
        shutil.rmtree(wt, ignore_errors=True)
    if _branch_is_disposable(meta, delete_branch):
        _run(repo, "branch", "-D", branch)
    return {"ok": True, "state": "cleaned"}


def reap(meta: dict, delete_branch: bool = True) -> dict[str, Any]:
    """Fauche IDEMPOTENTE d'un bac à sable TERMINAL : `worktree remove --force` + `prune`,
    puis (option) suppression de la branche agent. Sûr même si le worktree ou la branche
    n'existent déjà plus (reap rejoué = no-op) : on ignore les returncode, on ne lit jamais
    d'exception. Diffère de `cleanup` (post-merge nominal) par le `prune` explicite qui purge
    les entrées d'administration git laissées par un worktree disparu à la main."""
    repo = meta.get("repo_root")
    wt = meta.get("worktree")
    branch = meta.get("branch")
    if repo and wt:
        _arreter_ses_processus(wt)
        _run(repo, "worktree", "remove", "--force", wt)
        if Path(wt).exists():
            shutil.rmtree(wt, ignore_errors=True)
        _run(repo, "worktree", "prune")
    if _branch_is_disposable(meta, delete_branch) and repo and branch:
        _run(repo, "branch", "-D", branch)
    return {"ok": True, "state": "reaped"}
