# [desc] Outil Environment : l'agent demande LUI-MÊME son worktree, son venv, et son intégration finale. [/desc]
"""L'environnement à la demande.

Avant, l'isolation d'un agent était tranchée par son PARENT au spawn (paramètre `isolation`) :
il devait deviner, avant que l'enfant ait vu la tâche, si celle-ci allait écrire, ou toucher aux
dépendances. Résultat mesuré sur le parc : des worktrees provisionnés « au cas où » pour des
agents qui ne faisaient que lire, et à l'inverse des agents en worktree SANS venv déclenchant un
`uv sync` qui fabriquait ~1 Go de venv que personne n'avait demandé.

Ici, c'est l'agent qui demande, au moment où il découvre qu'il en a besoin :
  - `status`    : où suis-je, dans quel dépôt, sur quelle branche, avec quel venv (lecture seule) ;
  - `worktree`  : provisionne un worktree dédié et M'Y DÉPLACE (os.chdir dans MON process) ;
  - `venv`      : un venv dédié dans ce worktree, pour toucher aux dépendances sans casser
                  le venv de base (partagé avec le serveur et tous les autres agents) ;
  - `integrate` : merge la branche de travail dans sa base, et SIGNALE un conflit au lieu de
                  le résoudre en douce.

Deux points durs, traités ici :

1. **L'agent est un process séparé.** Son `cwd` est fixé au `Popen` par le runner du serveur ;
   pour le déplacer en vol il faut un `os.chdir()` DANS ce process — c'est ce que fait `_adopt`.
2. **Le serveur doit être prévenu**, sinon une reprise (`/continue`, respawn) repart au mauvais
   endroit. On emprunte le canal agent → serveur qui existe déjà : le dossier IPC exposé par
   `config["_web_agent_dir"]` (le même que `plan_mode` utilise pour `plan.md`). On y dépose un
   `env.json` via `web_v2.runtime.env_signal`, relu côté serveur au recalage du cwd.

Les imports de `web_v2` sont LAZY, dans les fonctions : cet outil est enregistré dans TOUT
process agent, y compris en CLI sans serveur, et `backend` ne doit pas dépendre de `web_v2`
à l'import.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..core.dossier_agent import aller, courant, poser_racine, poser_variables, variable
from ..core.tool_registry import ToolDef, register_tool

_ACTIONS = ("status", "worktree", "venv", "integrate", "cleanup")

# Worktree intégré dans CE process, en attente de rangement par l'agent. `integrate` quitte le
# worktree et POP `BOUZECODE_WORKTREE_ROOT` (le cwd disparaîtrait sous ses pieds) : sans cette
# mémoire, `cleanup` ne saurait plus QUOI supprimer une fois le merge fait.
_PENDING_CLEANUP: dict = {}

# Un `integrate` réussi ramène ce process dans le dépôt PARTAGÉ. Un process resté vivant (TUI,
# pool chaud) enchaîne le tour suivant sans respawn, donc sans `rehome_agent_cwd` : il
# travaillerait dans l'arbre partagé. Ce drapeau demande une ré-isolation au prochain tour.
_A_REISOLER: dict = {}


def reisoler_avant_tour(config: dict) -> str:
    """Au début d'un tour : si le tour précédent a intégré (donc quitté) son worktree, en
    obtenir un neuf, comme `Environment(action='worktree')`. Rend le message à montrer à
    l'agent, ou "" s'il n'y avait rien à faire. Ne lève jamais : un échec reste un message."""
    if not _A_REISOLER.pop("apres_integration", False):
        return ""
    root = variable("BOUZECODE_WORKTREE_ROOT")
    if root and os.path.isdir(root):
        return ""
    try:
        message = _worktree(config)
    except Exception as exc:  # pragma: no cover - git en erreur
        message = f"Worktree NON obtenu : {exc}. Tu restes dans {courant()}."
    return ("[Ré-isolation automatique : ton worktree précédent a été intégré au tour d'avant] "
            + message)

_SCHEMA = {
    "name": "Environment",
    "description": (
        "Ton environnement de travail, demandé quand tu découvres qu'il te manque. "
        "status : où tu es (dépôt, branche, venv). worktree : worktree git dédié où ton cwd "
        "bascule pour de bon (idempotent ; avant d'écrire du code). venv : venv dédié (uv sync) "
        "que visent les Bash suivants, avant de toucher aux dépendances. integrate : merge ta "
        "branche dans sa base, tests verts (conflits nommés, rien d'écrasé ; le worktree est "
        "conservé). cleanup : retire worktree et branche, refusé tant que rien n'est intégré."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": "status | worktree | venv | integrate | cleanup",
            },
        },
        "required": ["action"],
    },
}


