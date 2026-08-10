# [desc] Conformity: every declared skill must survive the real loader, and none may silently shadow a builtin. [/desc]
"""Une compétence déclarée doit être chargeable — ou échouer BRUYAMMENT.

Le 2026-07-27, quatre skills de `~/.bouzecode/skills/` étaient jetées en silence par
le loader (deux sans champ `name:`, deux sans frontmatter du tout).
L'une d'elles était crue vivante
et utilisée comme telle. `_parse_skill_file` renvoie `None` et la skill n'existe
simplement plus : aucune erreur, aucune trace.

RÈGLE DE DÉTECTION — un fichier qui DÉCLARE une skill doit se résoudre via le vrai
loader. Déclarent une skill, et elles seules :
  - `<store>/<nom>.md`          (disposition plate)
  - `<store>/<nom>/skill.md`    (disposition imbriquée, convention Claude Code)

Les autres `.md` d'un dossier de skill (`connectors/azure.md`,
`database/tables.md`, …) sont des PAGES COMPAGNONS : de la documentation de
référence, sans frontmatter par construction. `_iter_skill_files` les remonte quand
même, et `_parse_skill_file` renvoie `None` pour elles — c'est CORRECT. Les traiter
comme des déclarations ferait 20 faux positifs sur cette machine seule.

DISPONIBILITÉ DES STORES — un choix assumé, parce que ce test lit le disque réel :
  - Stores DU DÉPÔT (`<repo>/.bouzecode/skills`, `<repo>/.claude/skills`) : versionnés,
    identiques pour tout le monde → **échec dur**. C'est la partie non négociable.
  - Stores PERSONNELS (`~/.bouzecode/skills`, `~/.claude/skills`) : propres à chaque
    machine → **avertissement explicite** avec le chemin fautif. Rougir la suite
    partagée à cause des fichiers locaux d'un collègue est le plus court chemin vers
    un test désactivé ; se taire est le bug qu'on répare. On avertit donc, fort.
Les deux chemins sont prouvés par des tests « mordants » sur des stores temporaires,
donc la garantie ne dépend pas de ce qui traîne sur la machine qui joue la suite.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from bouzecode.backend.core.config import CONFIG_DIR
from bouzecode.backend.tools.skill import loader as skill_loader
from bouzecode.backend.tools.skill.scope import resolve

from tests.backend.conformity.source_index import repo_root

REPO = repo_root()
REPO_STORES = [REPO / ".bouzecode" / "skills", REPO / ".claude" / "skills"]
PERSONAL_STORES = [CONFIG_DIR / "skills", Path.home() / ".claude" / "skills"]

# Exemptions EXPLICITES et DATÉES (2026-07-28). Une entrée dit « ce fichier masque un
# builtin VOLONTAIREMENT ». Vide aujourd'hui : aucun store ne masque de builtin.
INTENTIONAL_BUILTIN_OVERRIDES: dict[str, str] = {}


def declarations(store: Path) -> list[Path]:
    """Les fichiers qui DÉCLARENT une skill dans `store` (pas les pages compagnons)."""
    if not store.is_dir():
        return []
    found = [p for p in sorted(store.glob("*.md")) if p.name.upper() != "README.MD"]
    for child in sorted(store.iterdir()):
        if not child.is_dir():
            continue
        for candidate in (child / "skill.md", child / "SKILL.md"):
            if candidate.exists():
                found.append(candidate)
                break
    return found


def unloadable(store: Path) -> list[Path]:
    """Les déclarations que le VRAI loader réduit à None — nom et chemin conservés."""
    return [path for path in declarations(store)
            if skill_loader._parse_skill_file(path, source="project") is None]


def builtin_names() -> set[str]:
    return {skill.name for skill in skill_loader._BUILTIN_SKILLS}


def shadowed_builtins(stores: list[Path]) -> dict[str, str]:
    """{nom de builtin masqué: fichier qui le masque}."""
    shadows = {}
    for store in stores:
        for path in declarations(store):
            skill = skill_loader._parse_skill_file(path, source="user")
            if skill and skill.name in builtin_names():
                shadows[skill.name] = str(path)
    return shadows


def test_the_repo_owned_stores_declare_skills_to_check():
    """Garde-fou : un inventaire vide rendrait les assertions suivantes creuses.

    Le dépôt public ne versionne aucun store de skills (`.bouzecode/` et `.claude/`
    ne sont pas publiés) : il n'y a alors rien à échantillonner, et le garde-fou
    n'a plus d'objet — on le saute au lieu d'échouer.
    """
    total = sum(len(declarations(store)) for store in REPO_STORES)
    if total == 0:
        pytest.skip("aucun store de skills versionné dans ce dépôt")
    assert total > 5, f"seulement {total} skills déclarées dans le dépôt — non représentatif"


@pytest.mark.parametrize("store", REPO_STORES, ids=lambda p: p.parent.name)
def test_every_skill_declared_in_the_repository_loads(store):
    """Toute skill versionnée dans ce dépôt se résout vraiment, par nom et par chemin."""
    broken = unloadable(store)
    assert not broken, (
        f"Skills déclarées mais jetées en silence par le loader : "
        f"{[str(p) for p in broken]}. Cause habituelle : pas de champ `name:` ou pas de "
        "frontmatter `---` du tout. Elles sont absentes de SkillList() sans un mot."
    )


def test_broken_skills_in_a_personal_store_are_reported_not_hidden():
    """Les stores personnels ne rougissent pas la suite partagée, mais ne se taisent pas.

    Un fichier cassé ici est une perte réelle POUR CET UTILISATEUR : il est nommé dans
    un avertissement visible du rapport pytest, jamais avalé.
    """
    broken = sorted(path for store in PERSONAL_STORES for path in unloadable(store))
    if broken:
        warnings.warn(
            f"Skills déclarées et non chargeables dans un store personnel : "
            f"{[str(p) for p in broken]} — ajoute un frontmatter avec `name:`, sinon "
            "elles n'existent pas pour l'agent.",
            UserWarning, stacklevel=2,
        )
    # Le test ne juge pas la machine, mais ce qu'il RAPPORTE doit être exact : chaque
    # chemin cité est bien une déclaration que le vrai loader refuse.
    for path in broken:
        assert path.suffix == ".md" and skill_loader._parse_skill_file(path) is None


def test_no_skill_file_shadows_a_builtin():
    """Un builtin qui marche remplacé par un fichier périmé : personne ne le remarque.

    Les builtins équipent des profils livrés : en masquer un casse le profil en silence.
    Un remplacement VOULU s'écrit dans INTENTIONAL_BUILTIN_OVERRIDES, daté.
    """
    shadows = {name: where for name, where in shadowed_builtins(REPO_STORES + PERSONAL_STORES).items()
               if name not in INTENTIONAL_BUILTIN_OVERRIDES}
    assert not shadows, (
        f"Builtins masqués par un fichier de store : {shadows}. Renomme le fichier, "
        "ou déclare l'écrasement dans INTENTIONAL_BUILTIN_OVERRIDES avec sa raison."
    )


def test_a_declaration_without_a_name_field_is_caught(tmp_path):
    """Preuve que le test mord : on rejoue la panne de l'audit — un `skill.md` dont le
    frontmatter n'a pas de `name:` — et il doit ressortir par son chemin."""
    store = tmp_path / "skills"
    (store / "slide-template").mkdir(parents=True)
    culprit = store / "slide-template" / "skill.md"
    culprit.write_text("---\ndescription: gabarit de slides\n---\n\nCorps.\n", encoding="utf-8")
    (store / "sain.md").write_text("---\nname: sain\n---\n\nCorps.\n", encoding="utf-8")

    assert unloadable(store) == [culprit]


