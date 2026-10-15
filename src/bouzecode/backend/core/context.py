from bouzecode.paths import project_dir as bouzecode_project_dir
from bouzecode.paths import data_dir as bouzecode_data_dir
import os
import subprocess
from pathlib import Path
from datetime import datetime

from ._embedded_data import (
    SYSTEM_PROMPT_TEMPLATE,
    WINDOWS_PLATFORM_HINTS,
    PLAN_MODE_TEMPLATE,
)


def checked_out_branch(cwd: str = "") -> str:
    """Branche RÉELLEMENT sortie dans `cwd` (défaut : le répertoire courant), "" hors dépôt.

    C'est la vérité terrain, celle que git rapporte — pas ce que le ticket AFFIRME. Un ticket
    peut dire « ta branche de travail = agent/X » alors que le worktree provisionné porte
    `agent/Y` : l'agent travaillait alors correctement au mauvais endroit et le rapportait de
    bonne foi. Le contrat de worktree cite désormais CE nom.

    `cwd` inexistant -> "" : `subprocess.run` LÈVE sur un cwd absent, et cet appel se fait
    depuis la construction du system prompt. Un BOUZECODE_WORKTREE_ROOT périmé (worktree
    moissonné puis rasé) tuait donc l'agent avant son premier tour, au lieu de le priver
    d'une seule phrase du contrat."""
    if cwd and not Path(cwd).is_dir():
        return ""
    result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=cwd or None, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip() if result.returncode == 0 else ""


_BRANCH_MEMO: dict[str, str] = {}


def _git_branch_memo() -> str:
    """Branche sortie dans le cwd, mémorisée par répertoire (un `git` par cwd et par process).

    `Environment(action='worktree')` change le cwd : la clé change avec lui, donc la branche
    du worktree apparaît d'elle-même au tour suivant."""
    cwd = os.getcwd()
    if cwd not in _BRANCH_MEMO:
        try:
            _BRANCH_MEMO[cwd] = checked_out_branch()
        except Exception:  # noqa: BLE001 — hors dépôt / git absent : pas de branche, pas d'échec
            _BRANCH_MEMO[cwd] = ""
    return _BRANCH_MEMO[cwd]


_DEPOT_MEMO: dict[str, str] = {}


def _depot_du_worktree() -> str:
    """Dépôt PRINCIPAL quand le cwd est un worktree lié, "" sinon (mémorisé par cwd).

    Les worktrees d'agent vivent sous `~/.bouzecode/worktrees/<dépôt>/<id>` : sans ce nom, un
    parent a lu la partie avant `/.bouzecode/` — le HOME — comme « son dépôt », et l'a dicté
    à son enfant (essai du 2026-09-24)."""
    cwd = os.getcwd()
    if cwd not in _DEPOT_MEMO:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir",
                 "--show-toplevel"], cwd=cwd, capture_output=True, text=True,
                encoding="utf-8", errors="replace").stdout.split("\n")
            depot = Path(out[0].strip()).parent if len(out) > 1 and out[1].strip() else None
            linked = depot is not None and depot != Path(out[1].strip())
            _DEPOT_MEMO[cwd] = str(depot) if linked else ""
        except Exception:  # noqa: BLE001 — hors dépôt / git absent : rien à dire
            _DEPOT_MEMO[cwd] = ""
    return _DEPOT_MEMO[cwd]


def get_platform_hints() -> str:
    """Return platform-specific shell hints. Windows-only for now; empty elsewhere."""
    import platform
    if platform.system() == "Windows":
        return WINDOWS_PLATFORM_HINTS
    return ""