# ── Contexte de l'agent ────────────────────────────────────────────────────

def _ipc_dir(config: dict) -> str:
    """Dossier IPC agent → serveur. Même canal que `plan_mode` (`config['_web_agent_dir']`)."""
    return str(config.get("_web_agent_dir") or os.environ.get("BOUZECODE_WEB_IPC_DIR") or "")


def _agent_id(config: dict) -> str:
    ipc = _ipc_dir(config)
    return Path(ipc).stem if ipc else ""


def _identity() -> tuple[str, str]:
    """slug/ticket_id du ticket porteur, posés en env au spawn par `runner._ticket_env`."""
    return (os.environ.get("BOUZECODE_TICKET_SLUG", ""),
            os.environ.get("BOUZECODE_TICKET_ID", ""))


def _same_path(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _branch_of(path: str) -> str:
    from ...web_v2.services.work import worktrees
    try:
        return worktrees.current_branch(path) or "?"
    except Exception:  # pragma: no cover - git absent / dépôt cassé
        return "?"


def _signal(config: dict, **fields) -> None:
    """Prévient le serveur du nouvel environnement. Best-effort : un échec disque ne doit pas
    faire échouer une action qui, elle, a réussi (le pire cas est une reprise mal recalée)."""
    ipc = _ipc_dir(config)
    if not ipc:
        return
    try:
        from ...web_v2.runtime import env_signal
        env_signal.write(ipc, **fields)
    except Exception:  # pragma: no cover - pas de serveur / disque en erreur
        pass


def adopt_cwd(path: str, config: dict, worktree: bool = False) -> None:
    """Déplace CE process dans `path` et le fait savoir (env + signal IPC).

    L'agent est un process séparé dont le cwd a été fixé au `Popen` par le serveur : `os.chdir`
    suffit pour le tour courant, le signal IPC sert au recalage à la reprise (`/continue`, respawn).

    `worktree=True` pose en plus `BOUZECODE_WORKTREE_ROOT`, la variable que le prompt système
    relit à chaque tour pour armer le contrat « tu travailles dans un worktree isolé » : la poser
    suffit à ce que le contrat apparaisse au tour suivant, sans respawn. À réserver aux VRAIS
    worktrees d'agent — entrer dans un projet (LoadProjectConfig(cd=true)) n'est pas s'isoler, et
    l'annoncer serait un faux positif qui ferait croire à l'agent qu'il a déjà sa branche."""
    aller(path)
    if worktree:
        poser_racine(path)
        _signal(config, cwd=path, worktree_root=path)
    else:
        _signal(config, cwd=path)


def _rebaser_extraits(config: dict, racine: str, worktree: str) -> str:
    """Les extraits gardés sous `racine` pointent désormais le worktree (cf. snippet_rebase)."""
    from ..context_manager.snippet_rebase import rebaser_extraits
    from ..context_manager.state import resolve_context_state
    rebases = rebaser_extraits(resolve_context_state(config), racine, worktree)
    if not rebases:
        return ""
    return (f"\n{rebases} extrait(s) déjà gardé(s) dans ta note pointent maintenant ce worktree "
            f"(fichiers identiques) : ne les relis pas.")


def _adopt(path: str, config: dict) -> None:
    """Adoption d'un worktree d'agent : cwd + contrat d'isolation."""
    adopt_cwd(path, config, worktree=True)


def _ticket(slug: str, ticket_id: str):
    from ...web_v2.services.work import tickets
    return tickets.get_ticket(slug, ticket_id)


_NO_GIT = (
    "Refusé : ce n'est pas un dépôt git ({path}) — il n'y a rien à isoler, et aucune branche à "
    "intégrer. Travaille sur place."
)


# ── Hors ticket : le déclencheur est le DÉPÔT GIT, pas le ticket ───────────
#
# Un agent lancé à la main (TUI/CLI) n'a ni BOUZECODE_TICKET_SLUG ni _ID : le serveur ne les
# pose qu'au spawn d'un ticket. Ça ne change rien au processus — dès qu'on va ÉCRIRE du code
# dans un dépôt git, on s'isole sur une branche et on intègre à la fin. Le ticket n'est qu'un
# enrichissement (idempotence via le store, commentaires, `done_agent`).

def _repo_root(path: str) -> str:
    from ...web_v2.services.work import repos
    try:
        return repos.repo_root(path) or ""
    except Exception:  # pragma: no cover - git absent
        return ""


def _main_repo_and_base(path: str) -> tuple[str, str]:
    """Dépôt PRINCIPAL et branche qui y est sortie : PREMIÈRE entrée de `git worktree list`.

    `repos.repo_root(<worktree>)` rendrait le worktree lui-même ; ce qu'il faut ici, c'est
    l'arbre partagé où le merge doit atterrir, et la base à viser (elle n'est pas forcément
    `develop` : d'autres dépôts travaillent sur `master`)."""
    import subprocess  # local, comme les autres imports de ce module
    try:
        out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=path,
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:  # pragma: no cover - git absent
        return ("", "")
    repo, base = "", ""
    for line in out.splitlines():
        if line.startswith("worktree ") and not repo:
            #  git rend des chemins à `/` même sous Windows : on les rend natifs, sinon les
            #  chemins composés (`C:/x/depot\.venv`) ne ressemblent à rien de ce que l'agent tape.
            repo = os.path.normpath(line[len("worktree "):].strip())
        elif line.startswith("branch ") and repo and not base:
            base = line[len("branch "):].strip()
            base = base[len("refs/heads/"):] if base.startswith("refs/heads/") else base
        elif not line.strip() and repo:
            break  # fin de la première entrée
    return (repo, base)


#  Jeu de caractères accepté par `worktrees.provision` pour un nom de worktree/branche : on
#  normalise PAREIL, sinon on vérifierait la disponibilité d'un nom que git ne verra jamais.
_NOM_SAIN = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
_NOMS_ESSAYES = 3


def _nom_sain(nom: str) -> str:
    return "".join(c if c in _NOM_SAIN else "-" for c in nom)


def _nom_agent_libre(repo_root: str, base: str) -> str:
    """Un nom dont NI la branche `agent/<nom>` NI le dossier de worktree ne sont déjà pris.

    Sans ça, tout agent sans dossier IPC s'appelait « solo » : le premier créait `agent/solo`,
    tous les suivants se voyaient refuser l'isolation et repartaient dans l'arbre partagé. On
    ne touche JAMAIS à la branche existante (son sort appartient à `discard_stale` /
    `dispatch.reisolate`) : on se décale à côté."""
    from ...web_v2.services.work import branch_rescue, worktrees

    base = _nom_sain(base) or "agent"
    dossier = Path(worktrees.WORKTREES_DIR) / Path(repo_root).name
    candidats = [base] + [f"{base}-{n}" for n in range(2, 100)]
    candidats.append(f"{base}-{os.urandom(3).hex()}")
    for candidat in candidats:
        pris_branche = bool(branch_rescue.branch_tip(repo_root, f"agent/{candidat}"))
        if not pris_branche and not (dossier / candidat).exists():
            return candidat
    return candidats[-1]


def _provisionner_isole(repo_root: str, base: str) -> tuple[str, str]:
    """Provisionne un worktree sur une branche LIBRE, en dérivant le nom si besoin.

    Rend `(chemin, "")` en cas de succès, `("", motif)` sinon. Un nom déjà pris N'EST PAS un
    motif de refus — renvoyer l'agent dans l'arbre partagé est exactement ce que l'outil existe
    pour empêcher. On ne re-tente que la collision (deux agents qui démarrent en même temps
    peuvent choisir le même nom entre la vérification et le `git worktree add`) ; tout autre
    échec (git en erreur, aucune branche de base résoluble) est remonté tel quel."""
    from ...web_v2.services.work import worktrees

    motif = "provisionnement échoué"
    for _ in range(_NOMS_ESSAYES):
        name = _nom_agent_libre(repo_root, base)
        try:
            meta = worktrees.provision(repo_root, name)
        except Exception as exc:  # git en erreur…
            return "", str(exc)
        chemin = (meta or {}).get("worktree") or ""
        if (meta or {}).get("ok") and chemin and os.path.isdir(chemin):
            return chemin, ""
        motif = (meta or {}).get("error") or "provisionnement échoué"
        if "already exists" not in motif:
            break
    return "", motif


_SEUIL_LENTEUR_S = 10.0


def _note_lenteur(duree: float) -> str:
    """Rappel quand le provisionnement a traîné. Mesure (session 1f5b8d96) : ~1800 fichiers
    écrits en ~28 s à froid (16 ms/fichier, inspection Windows Defender) contre 2,2 s à chaud."""
    if duree < _SEUIL_LENTEUR_S:
        return ""
    return (f"\nProvisionnement : {duree:.0f} s. Cause habituelle sous Windows : l'antivirus "
            f"inspecte chacun des ~1800 fichiers écrits — /doctor donne la commande d'exclusion "
            f"(à lancer en administrateur).")


def _worktree_without_ticket(config: dict) -> str:

    cwd = courant()
    repo_root = _repo_root(cwd)
    if not repo_root:
        return _NO_GIT.format(path=cwd)

    existing = variable("BOUZECODE_WORKTREE_ROOT")
    if existing and os.path.isdir(existing):
        # Idempotence : deux appels de suite ne créent pas deux worktrees.
        if _same_path(existing, cwd):
            return (f"Déjà en place : tu travailles dans ton worktree dédié {existing} "
                    f"(branche {_branch_of(existing)}). Rien à faire.")
        _adopt(existing, config)
        return (f"Worktree déjà provisionné — je t'y ai déplacé : {existing} "
                f"(branche {_branch_of(existing)}).")

    #  Le nom est UNIQUE par agent, et dérivé s'il est déjà pris : deux agents lancés sans
    #  ticket dans le même dépôt obtiennent deux branches, jamais un refus partagé.
    import time
    debut = time.monotonic()
    new_cwd, motif = _provisionner_isole(repo_root, _agent_id(config) or "solo")
    lenteur = _note_lenteur(time.monotonic() - debut)
    if not new_cwd:
        return (f"Worktree NON obtenu : {motif}. Tu restes dans l'arbre partagé {cwd} — ta "
                f"livraison n'est sur aucune branche d'agent.")
    _adopt(new_cwd, config)
    extraits = _rebaser_extraits(config, repo_root, new_cwd)
    return (f"Worktree dédié créé et adopté : {new_cwd} (branche {_branch_of(new_cwd)}).\n"
            f"Ton cwd EST ce dossier maintenant : Bash, Read/Write/Edit et les chemins relatifs "
            f"y pointent. À la fin, quand tes tests sont verts, appelle "
            f"Environment(action='integrate') pour merger — sans ça ton travail reste sur la "
            f"branche et personne ne le voit." + extraits + lenteur)


_AUTO_PUSH_BRANCHES = ("develop",)


def _pousser_base(repo_root: str, base: str = "") -> str:
    """Push the integration base to origin when it is develop (user rule: develop is
    ALWAYS pushed after an integration). Best-effort: never raises, returns a sentence
    to append to the integration message ("" when nothing to push)."""
    import subprocess

    if not repo_root or not os.path.isdir(repo_root):
        return ""
    try:
        if not base:
            base = subprocess.run(
                ["git", "-C", repo_root, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
        if base not in _AUTO_PUSH_BRANCHES:
            return ""
        r = subprocess.run(
            ["git", "-C", repo_root, "push", "origin", base],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, the merge already succeeded
        return f" Push de {base or 'la base'} vers origin impossible ({exc}) : pousse-le à la main."
    if r.returncode != 0:
        tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["?"])[-1]
        return f" Push de {base} vers origin ÉCHOUÉ ({tail}) : pousse-le à la main."
    return f" {base} est poussé sur origin."


def _integrate_without_ticket(config: dict) -> str:
    from ...web_v2.services.work import worktrees

    root = variable("BOUZECODE_WORKTREE_ROOT")
    if not root or not os.path.isdir(root):
        return ("Rien à intégrer : tu n'as pas de worktree dédié (tu travailles dans l'arbre "
                "partagé — il n'y a pas de branche à merger).")
    repo_root, base = _main_repo_and_base(root)
    if not repo_root:
        return _NO_GIT.format(path=root)
    meta = {
        "repo_root": repo_root,
        "worktree": root,
        "branch": _branch_of(root),
        "base": base or worktrees.default_branch(repo_root),
    }

    previous_cwd = courant()
    # Se déplacer AVANT : un merge propre supprime le worktree, c'est-à-dire le cwd de ce process.
    if os.path.isdir(repo_root):
        aller(repo_root)
        poser_racine("")
        _signal(config, cwd=repo_root, worktree_root="")

    result = worktrees.integrate(meta) or {}

    if result.get("ok"):
        _PENDING_CLEANUP.clear()
        _PENDING_CLEANUP.update(meta)
        _A_REISOLER["apres_integration"] = True
        pushed = _pousser_base(repo_root, meta["base"])
        return (f"Merge propre : ta branche {meta['branch']} est intégrée dans {meta['base']}."
                f"{pushed} "
                f"Tu es maintenant dans {courant()}. Ton worktree {root} est CONSERVÉ : "
                f"range-le MAINTENANT avec Environment(action='cleanup') — c'est toi qui nettoies "
                f"derrière toi, personne ne le fera à ta place.")

    # Échec : le worktree est CONSERVÉ. On y retourne, c'est là que l'agent doit travailler.
    if os.path.isdir(previous_cwd):
        aller(previous_cwd)
        if _same_path(previous_cwd, root):
            poser_racine(previous_cwd)
            _signal(config, cwd=previous_cwd, worktree_root=previous_cwd)

    return _echec_integration(result, meta.get("branch") or "")


#  Échecs d'intégration déjà rendus dans CETTE session (un process = un agent) : la même
#  signature deux fois de suite, c'est un modèle qui boucle sur un échec déterministe.
_ECHECS_INTEGRATION: dict[tuple[str, str], int] = {}
_SEUIL_BOUCLE = 2


def _echec_integration(result: dict, branche: str) -> str:
    """Message d'échec honnête : « relance-la telle quelle » SEULEMENT si ça peut marcher."""
    etat = result.get("state") or "refus"
    if etat == "conflict":
        files = ", ".join(result.get("files") or []) or "?"
        message = (f"CONFLIT au merge — rien n'a été écrasé, la base est intacte et ton worktree "
                   f"est conservé. Fichiers en conflit : {files}. Résous-les dans {courant()}, "
                   f"commite, puis rappelle Environment(action='integrate').")
    else:
        message = (f"Intégration non aboutie ({etat}) : "
                   f"{result.get('error') or 'raison non précisée'}. Ton worktree est conservé, "
                   f"rien n'est perdu.")
        if result.get("retryable"):
            message += " Tu peux la relancer telle quelle."
        else:
            remede = result.get("remede") or "corrige d'abord la cause ci-dessus"
            message += (f" La relancer telle quelle échouera de la même façon — {remede}.")
    signature = (etat, result.get("error") or "")
    _ECHECS_INTEGRATION[signature] = _ECHECS_INTEGRATION.get(signature, 0) + 1
    if _ECHECS_INTEGRATION[signature] >= _SEUIL_BOUCLE and etat != "conflict":
        message += (f"\n⚠️ C'est au moins la {_ECHECS_INTEGRATION[signature]}e fois que cette "
                    f"intégration échoue exactement ainsi. N'insiste pas : termine avec FinalAnswer "
                    f"en indiquant que ta branche {branche or '(la tienne)'} est prête à être "
                    f"intégrée par ton parent (ou l'utilisateur), et pourquoi l'intégration "
                    f"automatique a échoué.")
    return message


# ── Actions ────────────────────────────────────────────────────────────────

def _status(config: dict) -> str:
    from ...web_v2.services.work import repos
    cwd = courant()
    slug, ticket_id = _identity()
    root = repos.repo_root(cwd) or ""
    worktree_root = variable("BOUZECODE_WORKTREE_ROOT")
    lines = [
        f"cwd            : {cwd}",
        f"dépôt git      : {root or '(aucun — pas un dépôt git)'}",
        f"branche        : {_branch_of(root) if root else '-'}",
        f"worktree dédié : {worktree_root or '(aucun — arbre partagé)'}",
        f"venv           : {variable('VIRTUAL_ENV') or '(celui du système/base)'}",
        f"ticket         : {slug + '/' + ticket_id if (slug and ticket_id) else '(aucun)'}",
    ]
    return "\n".join(lines)


def _worktree(config: dict) -> str:
    slug, ticket_id = _identity()
    if not (slug and ticket_id):
        return _worktree_without_ticket(config)
    from ...web_v2.services.work import projects as work_projects, provisioning
    from ...web_v2.services.work.isolation import WORKTREE

    ticket = _ticket(slug, ticket_id)
    if not ticket:
        return f"Refusé : ticket {slug}/{ticket_id} introuvable dans le store."

    meta = ticket.get("worktree") or {}
    existing = meta.get("worktree") or ""
    from ...web_v2.services.work.integration import deja_integre
    if existing and os.path.isdir(existing) and not (meta.get("retire_at") or deja_integre(ticket)):
        # Idempotence : deux appels de suite ne créent pas deux worktrees.
        if _same_path(existing, courant()):
            return (f"Déjà en place : tu travailles dans ton worktree dédié {existing} "
                    f"(branche {_branch_of(existing)}). Rien à faire.")
        _adopt(existing, config)
        return (f"Worktree déjà provisionné pour ce ticket — je t'y ai déplacé : {existing} "
                f"(branche {_branch_of(existing)}).")

    project_path = provisioning._path_of(slug, work_projects.list_projects())
    if not project_path:
        return (f"Refusé : le projet '{slug}' n'est pas enregistré côté serveur, impossible de "
                f"savoir quel dépôt isoler.")
    import time
    debut = time.monotonic()
    try:
        new_cwd = provisioning._provision_worktree(
            slug, ticket, project_path, isolation=WORKTREE)
    except Exception as exc:  # branche demandée impossible, git en erreur…
        return f"Worktree NON obtenu : {exc}. Tu restes dans {courant()}."
    lenteur = _note_lenteur(time.monotonic() - debut)
    if not new_cwd or _same_path(new_cwd, project_path):
        return ("Worktree NON obtenu : soit ce n'est pas un dépôt git, soit le provisionnement a "
                "échoué (le motif est posé en commentaire sur le ticket). Tu restes dans l'arbre "
                f"partagé {courant()} — ta livraison n'est sur aucune branche d'agent.")
    _adopt(new_cwd, config)
    extraits = _rebaser_extraits(config, project_path, new_cwd)
    return (f"Worktree dédié créé et adopté : {new_cwd} (branche {_branch_of(new_cwd)}).\n"
            f"Ton cwd EST ce dossier maintenant : Bash, Read/Write/Edit et les chemins relatifs y "
            f"pointent. À la fin, quand tes tests sont verts, appelle "
            f"Environment(action='integrate') pour merger — sans ça ton travail reste sur la "
            f"branche et personne ne le voit." + extraits + lenteur)


def _venv(config: dict) -> str:
    root = variable("BOUZECODE_WORKTREE_ROOT")
    if not (root and os.path.isdir(root)):
        return ("Refusé : pas de venv dédié sans worktree dédié. Appelle d'abord "
                "Environment(action='worktree') — fabriquer un venv dans l'arbre principal, c'est "
                "exactement le dégât qu'on évite (il est partagé avec le serveur et les autres "
                "agents).")
    from ...web_v2.services.work import worktrees
    from ...web_v2.runtime import venv_env

    slug, ticket_id = _identity()
    ticket = _ticket(slug, ticket_id) if (slug and ticket_id) else None
    # Repli sur le dépôt que le worktree DÉSIGNE lui-même : un agent lancé à la main n'a pas
    # de ticket, et un repo_root vide privait `_setup_venv` du relinkage des deps editables.
    repo_root = (((ticket or {}).get("worktree") or {}).get("repo_root")
                 or worktrees.main_repo_root(Path(root)))

    issue = worktrees._setup_venv(Path(root), repo_root)
    if issue == worktrees.VENV_SKIPPED:
        return (f"Pas de venv : {root} ne contient pas de pyproject.toml (ce n'est pas un projet "
                f"Python). Rien n'a été touché.")
    if issue != worktrees.VENV_OK:
        return (f"Échec de `uv venv` / `uv sync --all-extras` dans {root}. Ton environnement est "
                f"INCHANGÉ (le venv de base n'a pas été touché) — regarde les dépendances du "
                f"projet avant de réessayer.")
    venv_path = str(Path(root) / ".venv")
    # Les Bash SUIVANTS de CET agent en héritent (os.environ, ou ses variables en process TUI).
    poser_variables(venv_env.base_venv_env(venv_path))
    _signal(config, base_venv=venv_path)
    return (f"Venv dédié prêt : {venv_path}. Tes prochains Bash le visent (VIRTUAL_ENV, "
            f"UV_PROJECT_ENVIRONMENT, PATH préfixé) et le venv de base est intact.\n"
            f"Pour répercuter dans l'env principal : commite pyproject.toml / uv.lock, puis "
            f"integrate. Jamais l'inverse — on ne casse l'env partagé qu'après preuve que ça "
            f"marche ici.")


_GESTE_INTEGRER = ("intégrer maintenant livrerait sans leur travail, qui arriverait ensuite "
                   "par-dessus le tien")
_GESTE_RANGER = "ranger ton worktree et ta branche retirerait la base où ils s'intègrent"


#  Intégrer ou ranger pendant qu'un enfant travaille : son travail arriverait par-dessus le
#  mien, ou n'aurait plus de base où s'intégrer (essai 3, 2026-09-24).
_GESTES_GARDES = {"integrate": _GESTE_INTEGRER, "cleanup": _GESTE_RANGER}


def _refus_enfants_actifs(geste: str, config: dict) -> str:
    """Refus d'un geste gardé tant qu'un enfant travaille (voir `multi_agent.enfants`)."""
    if not geste:
        return ""
    from ..multi_agent.enfants import refus_si_enfants_actifs
    return refus_si_enfants_actifs(geste, config)


def _integrate(config: dict) -> str:
    slug, ticket_id = _identity()
    if not (slug and ticket_id):
        return _integrate_without_ticket(config)
    from ...web_v2.services.work import integration

    ticket = _ticket(slug, ticket_id)
    if not ticket:
        return f"Refusé : ticket {slug}/{ticket_id} introuvable dans le store."
    meta = ticket.get("worktree") or {}
    if not meta:
        return ("Rien à intégrer : aucun worktree n'est rattaché à ce ticket (tu as travaillé "
                "dans l'arbre partagé — il n'y a pas de branche à merger).")

    previous_cwd = courant()
    repo_root = meta.get("repo_root") or ""
    # Se déplacer AVANT : un merge propre supprime le worktree, c'est-à-dire le cwd de ce process.
    if repo_root and os.path.isdir(repo_root):
        aller(repo_root)
        poser_racine("")
        _signal(config, cwd=repo_root, worktree_root="")

    result = integration.integrate_ticket(slug, ticket, done_agent=_agent_id(config),
                                          cleanup=False)

    if result.get("ok"):
        _PENDING_CLEANUP.clear()
        _PENDING_CLEANUP.update(meta)
        _A_REISOLER["apres_integration"] = True
        pushed = _pousser_base(repo_root, meta.get("base") or "")
        return (f"Merge propre : ta branche est intégrée dans sa base.{pushed} Tu es maintenant dans "
                f"{courant()}. Ton worktree {meta.get('worktree')} est CONSERVÉ : range-le "
                f"MAINTENANT avec Environment(action='cleanup') — c'est toi qui nettoies derrière "
                f"toi, personne ne le fera à ta place.")

    # Échec : le worktree est CONSERVÉ. On y retourne, c'est là que l'agent doit travailler.
    if os.path.isdir(previous_cwd):
        aller(previous_cwd)
        if _same_path(previous_cwd, meta.get("worktree") or ""):
            poser_racine(previous_cwd)
            _signal(config, cwd=previous_cwd, worktree_root=previous_cwd)

    return _echec_integration(result, meta.get("branch") or "")


def _cleanup(config: dict) -> str:
    """Range l'atelier APRÈS le merge : c'est l'agent qui le demande, jamais l'outil dans son dos.

    Refusé tant que rien n'est intégré : un worktree non mergé porte du travail que personne
    d'autre n'a, le supprimer serait la seule perte irréversible de tout ce flux."""
    from ...web_v2.services.work import tickets as work_tickets, worktrees

    slug, ticket_id = _identity()
    meta: dict = {}
    ticket = None
    if slug and ticket_id:
        ticket = _ticket(slug, ticket_id)
        if not ticket:
            return f"Refusé : ticket {slug}/{ticket_id} introuvable dans le store."
        meta = dict(ticket.get("worktree") or {})
        if not meta:
            return ("Rien à ranger : aucun worktree n'est rattaché à ce ticket (tu as travaillé "
                    "dans l'arbre partagé).")
        from ...web_v2.services.work.integration import deja_integre
        if meta.get("retire_at"):
            return "Déjà rangé : ce worktree a été retiré, il n'y a plus rien à nettoyer."
        if not deja_integre(ticket):
            return ("Refusé : ton travail n'est pas intégré (état du ticket "
                    f"'{ticket.get('state') or 'inconnu'}'). Ranger maintenant DÉTRUIRAIT du code "
                    "que personne d'autre n'a. Appelle d'abord Environment(action='integrate').")
    else:
        meta = dict(_PENDING_CLEANUP)
        if not meta:
            if variable("BOUZECODE_WORKTREE_ROOT"):
                return ("Refusé : ton travail n'est pas intégré — tu es encore dans ton worktree. "
                        "Ranger maintenant DÉTRUIRAIT du code que personne d'autre n'a. Appelle "
                        "d'abord Environment(action='integrate').")
            return "Rien à ranger : aucun worktree intégré n'est en attente de nettoyage."

    # Ne jamais supprimer le worktree sous ses propres pieds : `integrate` a déjà ramené le
    # process dans le dépôt principal, mais un appel direct pourrait encore y être.
    repo_root = meta.get("repo_root") or ""
    if repo_root and os.path.isdir(repo_root) and _same_path(courant(), meta.get("worktree") or ""):
        aller(repo_root)
        poser_racine("")
        _signal(config, cwd=repo_root, worktree_root="")

    try:
        worktrees.cleanup(meta)
    except Exception as exc:  # pragma: no cover - git en erreur
        return (f"Nettoyage non abouti : {exc}. Rien n'est perdu (le merge est déjà fait), "
                f"c'est re-tentable.")

    _PENDING_CLEANUP.clear()
    if ticket is not None:
        from datetime import datetime
        work_tickets.poser(slug, ticket, worktree={**meta, "retire_at": datetime.now().isoformat(
            timespec="seconds")})
    branch = meta.get("branch") or "?"
    return (f"Rangé : worktree {meta.get('worktree')} retiré et branche {branch} supprimée. "
            f"Tu es dans {courant()} — l'ancien chemin n'existe plus, n'y écris plus.")


_HANDLERS = {"status": _status, "worktree": _worktree, "venv": _venv, "integrate": _integrate,
             "cleanup": _cleanup}


#  Ignorés par git, donc absents d'un worktree neuf, mais sans intérêt pour l'agent.
_BRUIT_IGNORE = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                 ".bouzecode", ".bouzecode", ".nano_claude", ".idea", ".vscode"}


def _ignores_absents(repo: str, worktree: str) -> list[str]:
    """Entrées du dépôt principal, ignorées par git, qui n'existent pas dans le worktree."""
    import subprocess
    absents = [e for e in sorted(os.listdir(repo)) if e not in _BRUIT_IGNORE
               and not os.path.exists(os.path.join(worktree, e))]
    if not absents:
        return []
    return subprocess.run(["git", "check-ignore", *absents], cwd=repo, capture_output=True,
                          text=True, timeout=30).stdout.split()


def _absents_du_worktree(worktree: str) -> str:
    """Dossiers ignorés par git (`.venv`, `.cache`, données…) présents dans le dépôt principal
    mais absents du worktree. Rapport docs/reduction_tokens §2.1 : 5 tours perdus à les
    chercher après la (re)création d'un worktree. On le DIT, avec les chemins à utiliser ; on ne
    lie rien (un lien vers le venv de base laisserait `uv run` le resynchroniser)."""
    repo, _base = _main_repo_and_base(worktree)
    ignores = _ignores_absents(repo, worktree) if repo and not _same_path(repo, worktree) else []
    if not ignores:
        return ""
    chemins = ", ".join(os.path.join(repo, e) for e in ignores[:8])
    venv = variable("VIRTUAL_ENV") or "(venv de base du serveur)"
    return (f"\nAbsents de ce worktree car ignorés par git (restés dans le dépôt principal) : "
            f"{chemins}. Lis-les à ces chemins (copie-les ici si tu dois les modifier). Le python "
            f"actif reste celui du venv de base ({venv}) ; un venv à toi : "
            f"Environment(action='venv').")


def _environment(params: dict, config: dict) -> str:
    action = (params.get("action") or "").strip().lower()
    handler = _HANDLERS.get(action)
    if handler is None:
        return f"action inconnue '{action}' — attendu l'une de : {', '.join(_ACTIONS)}."
    refus = _refus_enfants_actifs(_GESTES_GARDES.get(action, ""), config)
    if refus:
        return refus
    try:
        resultat = handler(config)
    except (AttributeError, ImportError) as exc:
        # Vécu le 2026-09-21 : « module 'venv_env' has no attribute 'pinned_python_spec' »
        # alors que la fonction existait sur disque depuis douze jours — le process avait
        # chargé un module AVANT la mise à jour et un autre APRÈS. L'agent en a conclu « action
        # cassée sur ce parc » ; le dire autrement lui évite de l'abandonner pour de bon.
        return (f"Environment(action='{action}') a échoué : {type(exc).__name__}: {exc}\n"
                f"Cause la plus probable : ce process bouzecode tourne sur un mélange de code "
                f"ancien (chargé à son démarrage) et récent (lu sur disque depuis). Redémarre "
                f"l'agent (ou le serveur web) puis relance l'action ; ce n'est pas un défaut "
                f"permanent du poste.")
    except subprocess.TimeoutExpired as exc:
        commande = " ".join(str(a) for a in (exc.cmd or []))[:200]
        return (f"Environment(action='{action}') : `{commande}` n'a pas répondu en "
                f"{exc.timeout:.0f}s. Vérifie l'état avec `git status` (et `git worktree list`) "
                f"dans le dépôt concerné avant de relancer l'action.")
    worktree = variable("BOUZECODE_WORKTREE_ROOT")
    if action in ("status", "worktree") and worktree and _same_path(worktree, courant()):
        resultat += _absents_du_worktree(worktree)
    return resultat


register_tool(ToolDef(
    name="Environment",
    schema=_SCHEMA,
    func=_environment,
    # `status` est en lecture seule mais les trois autres déplacent le process, écrivent le
    # store du ticket et mergent : l'outil entier est déclaré écrivain, et JAMAIS parallélisable
    # (un chdir concurrent d'un autre outil du même batch serait indébuggable).
    read_only=False,
    concurrent_safe=False,
))
