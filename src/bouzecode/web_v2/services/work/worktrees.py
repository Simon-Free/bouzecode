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

import logging
import re
import shutil
import subprocess
import threading
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

WORKTREES_DIR = Path.home() / ".bouzecode" / "worktrees"
_IDENT = ["-c", "user.name=bouzecode", "-c", "user.email=bouzecode@local"]

# Ce que `harvest` refuse DÉLIBÉRÉMENT de committer : `.agents.lock` est le lock
# d'orchestration du harness, jamais du produit. La MÊME pathspec sert au staging et au
# constat de saleté résiduelle — sinon un simple lock oublié ferait crier « livraison non
# commitée » sur un ticket parfaitement récolté.
_NOT_PRODUCT = [":(exclude,glob)**/.agents.lock", ":(exclude,glob).agents.lock"]

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


def _run(cwd: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # encoding forcé UTF-8 : git émet de l'UTF-8, mais `text=True` décoderait avec la locale
    # (cp1252 sous Windows) → un diff avec du non-ASCII (accents FR, emojis) lève
    # UnicodeDecodeError, stdout devient None et harvest/validate/merge cassent (500).
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


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
    """Branche par défaut du dépôt (origin/HEAD, sinon main/master/develop, sinon HEAD)."""
    ref = _out(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if ref:
        return ref.rsplit("/", 1)[-1]
    for cand in ("develop", "main", "master"):
        if _run(repo_root, "rev-parse", "--verify", cand).returncode == 0:
            return cand
    return _out(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "main"


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
    try:
        subprocess.run([uv, "venv"], cwd=worktree, capture_output=True, timeout=120)
        sync = subprocess.run([uv, "sync", "--all-extras"], cwd=worktree, capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return VENV_FAILED
    return VENV_OK if sync.returncode == 0 else VENV_FAILED


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
    `git worktree add` coûte 50 s à vide pour 1209 fichiers suivis (antivirus temps réel qui
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
    if _out(wt, "status", "--porcelain"):
        # `.agents.lock` = lock d'orchestration du harness (état local par worktree,
        # référence les scripts jetables temp_*), JAMAIS du produit. `add -A` l'aspirerait
        # comme tout untracked → il finit committé dans le merge d'agent (source du KO
        # validateur). On l'exclut du staging via pathspec magic (aveugle au reste du
        # travail). Les fichiers temp=True, eux, vivent déjà HORS du worktree (scratch dir,
        # cf. tools/ops/scratch.py) : git ne les voit pas, rien à exclure côté temp.
        _run(wt, "add", "-A", "--", *_NOT_PRODUCT)
        commit_args = ["commit", "-m", f"agent: {title}"[:72]]
        if body.strip():
            commit_args += ["-m", body]
        res = _run(wt, *_IDENT, *commit_args)
        committed = res.returncode == 0
    diff = _out(wt, "diff", f"{meta['base']}...{meta['branch']}") or ""
    # SHA du tip FIGÉ juste après le commit auto, atomiquement avec le diff : c'est l'état
    # EXACT que le diff décrit. Le validateur doit ancrer sa relecture sur CE sha (git diff
    # base...<sha>), pas sur HEAD (ref mouvante) — sinon un re-commit du codeur pendant que le
    # validateur tourne, ou une re-validation, lui fait juger un autre état que celui livré
    # (faux négatif KO3 : verdict rendu sur un commit ≠ SHA réellement livré).
    return {"committed": committed, "diff": diff, "head": _out(wt, "rev-parse", meta["branch"]) or "",
            "dirty": dirty_files(meta),
            "files": (_out(wt, "diff", "--name-only", f"{meta['base']}...{meta['branch']}") or "").splitlines()}


def _conflict_marker_files(repo_root: str, ref: str) -> list[str]:
    """Fichiers de `ref` portant des marqueurs de conflit non résolus (`<<<<<<< ` / `>>>>>>> `).
    Un agent peut committer une résolution ratée : on refuse alors d'intégrer du code cassé
    dans la branche de référence (cf. incident c1d0206 : app.py mergé avec marqueurs → serveur mort)."""
    out = _out(repo_root, "grep", "-lE", r"^(<<<<<<< |>>>>>>> )", ref) or ""
    return [ln.split(":", 1)[-1] for ln in out.splitlines() if ln]


def _conflict_residue(repo_root: str) -> list[str]:
    """Fichiers de l'ARBRE DE TRAVAIL principal qui portent un conflit NON résolu : entrées
    non-mergées de l'index (`git ls-files -u`, état UU après un stash pop conflictuel) OU
    marqueurs `^<<<<<<< ` dans le contenu du working tree (`git grep` SANS ref = arbre de
    travail courant). Distinct de `_conflict_marker_files` qui grep un REF committé — ici on
    inspecte l'arbre vivant servi tel quel (cf. incident : conversations.js laissé en UU après
    un `stash pop` de restauration en conflit → JS cassé, page /conversations morte)."""
    unmerged = _out(repo_root, "ls-files", "-u") or ""
    paths = {ln.split("\t", 1)[-1] for ln in unmerged.splitlines() if "\t" in ln}
    marked = _out(repo_root, "grep", "-lE", r"^<<<<<<< ") or ""
    paths.update(ln for ln in marked.splitlines() if ln)
    return sorted(paths)


def integrate(meta: dict) -> dict[str, Any]:
    """Intègre la branche agent dans la base, SÉRIALISÉ globalement par base de merge.

    Le verrou `_lock_for_base(repo, base)` garantit qu'un seul ticket merge dans une base
    donnée à la fois → supprime la course entre N merges concurrents visant le même `develop`
    (plus de faux needs_attention transitoires). Le vrai travail est dans `_integrate_locked`."""
    with _lock_for_base(meta["repo_root"], meta["base"]):
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
        return {"ok": False, "state": "needs_attention",
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
        return {"ok": False, "state": "needs_attention",
                "error": f"'{base}' a avancé pendant l'intégration — relancer l'intégration"}

    if _out(repo, "rev-parse", "--abbrev-ref", "HEAD") == base:
        return _merge_into_live_base(repo, branch, base)

    upd = _run(repo, "branch", "-f", base, branch)
    if upd.returncode != 0:
        return {"ok": False, "state": "error", "error": upd.stderr.strip()}
    return {"ok": True, "state": "integrated"}


def _merge_into_live_base(repo: str, branch: str, base: str) -> dict[str, Any]:
    """Intègre `branch` quand `base` est CHECKOUT dans l'arbre principal (cas courant : serveur ET
    agents partagent ce seul checkout). git NE PEUT PAS avancer une branche checkout dont l'arbre
    porte des modifs non commitées → on REFUSAIT (needs_attention), donc le moindre artefact
    orphelin (test non commité, fichier laissé par la flotte) bloquait TOUS les merges (« les
    merges automatiques ne se déclenchent pas »). On met l'arbre sale de côté (stash tracked +
    untracked), on merge, puis on restaure : AUCUN travail perdu, le merge n'est plus otage.

    La branche descend déjà de la base (is-ancestor vérifié en amont) → le merge --no-ff ne peut
    pas conflicter sur le CONTENU. Seul le stash pop peut conflicter si le sale touchait les mêmes
    fichiers ; dans ce cas le merge EST intégré et le sale reste SAUF dans la pile `git stash`."""
    stashed = False
    if _tracked_dirty(repo) or _has_untracked(repo):
        st = _run(repo, *_IDENT, "stash", "push", "--include-untracked",
                  "-m", f"bouzecode-auto-integrate {branch}")
        if st.returncode != 0:
            return {"ok": False, "state": "needs_attention",
                    "error": f"stash de l'arbre sale avant merge impossible : {st.stderr.strip()}"}
        stashed = "No local changes" not in (st.stdout or "")
    merge = _run(repo, *_IDENT, "merge", "--no-ff", "--no-edit", branch)
    if merge.returncode != 0:
        _run(repo, "merge", "--abort")
        if stashed:
            _run(repo, "stash", "pop")
        return {"ok": False, "state": "needs_attention", "error": merge.stderr.strip()}
    if stashed:
        pop = _run(repo, "stash", "pop")
        if pop.returncode != 0:
            # Restauration en conflit : le WIP humain touchait un fichier que le merge vient de
            # réécrire. Un `stash pop` conflictuel LAISSE l'arbre en état UU + marqueurs `<<<<<<<`
            # ET conserve le stash dans la pile. On NE peut PAS laisser ça : le fichier (souvent
            # du JS servi tel quel) casserait la page en ligne. On réaligne l'arbre principal sur
            # l'état mergé (`reset --hard HEAD`, zéro marqueur/UU) — le WIP n'est PAS perdu, il
            # reste intact dans le stash `bouzecode-auto-integrate {branch}` qu'on remonte.
            marked = _conflict_residue(repo)
            _run(repo, "reset", "--hard", "HEAD")
            stash_list = _out(repo, "stash", "list") or ""
            msg = f"bouzecode-auto-integrate {branch}"
            stash_ref = next((ln.split(":", 1)[0] for ln in stash_list.splitlines()
                              if msg in ln), "")
            print(f"[integrate] restore en conflit sur {branch} : arbre principal réaligné sur "
                  f"l'état mergé ; WIP humain SAUF dans {stash_ref or 'la pile git stash'} "
                  f"(fichiers : {', '.join(marked) or '?'})", flush=True)
            residue = _conflict_residue(repo)
            if residue:  # défense en profondeur : le reset DOIT avoir tout nettoyé
                return {"ok": False, "state": "needs_attention",
                        "error": f"restauration en conflit et nettoyage incomplet de l'arbre "
                                 f"principal ({', '.join(residue[:4])}) — intervention manuelle"}
            return {"ok": True, "state": "integrated",
                    "restore_conflict": {"branch": branch, "stash_ref": stash_ref,
                                         "stash_message": msg, "files": marked}}
    residue = _conflict_residue(repo)
    if residue:  # défense en profondeur : aucune intégration ne doit laisser un conflit en ligne
        return {"ok": False, "state": "needs_attention",
                "error": f"conflit résiduel dans l'arbre principal après intégration "
                         f"({', '.join(residue[:4])}) — intervention manuelle requise"}
    return {"ok": True, "state": "integrated"}


def _branch_is_disposable(meta: dict, delete_branch: bool) -> bool:
    """Peut-on supprimer la branche de ce bac à sable ? NON pour un travail EN PLACE : la
    branche n'appartient pas au ticket, elle PRÉEXISTAIT et porte la livraison attendue —
    la faucher détruirait exactement ce qu'on venait d'y déposer."""
    return delete_branch and not meta.get("in_place")


def cleanup(meta: dict, delete_branch: bool = True) -> dict[str, Any]:
    """Supprime le worktree (+venv) et la branche agent. À n'appeler qu'après intégration."""
    repo, wt, branch = meta["repo_root"], meta["worktree"], meta["branch"]
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
        _run(repo, "worktree", "remove", "--force", wt)
        if Path(wt).exists():
            shutil.rmtree(wt, ignore_errors=True)
        _run(repo, "worktree", "prune")
    if _branch_is_disposable(meta, delete_branch) and repo and branch:
        _run(repo, "branch", "-D", branch)
    return {"ok": True, "state": "reaped"}
