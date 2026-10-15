"""Régénère la table des routes de `.bouzecode/skills/bouzecode/web-api.md` depuis GET /api/schema.

    python scripts/regenerer_skill_web_api.py          # réécrit la skill
    python scripts/regenerer_skill_web_api.py --verif  # code 1 si la skill n'est pas à jour

Le schéma est construit sur une application qui n'enregistre QUE les routes : aucun serveur à
démarrer, aucune migration du store. Le HOME est redirigé vers un dossier jetable pour que les
imports de bouzecode n'écrivent rien dans le vrai `~/.bouzecode`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def main() -> int:
    home_jetable = tempfile.mkdtemp(prefix="bz_schema_")
    os.environ["HOME"] = os.environ["USERPROFILE"] = home_jetable
    sys.path.insert(0, str(RACINE / "src"))
    from bouzecode.web_v2.schema import skill
    from bouzecode.web_v2.schema.application import schema_des_routes

    chemin = RACINE / skill.CHEMIN_SKILL
    actuel = chemin.read_bytes().decode("utf-8")
    attendu = skill.regenerer(actuel, schema_des_routes())
    if "--verif" in sys.argv:
        if attendu != actuel:
            print(f"{chemin} n'est pas à jour : lance scripts/regenerer_skill_web_api.py")
            return 1
        print("skill à jour")
        return 0
    chemin.write_bytes(attendu.encode("utf-8"))
    print(f"{chemin} régénérée")
    return 0


if __name__ == "__main__":
    sys.exit(main())