def get_skills_section() -> str:
    """Instructions Projets + Skills.

    `LoadProjectConfig` est la porte d'entrée : lui seul sait ce qu'un projet
    apporte. Le prompt ne nomme aucun projet — le registre change, et l'outil
    liste lui-même les projets voisins quand le chemin n'en est pas un.
    """
    return """
# Projets et skills
- Avant de travailler dans un dossier : `LoadProjectConfig(path=..., cd=true s'il n'est pas ton dossier de départ)`, une fois, puis Snippet du résultat. `AddProject`/`DismissProject` seulement pour transcrire la réponse de l'utilisateur (sans bloquer : pose la question en fin de travail).
- Charge une skill **AVANT** d'agir (`SkillResearch(query="mots-clés")`, puis `Skill(name=...)`). Le code a raison contre une skill ; skill fausse → corrige son `.md` dans le même tour (date `updated` à aujourd'hui).
- Pars du principe que des sessions précédentes ont déjà traité un problème proche : chaque recherche dans le code sur un sujet neuf (`FindCode`, `Grep`, `Glob`) part avec un `SkillResearch` dans le même lot, en mots-clés de langage naturel qui décrivent le problème (« certificat base expiré », « coût sessions focus ») plutôt qu'en identifiants. Même chose dès qu'une erreur ou un sujet nouveau apparaît. SkillResearch cherche dans le nom, la description, les déclencheurs et le corps des skills.
- Un enseignement qui t'a coûté plusieurs tours et resservira (où sont les données, comment s'y connecter, piège d'environnement, méthode d'analyse) va dans une skill projet avant ta clôture, sans demander : enrichis la skill existante la plus proche, sinon crée-en une.
"""


def render_profile_skills(names: list[str]) -> str:
    """Preload the named skills' content into the prompt (an agent's declared skills are
    part of its equipment, not something to discover). Falls back to the generic
    SkillResearch() instruction when no name resolves."""
    from bouzecode.backend.tools.skill.loader import load_skills

    by_name = {s.name: s for s in load_skills()}
    blocks = []
    for name in names:
        skill = by_name.get(name)
        if skill is None:
            continue
        desc = (skill.description or "").strip()
        blocks.append(f"## {skill.name}\n{desc}\n\n{(skill.prompt or '').strip()}".strip())
    if not blocks:
        return get_skills_section()
    body = "\n\n---\n\n".join(blocks)
    return (
        "\n\n# Skills (préchargées pour cet agent)\n\n"
        "Ces skills font partie de ton équipement et sont déjà chargées ci-dessous — "
        "applique-les directement, inutile d'appeler SkillResearch()/Skill().\n\n" + body + "\n"
    )


def entrees_de_memoire() -> dict[str, str]:
    """Les entrées de mémoire visibles (~/.bouzecode/memory/ puis .bouzecode/memory/ du cwd) :
    {chemin du fichier : ligne d'index « - [nom](fichier) — description »}. Un fichier sans
    `name:` dans son en-tête YAML n'est pas listé."""
    entrees = {}
    for dossier in (bouzecode_data_dir() / "memory", bouzecode_project_dir(Path.cwd()) / "memory"):
        if not dossier.is_dir():
            continue
        for fichier in sorted(dossier.glob("*.md")):
            ligne = _ligne_d_index(fichier)
            if ligne:
                entrees[str(fichier)] = ligne
    return entrees


def _ligne_d_index(fichier: Path) -> str:
    texte = fichier.read_text(encoding="utf-8", errors="ignore")
    if not texte.startswith("---"):
        return ""
    parties = texte.split("---", 2)
    if len(parties) < 3:
        return ""
    nom = description = ""
    for ligne in parties[1].splitlines():
        if ligne.startswith("name:"):
            nom = ligne[5:].strip()
        elif ligne.startswith("description:"):
            description = ligne[12:].strip()
    return f"- [{nom}]({fichier.name}) — {description}" if nom else ""


def get_memory_context() -> str:
    """La mémoire visible à l'instant, une ligne par entrée."""
    return "\n".join(entrees_de_memoire().values())


