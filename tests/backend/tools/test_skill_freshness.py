# [desc] Tests du bandeau de fraîcheur : silence si rien n'a bougé, alerte graduée sinon. [/desc]
"""Une skill est une piste datée.

Rien ne disait à un agent qu'une skill pouvait être périmée. Ces tests décrivent
le signal qu'il reçoit désormais à l'ouverture : rien du tout quand la skill est
fraîche, un avertissement gradué sinon.
"""
import pytest

from bouzecode.backend.tools.skill import freshness
from bouzecode.backend.tools.skill.parsing import _parse_skill_file
from tests.git_modeles import ecrire_commits
from tests.git_modeles import git as _git


def _construire(depot):
    _git(depot, "init", "-q", "-b", "main")
    _git(depot, "config", "user.email", "t@t.t")
    _git(depot, "config", "user.name", "t")
    code = depot / "src"
    code.mkdir()
    (code / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(depot, "add", "-A")
    _git(depot, "commit", "-q", "-m", "initial")


@pytest.fixture()
def depot(tmp_path, depot_modele):
    """Un dépôt git avec une skill datée qui couvre un dossier de code."""
    return depot_modele(tmp_path, _construire)


def _ecrire_skill(depot, updated, covers):
    dossier = depot / ".bouzecode" / "skills" / "demo"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "skill.md"
    entete = ["---", "name: demo", 'description: "ALWAYS LOAD WHEN ..."']
    if updated:
        entete.append(f"updated: {updated}")
    if covers:
        entete.append(f"covers: [{', '.join(covers)}]")
    entete.append("---")
    chemin.write_text("\n".join(entete) + "\n\n# Corps\n", encoding="utf-8")
    return _parse_skill_file(chemin)


def _commits(depot, combien, dossier="src", fichier="module.py", prefixe="change"):
    """`combien` commits sur `main` touchant `dossier/fichier`, en un seul lancement git.
    `git log` — seul juge de la dérive — ne lit que l'historique, pas l'arbre de travail."""
    ecrire_commits(depot, "main", "main",
                   [(f"{prefixe} {index}", {f"{dossier}/{fichier}": f"x = {index}\n"})
                    for index in range(combien)])


def test_les_champs_updated_et_covers_sont_lus(depot):
    skill = _ecrire_skill(depot, "2026-07-31", ["src", "docs"])

    assert skill.updated == "2026-07-31"
    assert skill.covers == ["src", "docs"]


def test_une_skill_sans_date_ne_declenche_rien(depot):
    """On ne harcèle pas sur ce qu'on ne sait pas mesurer."""
    skill = _ecrire_skill(depot, "", ["src"])

    assert freshness.drift(skill) == -1
    assert freshness.banner(skill) == ""


def test_une_skill_sans_chemins_couverts_ne_declenche_rien(depot):
    skill = _ecrire_skill(depot, "2026-07-31", [])

    assert freshness.banner(skill) == ""


def test_aucune_derive_aucun_bandeau(depot):
    """Sans dérive, pas de bruit : sinon le signal ne veut plus rien dire."""
    skill = _ecrire_skill(depot, "2099-01-01", ["src"])

    assert freshness.drift(skill) == 0
    assert freshness.banner(skill) == ""


def test_une_derive_faible_demande_de_verifier(depot):
    skill = _ecrire_skill(depot, "2000-01-01", ["src"])
    _commits(depot, 3)

    bandeau = freshness.banner(skill)

    assert "FRAÎCHEUR" in bandeau
    assert "vérifie ce sur quoi tu t'appuies" in bandeau
    assert "CORRIGE la skill dans ce même tour" in bandeau


def test_une_forte_derive_degrade_la_skill_en_piste(depot):
    skill = _ecrire_skill(depot, "2000-01-01", ["src"])
    _commits(depot, 12)

    bandeau = freshness.banner(skill)

    assert "PISTE" in bandeau
    assert "pas comme une vérité" in bandeau
    # Le bandeau donne le VRAI compte de commits, pas le seuil. On lit la phrase du compte :
    # tester le bandeau entier dépendait du chemin tmp de pytest (« pytest-1022 » contient « 10 »).
    import re
    assert re.search(r"(\d+) commits", bandeau).group(1) != str(freshness.PISTE_THRESHOLD)


def test_un_chemin_couvert_inexistant_est_ignore(depot):
    """Une skill qui cite un dossier supprimé ne doit pas mesurer n'importe quoi."""
    skill = _ecrire_skill(depot, "2000-01-01", ["dossier_supprime"])

    assert freshness.drift(skill) == -1
    assert freshness.banner(skill) == ""


def test_seuls_les_chemins_couverts_comptent(depot):
    """Des commits ailleurs dans le dépôt ne rendent pas la skill périmée.

    On compare avant/après : la valeur absolue inclut le commit initial, qui a
    bien créé `src`. Ce qui compte, c'est qu'elle ne bouge pas.
    """
    skill = _ecrire_skill(depot, "2000-01-01", ["src"])
    avant = freshness.drift(skill)

    _commits(depot, 5, dossier="ailleurs", fichier="autre.py", prefixe="ailleurs")

    assert freshness.drift(skill) == avant
