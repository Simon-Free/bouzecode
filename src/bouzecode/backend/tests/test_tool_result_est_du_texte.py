"""Le resultat d'un outil doit arriver au modele en TEXTE.

Les outils du Bureau (`Mails`, `Teams`, `Taches`...) rendent un dict Python. Ce dict
traversait TOUTE la chaine sans lever : `len(dict)` compte les cles (donc jamais de
troncature), `_compact_tool_result` est un pass-through, et le message `role=tool`
partait avec un dict dans son `content` — la ou l'API du modele exige une chaine.
Resultat mesure cote humain : `Methodology` (qui rend une str) s'affichait, les huit
outils du Bureau restaient MUETS.

On teste au point d'entree reel du pipeline (`execute_tool`), pas sur les wrappers
metier : c'est exactement le maillon que les mesures precedentes contournaient.
"""
import json

from bouzecode.backend.core.tool_registry import ToolDef, execute_tool, register_tool


def _enregistre(nom: str, retour):
    """Un outil factice qui rend `retour` tel quel."""
    schema = {
        "name": nom,
        "description": "outil de test",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }
    #  read_only=False : on ne veut pas melanger le repeat_guard (memoire des outils
    #  read_only) au sujet du test, qui est le TYPE du resultat.
    register_tool(ToolDef(name=nom, schema=schema, func=lambda p, c: retour,
                          read_only=False, concurrent_safe=True))
    return nom


def test_un_outil_qui_rend_un_dict_arrive_en_json_relisible():
    """Le cas des outils du Bureau : un dict doit devenir du JSON, pas un repr Python."""
    nom = _enregistre("OutilDictTest", {"ok": True, "total": 2, "mails": [{"id": "a"}]})

    resultat = execute_tool(nom, {}, {})

    assert isinstance(resultat, str), f"un dict est ressorti tel quel : {type(resultat)}"
    charge = json.loads(resultat)
    assert charge["total"] == 2
    assert charge["mails"][0]["id"] == "a"


def test_un_outil_qui_rend_une_liste_arrive_en_json_relisible():
    nom = _enregistre("OutilListeTest", [{"id": "m1"}, {"id": "m2"}])

    resultat = execute_tool(nom, {}, {})

    assert isinstance(resultat, str)
    assert [element["id"] for element in json.loads(resultat)] == ["m1", "m2"]


def test_un_outil_qui_rend_du_texte_est_rendu_inchange():
    """Non-regression : la quarantaine d'outils du framework rendent deja du texte."""
    nom = _enregistre("OutilTexteTest", "resultat brut\nsur deux lignes")

    resultat = execute_tool(nom, {}, {})

    assert resultat == "resultat brut\nsur deux lignes"


def test_un_objet_non_serialisable_ne_fait_pas_perdre_le_tour():
    """Mieux vaut un texte approximatif qu'un tour d'agent perdu en silence."""

    class Opaque:
        def __str__(self) -> str:
            return "objet-opaque"

    nom = _enregistre("OutilOpaqueTest", Opaque())

    resultat = execute_tool(nom, {}, {})

    assert isinstance(resultat, str)
    assert "objet-opaque" in resultat