def build_system_prompt_parts(config: dict | None = None) -> tuple[str, str]:
    """Return (stable, volatile) halves of the system prompt.

    Stable: identity, guidelines, platform hints, CLAUDE.md, memory, skills.
    Volatile: session context (date, cwd, git), plan mode block.

    The boundary is where an Anthropic-style cache_control breakpoint belongs.
    """
    import platform
    from ..agent.providers.registry import model_uses_native_tools
    model = config.get("model", "") if config else ""
    # The examples teach a PROTOCOL, so they follow the protocol switch — not the
    # provider. Keyed on the provider, an Anthropic model in native mode was still
    # taught XML it would never emit (~1 454 wasted characters every request).
    if model_uses_native_tools(model, config or {}):
        from ._embedded_data import TOOL_EXAMPLES_JSON as _examples
    else:
        from ._embedded_data import TOOL_EXAMPLES_XML as _examples
    template = SYSTEM_PROMPT_TEMPLATE
    if config and config.get("lean_turn_protocol"):
        from .lean_prompt import apply_lean_turn_protocol
        template = apply_lean_turn_protocol(template)
    stable = (
        template
        .replace("{platform_hints}", "")
        .replace("{claude_md}", "")
        .replace("{platform}", platform.system())
        .replace("{tool_examples}", _examples)
    )
    # Figée au premier appel de la session quand il y en a une (memoire_figee.py) : modifiée
    # ensuite, elle ne change plus le préfixe en cache, une note de harnais le dit.
    from ..context_manager.memoire_figee import memoire_de_l_appel
    memory_ctx = memoire_de_l_appel(config.get("_context_state") if config else None)
    if memory_ctx:
        stable += f"\n\n# Memory\nYour persistent memories:\n{memory_ctx}\n"
    # An agent's declared skills are part of its equipment: preload their bodies.
    # Otherwise emit the generic SkillResearch()/Skill() discovery instruction.
    profile_skills = config.get("_profile_skills") if config else None
    stable += render_profile_skills(profile_skills) if profile_skills else get_skills_section()

    # Active agent typology selected in-session via /agent <name>.
    agent_extra = config.get("_agent_system_prompt_extra", "") if config else ""
    if agent_extra:
        stable += f"\n\n# Active agent profile\n{agent_extra.strip()}\n"

    volatile = build_session_context(config)

    return stable, volatile


def build_system_prompt(config: dict | None = None) -> str:
    """Prompt complet (stable + contexte de session), pour l'affichage et les aperçus.

    Pour un tour d'agent, passer plutôt `build_stable_system_prompt` : `dispatch.stream`
    rajoute lui-même le contexte de session EN DERNIER, après le préfixe stable et la note,
    et le recalcule à chaque appel (cwd et branche changent avec `Environment`)."""
    stable, volatile = build_system_prompt_parts(config)
    return stable + volatile


def build_stable_system_prompt(config: dict | None = None) -> str:
    """La moitié STABLE seule (noyau, skills, navigation) : identique d'un tour à l'autre et
    d'un agent à l'autre du même profil, donc partageable par le cache."""
    return build_system_prompt_parts(config)[0]


_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def harness_repo(root: Path | None = None) -> tuple[Path | None, Path | None]:
    """(racine du code de bouzecode, dépôt principal si cette racine est un worktree lié).

    Lu sur disque, sans `git` : `.git` FICHIER (« gitdir: <principal>/.git/worktrees/<nom> »)
    désigne un worktree lié. (None, None) si `root` n'est pas un projet (installation en
    site-packages : aucun dépôt à annoncer)."""
    root = Path(root) if root else Path(__file__).resolve().parents[4]
    if not (root / "pyproject.toml").is_file():
        return None, None
    git = root / ".git"
    if git.is_file():
        try:
            ligne = git.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return root, None
        if ligne.startswith("gitdir:"):
            gitdir = Path(ligne.split(":", 1)[1].strip())
            if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
                return root, gitdir.parent.parent.parent
    return root, None


def _ligne_code_du_harnais() -> str:
    """« où est le code de bouzecode », sauf si le cwd y est déjà (l'info serait redondante).

    Constat sur 70 sessions réelles : pour une tâche « dans bouzecode », l'agent cherchait
    `PycharmProjects\\bouzecode` alors que le dépôt est `PycharmProjects\\demo\\bouzecode` —
    2 à 5 tours perdus par session, et un autre dépôt modifié une fois."""
    racine, depot = harness_repo()
    if racine is None:
        return ""
    try:
        Path.cwd().resolve().relative_to(racine)
        return ""
    except (ValueError, OSError):
        pass
    ligne = f"- Code de bouzecode (ce harnais, si la tâche porte sur lui) : {racine}"
    if depot is not None:
        ligne += f" — worktree du dépôt {depot}"
    return ligne + ".\n"


def build_session_context(config: dict | None = None) -> str:
    """Le contexte de session, court, placé EN DERNIER dans le prompt système.

    Audit du 2026-09-24 : placé au milieu du préfixe (avant le profil), il cassait le cache à
    chaque redémarrage de process et rendait le préfixe différent d'un agent à l'autre. Il
    ne porte plus ni `git status` ni les derniers commits : ils changent sans cesse, et l'agent
    les obtient avec `git log` / `git status` quand il en a besoin. La doctrine d'environnement
    (worktree / venv / integrate) vit dans le profil `default`, avec le reste du processus git.

    2026-10-07 : pour un tour d'agent, `dispatch` n'envoie plus ce texte recalculé mais celui du
    premier appel de la session (`contexte_fige`) ; un changement ultérieur part en note de
    harnais. Cette fonction reste la vérité de l'instant.
    """
    return "".join(situation_de_session(config)["segments"].values())


