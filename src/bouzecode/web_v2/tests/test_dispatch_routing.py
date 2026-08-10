"""resolve_routing: routage d'un prompt vers un projet CHOISI, sans effet de bord.

Plus aucune deduction LLM : le titre du ticket est la premiere ligne du prompt, et
sans projet choisi l'API repond needs_project au lieu de deviner."""
from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import dispatch

PROJECTS = [
    {"slug": "demo-app", "name": "demo_app", "path": "/tmp/app"},
    {"slug": "demo-ingestion", "name": "demo_ingestion", "path": "/tmp/ing"},
]


def test_routes_to_the_chosen_project():
    """Le projet choisi par l'utilisateur est celui retenu, sans autre arbitrage."""
    result = dispatch.resolve_routing("le delta rm_od est mort", PROJECTS,
                                      project_slug="demo-ingestion")
    assert result["needs_project"] is False
    assert result["project_slug"] == "demo-ingestion"


def test_title_is_the_first_line_of_the_prompt():
    """Le titre du ticket se lit sur la premiere ligne du prompt."""
    result = dispatch.resolve_routing("premiere ligne\nseconde", PROJECTS,
                                      project_slug="demo-app")
    assert result["title"] == "premiere ligne"


def test_needs_project_when_none_is_chosen():
    """Sans projet choisi, la reponse dit needs_project au lieu d'en inventer un."""
    result = dispatch.resolve_routing("un besoin flou sans projet", PROJECTS)
    assert result["needs_project"] is True
    assert result["project_slug"] == ""


def test_typology_defaults_when_not_given():
    """Une typologie absente retombe sur 'default', jamais sur une devinette."""
    result = dispatch.resolve_routing("fais un truc", PROJECTS,
                                      project_slug="demo-app")
    assert result["typology"] == "default"


def test_agent_parent_round_trips():
    """Un parent persisté se relit ; un JSON legacy sans parent reste valide."""
    data = {"agent_id": "abc", "prompt": "p", "model": "m", "cwd": "c",
            "pid": 1, "started_at": "t", "parent": "dispatcher:manual"}
    agent = runner._agent_from_dict(data)
    assert agent.parent == "dispatcher:manual"

    legacy = {k: v for k, v in data.items() if k != "parent"}
    assert runner._agent_from_dict(legacy).parent == ""