def test_a_declaration_without_any_frontmatter_is_caught(tmp_path):
    """L'autre moitié de la panne : aucun frontmatter du tout."""
    store = tmp_path / "skills"
    store.mkdir()
    culprit = store / "sql-macros.md"
    culprit.write_text("# Macros SQL\n\nDu texte, pas de frontmatter.\n", encoding="utf-8")

    assert unloadable(store) == [culprit]


def test_companion_pages_are_not_mistaken_for_declarations(tmp_path):
    """Preuve de non-hurlement : une page de référence sans frontmatter, à côté d'un
    `skill.md` valide, est de la documentation — pas une skill cassée."""
    store = tmp_path / "skills"
    (store / "connectors").mkdir(parents=True)
    (store / "connectors" / "skill.md").write_text(
        "---\nname: connectors\n---\n\nCorps.\n", encoding="utf-8")
    (store / "connectors" / "azure.md").write_text(
        "# Azure\n\nRéférence, sans frontmatter.\n", encoding="utf-8")

    assert unloadable(store) == []
    assert declarations(store) == [store / "connectors" / "skill.md"]


def test_a_user_skill_named_like_a_builtin_really_shadows_it(tmp_path):
    """Preuve par le vrai résolveur : une skill `user` homonyme d'un builtin gagne, et
    le builtin passe en `shadowed` — c'est exactement la perte silencieuse visée."""
    store = tmp_path / "skills"
    store.mkdir()
    (store / "commit.md").write_text(
        "---\nname: commit\ndescription: version locale périmée\n---\n\nCorps.\n",
        encoding="utf-8")

    intruder = skill_loader._parse_skill_file(store / "commit.md", source="user")
    resolution = resolve(list(skill_loader._BUILTIN_SKILLS) + [intruder], tmp_path)

    assert resolution.by_name("commit") is intruder
    assert [s.source for s in resolution.shadowed["commit"]] == ["builtin"]
    assert shadowed_builtins([store]) == {"commit": str(store / "commit.md")}