def situation_de_session(config: dict | None = None) -> dict:
    """Le contexte de session en morceaux nommés (`segments`, dans l'ordre du texte) avec les
    valeurs brutes qui le fondent (`repertoire`, `branche`, `worktree`) : `contexte_fige`
    compare deux situations morceau par morceau pour rédiger sa note."""
    import platform
    now = datetime.now()
    branch = _git_branch_memo()
    segments = {
        "entete": "\n# Contexte de session\n",
        "date": (f"- Date : {now.strftime('%Y-%m-%d')} ({_JOURS[now.weekday()]}). "
                 f"Plateforme : {platform.system()}.\n"),
        "repertoire": f"- Répertoire : {Path.cwd()}" + (f" — branche {branch}" if branch else "")
                      + ".\n",
    }
    depot = _depot_du_worktree()
    if depot:
        segments["depot"] = f"- Dépôt git : {depot} (le répertoire ci-dessus en est un worktree).\n"
    segments["harnais"] = _ligne_code_du_harnais()

    # Contrat EXPLICITE pour un agent tournant dans un worktree ISOLÉ. Anciennement préfixé au
    # prompt user (dispatch._worktree_contract) — il pollue la lecture du ticket ; il vit
    # désormais ici, dans le system prompt. Armé par l'env BOUZECODE_WORKTREE_ROOT (posée au
    # spawn par le runner). Rend visible la règle du worktree et autorise l'action hors
    # worktree ordonnée par le ticket.
    #
    # 2026-07-28 : la formule « autorisé mais signalé » a été retirée. Le guard hors-worktree
    # qui produisait ce signal a été supprimé — sa trace out_of_worktree.jsonl n'avait AUCUN
    # lecteur, et le spawn_validator/mark_run_out_of_worktree_notified que la doc annonçait
    # n'a jamais existé. Promettre au modèle une surveillance inexistante lui apprend à
    # escompter le reste du prompt ; la vraie conséquence (non récolté) suffit et est vraie.
    #
    # 2026-08-23 : la variable n'est plus posée qu'au spawn. `Environment(action='worktree')` la
    # pose EN VOL dans le process de l'agent. 2026-10-07 : le contrat posé en vol arrive par la
    # note de harnais de `contexte_fige` (le bloc envoyé reste celui du premier appel).
    worktree_root = os.environ.get("BOUZECODE_WORKTREE_ROOT", "") or ""
    if worktree_root:
        segments["worktree"] = (
            f"- Tu travailles dans un worktree isolé : {worktree_root}. Seul ce qui est écrit ICI "
            "est récolté ; ce que tu écris ailleurs n'est PAS récolté (autorisé seulement si le "
            "ticket l'ordonne : git -C, consigne cross-repo).\n"
        )
        # La branche EFFECTIVE, dite explicitement. Un ticket peut annoncer « ta branche de
        # travail = agent/X » alors que le provisioning a sorti agent/Y : l'agent livrait alors
        # au bon endroit techniquement, mais RAPPORTAIT le mauvais — un compte rendu trompeur
        # sans que personne mente. Nommer la branche réelle rend la contradiction visible AVANT
        # le rapport, pas après.
        branche_de_travail = checked_out_branch(worktree_root)
        if branche_de_travail:
            segments["branche_de_travail"] = (
                f"- Ta branche de travail est `{branche_de_travail}`. Si ton ticket en nomme une "
                "autre, signale la contradiction dans ton rapport : ta livraison n'ira pas où on "
                "l'attend.\n"
            )

    if config and config.get("permission_mode") == "plan":
        segments["plan"] = PLAN_MODE_TEMPLATE.format(plan_file=config.get("_plan_file", ""))

    return {"repertoire": str(Path.cwd()), "branche": branch, "worktree": worktree_root,
            "segments": {cle: texte for cle, texte in segments.items() if texte}}


# Re-exported for backward compat: call sites (e.g. dispatch.py) import these
# from core.context. The implementations live in core.profile_extra.
from .profile_extra import (  # noqa: E402
    get_agent_profile_extra,
    get_default_agent_profile_extra,
)
