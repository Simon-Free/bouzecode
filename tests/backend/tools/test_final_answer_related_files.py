"""FinalAnswer expose `related_files` : fichiers livrés consultables par l'humain dans bouzeui."""
from bouzecode.backend.agent.related_files import normaliser_related_files


def _params():
    from bouzecode.backend.tools.schemas import TOOL_SCHEMAS
    schema = next(s for s in TOOL_SCHEMAS if s.get("name") == "FinalAnswer")
    return schema.get("input_schema") or schema.get("parameters")


def test_schema_final_answer_declare_related_files():
    params = _params()
    champ = params["properties"]["related_files"]
    assert champ["type"] == "array"
    assert "path" in champ["items"]["properties"]
    assert "path" in champ["items"].get("required", [])
    assert "cliquables dans bouzeui" in champ["description"]
    assert "related_files" not in params.get("required", [])


def test_normaliser_related_files_ignore_chemins_relatifs(tmp_path):
    absolu = str(tmp_path / "rapport.html")
    sortie = normaliser_related_files([{"path": absolu, "label": "Rapport"}, {"path": "rel.txt"},
                                       absolu + "x"])
    assert [f["path"] for f in sortie] == [absolu, absolu + "x"]
    assert sortie[0]["label"] == "Rapport"
