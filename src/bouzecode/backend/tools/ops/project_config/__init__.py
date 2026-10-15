# [desc] LoadProjectConfig : équipe l'agent d'un projet, ou dit ce qu'il y a dedans quand ce n'en est pas un. [/desc]
"""La porte d'entrée d'un projet.

Trois réponses possibles, et une seule question posée au plus une fois dans une vie :

- **désigné** — l'utilisateur l'a enregistré : on rend ses skills, ses outils, l'accès à son code ;
- **écarté** — l'utilisateur a déjà dit que ce n'en est pas un : on ne redemande rien,
  on liste ce qu'il contient ;
- **inconnu** — on liste ce qu'il contient, et on pose la question une fois.

Le `.bouzecode/` d'un dossier est enregistré comme source de skills **dès qu'il
existe**, indépendamment du registre : « être un projet » et « être équipé » sont
deux choses différentes. Un worktree n'est jamais un projet à enregistrer, mais
il est équipé — et c'est ce qui le rend autonome sur sa branche.
"""
from __future__ import annotations

from bouzecode.paths import project_dir as bouzecode_project_dir
from pathlib import Path

from ....core.paths import add_extra_dir, register_loaded_project
from . import briefing, plugins, registry


def _children_block(root: Path) -> list[str]:
    """Les projets désignés situés dans ce dossier — ce qui fait avancer l'agent."""
    children = registry.registered_children(root)
    if not children:
        return ["Aucun projet enregistré à l'intérieur."]
    lines = [f"Projets enregistrés à l'intérieur ({len(children)}) :"]
    for child in children:
        lines.append(f"  - {child['name']:24s} {briefing.equipment_summary(Path(child['path']))}")
        lines.append(f"    LoadProjectConfig(path=\"{child['path']}\")")
    return lines


def _elsewhere_block(root: Path) -> list[str]:
    others = registry.other_projects(root)
    if not others:
        return []
    return ["", "Autres projets enregistrés : " + ", ".join(p["name"] for p in others)]


def _question_block(root: Path) -> list[str]:
    return [
        "",
        "La question n'a jamais été posée pour ce dossier. Pose-la à l'utilisateur avec",
        f'AskUserQuestion : « {root} est-il un projet à part entière ? »',
        "  - Oui  → AddProject(name=..., path=...)",
        "  - Non  → DismissProject(path=...)   (la question ne reviendra plus)",
        "Ne réponds JAMAIS à sa place : c'est lui qui désigne ce qui est un projet.",
        "Si les projets ci-dessus suffisent à ton travail, sers-t'en et pose la question",
        "à la fin plutôt que de bloquer dessus.",
    ]


def _equipment(root: Path, name: str, header: str) -> list[str]:
    """Le briefing, si le dossier porte un `.bouzecode/` — indépendant du registre.

    Les outils du projet sont branchés ICI, pas seulement listés : c'est la
    différence entre un plugin utilisable et un dossier qu'on décrit.
    """
    if not (bouzecode_project_dir(root)).is_dir():
        return []
    add_extra_dir(bouzecode_project_dir(root))
    # Declares "the agent also works in `root`": without it the project's own skills are
    # collected then dropped by the scope filter when the cwd is the parent monorepo, so
    # SkillResearch never showed them and Skill(name=...) answered "not found".
    register_loaded_project(root)
    wired, failures = plugins.wire(root)
    # Un `.bouzecode/` peut ne contenir que des profils ou des agents. Annoncer
    # « équipé » puis lister zéro skill et zéro outil serait un faux positif :
    # dans ce cas on se tait.
    if not (briefing.project_skills(root) or wired or failures):
        return []
    return ["", briefing.render(root, name, header, wired, failures),
            "", "→ Snippet ce résultat, sinon tu le perds au tour suivant."]


def _load_project_config(path: str, config: dict | None = None, cd: bool = False) -> str:
    """Briefing d'un dossier, et — si `cd` — entrée DANS ce dossier.

    `cd` existe parce qu'un agent spawne dans le worktree du dépôt qui l'a lancé : sans
    déplacement, `Environment(action='worktree')` provisionnait dans CE dépôt-là et jamais dans
    le projet qu'on vient de charger. Opt-in : lire un projet reste sans effet de bord."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return f"Erreur : dossier introuvable — {root}"

    # Le venv que ses commandes utiliseront dans ce projet (règle du 2026-10-12 : celui du projet
    # où l'agent travaille). Avec `cd`, c'est effectif dès le Bash suivant, sans autre geste.
    from ..venv_du_projet import ligne_de_briefing
    briefing = f"{_briefing(root)}\n\n{ligne_de_briefing(str(root))}"
    if not cd:
        return briefing

    from ...environment import adopt_cwd
    adopt_cwd(str(root), config or {})
    entete = (
        f"[cwd déplacé] Tu travailles maintenant depuis {root} — Bash, chemins relatifs, "
        "Environment(action='worktree') et Environment(action='venv') visent ce dépôt, et tes "
        "commandes prennent le venv de ce projet (ligne « Venv » ci-dessous).\n"
        "Tu n'es PAS pour autant isolé : appelle Environment(action='worktree') si tu vas écrire."
    )
    return f"{entete}\n\n{briefing}"


def _briefing(root: Path) -> str:
    silence = registry.is_silent(root)
    if silence:
        equipment = _equipment(root, root.name, f"Dossier équipé ({silence}) : {root}")
        if equipment:
            return "\n".join(equipment).lstrip("\n")
        return (f"{root} est un {silence} : il n'y a pas lieu de l'enregistrer comme projet, "
                "et il n'apporte ni skill ni outil.")

    status, entry = registry.status_of(root)

    if status == registry.DESIGNATED:
        name = entry["name"]
        equipment = _equipment(root, name, f"Projet : {name}  ({root})")
        if equipment:
            return "\n".join(equipment).lstrip("\n")
        return (f"Projet : {name}  ({root})\n\n"
                "Ce projet n'a pas de dossier .bouzecode/ : ni skill, ni outil propre.\n"
                f"Code : {briefing.code_hint(root)}")

    if status == registry.DISMISSED:
        head = [f"{root} — tu as indiqué le {entry['dismissed_at'][:10]} que ce n'est pas un projet."]
        if entry.get("reason"):
            head.append(f"Raison notée : {entry['reason']}")
    else:
        head = [f"{root} n'est pas enregistré comme projet."]

    lines = head + [""] + _children_block(root) + _elsewhere_block(root)
    if status == registry.UNKNOWN:
        lines += _question_block(root)
    lines += _equipment(root, root.name, f"Ce dossier est tout de même équipé : {root}")
    return "\n".join(lines)
