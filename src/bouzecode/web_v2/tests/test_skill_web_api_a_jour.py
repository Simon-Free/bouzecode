"""La skill `bouzecode/web-api` est DÉRIVÉE du schéma d'API (spec ticketing §10, critère « Schéma ») :
le fichier versionné doit être exactement ce que produit `scripts/regenerer_skill_web_api.py`."""
from pathlib import Path

from bouzecode.web_v2.schema import skill
from bouzecode.web_v2.schema.application import schema_des_routes

RACINE = Path(__file__).resolve().parents[4]


def _texte_de_la_skill() -> str:
    return (RACINE / skill.CHEMIN_SKILL).read_bytes().decode("utf-8")


def test_la_skill_est_a_jour_du_schema():
    actuel = _texte_de_la_skill()

    assert skill.regenerer(actuel, schema_des_routes()) == actuel, (
        "La table de .bouzecode/skills/bouzecode/web-api.md n'est plus celle du schéma : "
        "lance `python scripts/regenerer_skill_web_api.py`.")


def test_la_skill_garde_sa_forme():
    """Front-matter de skill, une seule section générée, une ligne par route du périmètre."""
    actuel = _texte_de_la_skill().replace("\r\n", "\n")
    schema = schema_des_routes()
    lignes_de_routes = [ligne for ligne in actuel.split("\n") if ligne.startswith("| `")]
    perimetre = [cle for cle in schema["endpoints"] if skill._dans_le_perimetre(cle)]

    assert actuel.startswith("---\nname: bouzecode/web-api\n")
    assert actuel.count(skill.DEBUT) == 1 and actuel.count(skill.FIN) == 1
    assert [ligne.split("`")[1] for ligne in lignes_de_routes] == perimetre
    assert "POST /api/projects/<slug>/tickets" in perimetre
