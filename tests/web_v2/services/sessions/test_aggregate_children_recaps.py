"""Tests de recap_service.aggregate_children_recaps : concaténation (sans LLM) des récaps
des sous-agents d'un manager. Fonction pure (deps injectées) → fakes, aucun mock."""
from bouzecode.web_v2.services import recap_service


class FakeAgent:
    def __init__(self, agent_id, parent, session_path, prompt="", started_at=""):
        self.agent_id = agent_id
        self.parent = parent
        self.session_path = session_path
        self.prompt = prompt
        self.started_at = started_at


def _session(recap=None, snapshots=None, diff=None):
    return {"recap": recap, "file_snapshots": snapshots or {}, "diff": diff}


def _loader(by_path):
    return lambda p: by_path.get(p)


def test_aggregates_children_in_dispatch_order_with_diffs():
    recap_a = {"symptoms": "sa", "explanation": "ea", "tests": "ta",
               "changes": [{"file": "src/a.py", "summary": "fix a"}]}
    recap_b = {"symptoms": "sb", "explanation": "eb", "tests": "tb",
               "changes": [{"file": "src/b.py", "summary": "fix b"}]}
    agents = [
        FakeAgent("child-b", "mgr", "b.json", "feature B", started_at="2026-07-07T02:00:00"),
        FakeAgent("child-a", "mgr", "a.json", "feature A", started_at="2026-07-07T01:00:00"),
        FakeAgent("stranger", "other-mgr", "x.json", "hors lot", started_at="2026-07-07T00:00:00"),
    ]
    by_path = {
        "a.json": _session(recap_a, {"src/a.py": {"before": "old\n", "after": "new\n"}}),
        "b.json": _session(recap_b, {"src/b.py": {"before": "1\n", "after": "2\n"}}),
        "x.json": _session({"symptoms": "sx"}, {}),
    }

    kids = recap_service.aggregate_children_recaps("mgr", agents, _loader(by_path))

    # Seuls les enfants de 'mgr', triés par started_at (ordre de dispatch : A avant B).
    assert [k["agent_id"] for k in kids] == ["child-a", "child-b"]
    assert [k["title"] for k in kids] == ["feature A", "feature B"]
    assert kids[0]["recap"] is recap_a
    # Les diffs sont assemblés par enfant (section changes présente).
    assert [d["file"] for d in kids[0]["diffs"]] == ["src/a.py"]
    assert kids[0]["diffs"][0]["section"] == "changes"


def test_matches_parent_by_key_form_too():
    """Le parent d'un enfant peut être 'agent/<id>' (forme key) ou '<id>' (agent_id)."""
    recap = {"symptoms": "s", "explanation": "e", "tests": "t", "changes": []}
    agents = [FakeAgent("c", "agent/mgr", "c.json", "c", started_at="t")]
    kids = recap_service.aggregate_children_recaps(
        "mgr", agents, _loader({"c.json": _session(recap)}))
    assert [k["agent_id"] for k in kids] == ["c"]


def test_includes_children_without_recap_as_link_only():
    """MINIMUM demandé : un enfant du manager SANS récap structuré (ou sans session)
    reste remonté — recap=None, diffs=[], has_recap=False — pour que le front affiche
    au moins un lien vers sa conversation. Seuls les enfants d'un AUTRE parent sont exclus."""
    agents = [
        FakeAgent("no-recap", "mgr", "n.json", "x", started_at="a"),
        FakeAgent("empty-recap", "mgr", "e.json", "y", started_at="b"),
        FakeAgent("no-session", "mgr", "", "z", started_at="c"),
    ]
    by_path = {"n.json": _session(None), "e.json": _session({})}
    kids = recap_service.aggregate_children_recaps("mgr", agents, _loader(by_path))
    # Les trois enfants du manager sont présents (ordre de dispatch = started_at asc).
    assert [k["agent_id"] for k in kids] == ["no-recap", "empty-recap", "no-session"]
    for k in kids:
        assert k["has_recap"] is False
        assert k["recap"] is None
        assert k["diffs"] == []


def test_no_children_returns_empty():
    agents = [FakeAgent("solo", "dispatcher:manual", "s.json", "s", started_at="a")]
    kids = recap_service.aggregate_children_recaps(
        "mgr", agents, _loader({"s.json": _session({"symptoms": "s"})}))
    assert kids == []


_GIT_DIFF = """diff --git a/src/pkg/service.py b/src/pkg/service.py
index 1111111..2222222 100644
--- a/src/pkg/service.py
+++ b/src/pkg/service.py
@@ -1,3 +1,3 @@
 def run():
-    return 1
+    return 2
diff --git a/tests/test_service.py b/tests/test_service.py
index 5555555..6666666 100644
--- a/tests/test_service.py
+++ b/tests/test_service.py
@@ -1,2 +1,2 @@
-assert run() == 1
+assert run() == 2
"""


def test_child_diffs_from_git_text_when_snapshots_empty():
    """Repro bug Manager/Python : l'enfant a un récap et un git diff TEXTE (`diff`)
    mais file_snapshots VIDE (flux headless). Les diffs doivent quand même apparaître,
    sectionnés, en repli sur le champ `diff`."""
    recap = {"symptoms": "s", "explanation": "e", "tests": "t",
             "changes": [{"file": "src/pkg/service.py", "summary": "fix run()"}]}
    agents = [FakeAgent("coder", "mgr", "c.json", "corrige run()", started_at="t1")]
    by_path = {"c.json": _session(recap, snapshots={}, diff=_GIT_DIFF)}

    kids = recap_service.aggregate_children_recaps("mgr", agents, _loader(by_path))

    assert [k["agent_id"] for k in kids] == ["coder"]
    diffs = kids[0]["diffs"]
    files = [d["file"] for d in diffs]
    assert files == ["src/pkg/service.py", "tests/test_service.py"]
    by_file = {d["file"]: d for d in diffs}
    assert by_file["src/pkg/service.py"]["section"] == "changes"
    assert by_file["tests/test_service.py"]["section"] == "tests"
    # Le patch git text est porté tel quel (rendu <pre> côté front, pas de Monaco).
    assert "def run():" in by_file["src/pkg/service.py"]["patch"]


def test_dedups_reworked_recaps_last_wins():
    """POLITIQUE MULTI-RÉCAPS : deux enfants de MÊME TITRE (rework KO→OK relancé)
    → une seule entrée = la plus RÉCENTE (started_at max). Titres distincts = une
    entrée chacun, ordre de dispatch (started_at asc)."""
    old_recap = {"symptoms": "vieux KO", "explanation": "e", "tests": "t", "changes": []}
    new_recap = {"symptoms": "récent OK", "explanation": "e", "tests": "t", "changes": []}
    other_recap = {"symptoms": "autre", "explanation": "e", "tests": "t", "changes": []}
    agents = [
        FakeAgent("rework-old", "mgr", "old.json", "corrige le login", started_at="2026-07-07T01:00:00"),
        FakeAgent("rework-new", "mgr", "new.json", "corrige le login", started_at="2026-07-07T03:00:00"),
        FakeAgent("distinct", "mgr", "d.json", "ajoute le logout", started_at="2026-07-07T02:00:00"),
    ]
    by_path = {
        "old.json": _session(old_recap),
        "new.json": _session(new_recap),
        "d.json": _session(other_recap),
    }

    kids = recap_service.aggregate_children_recaps("mgr", agents, _loader(by_path))

    titles = [k["title"] for k in kids]
    # Deux titres distincts seulement (dédup du rework), ordre de dispatch (started_at asc).
    assert titles == ["corrige le login", "ajoute le logout"]
    login = next(k for k in kids if k["title"] == "corrige le login")
    # Le plus récent gagne : c'est le récap OK (started_at 03:00), pas le KO (01:00).
    assert login["recap"] is new_recap
    assert login["agent_id"] == "rework-new"


def test_session_recap_diffs_prefers_snapshots_then_git_text_then_empty():
    """Fonction pure : file_snapshots prioritaire → sinon git diff text → sinon []."""
    recap = {"symptoms": "s", "explanation": "e", "tests": "t",
             "changes": [{"file": "src/pkg/service.py", "summary": "x"}]}

    # 1. file_snapshots présent → chemin difflib (contenus complets original/modified).
    snap = {"src/pkg/service.py": {"before": "return 1\n", "after": "return 2\n"}}
    via_snap = recap_service.session_recap_diffs(recap, {"file_snapshots": snap})
    assert [d["file"] for d in via_snap] == ["src/pkg/service.py"]
    assert via_snap[0]["original"] == "return 1\n"

    # 2. file_snapshots vide mais git diff text → repli sur `diff`.
    via_git = recap_service.session_recap_diffs(recap, {"file_snapshots": {}, "diff": _GIT_DIFF})
    assert [d["file"] for d in via_git] == ["src/pkg/service.py", "tests/test_service.py"]
    assert "patch" in via_git[0]

    # 3. ni snapshots ni diff → liste vide (comportement historique préservé).
    assert recap_service.session_recap_diffs(recap, {}) == []


# --- sessions réelles : lues une fois par version du fichier ------------------------------

def _enfants_sur_disque(tmp_path):
    import json
    recap = {"symptoms": "s", "explanation": "e", "tests": "t",
             "changes": [{"file": "src/a.py", "summary": "fix"}]}
    agents = []
    for i in range(3):
        chemin = tmp_path / f"enfant{i}.session.json"
        chemin.write_text(json.dumps(_session(recap, {"src/a.py": {"before": "a\n", "after": f"{i}\n"}})),
                          encoding="utf-8")
        agents.append(FakeAgent(f"e{i}", "mgr", str(chemin), f"tâche {i}", started_at=f"t{i}"))
    return agents


def _chargeur_compte():
    import json
    from pathlib import Path
    lectures = []

    def charger(p):
        lectures.append(p)
        return json.loads(Path(p).read_text(encoding="utf-8"))

    return charger, lectures


def test_sessions_des_enfants_lues_une_fois_par_version(tmp_path):
    """Ouvrir trois fois le récap d'un manager : chaque session d'enfant est lue UNE fois."""
    from bouzecode.web_v2.runtime.context_viewer import builder
    builder.oublier()
    agents = _enfants_sur_disque(tmp_path)
    charger, lectures = _chargeur_compte()
    resultats = [recap_service.aggregate_children_recaps("mgr", agents, charger)
                 for _ in range(3)]
    assert resultats[0] == resultats[1] == resultats[2]
    assert len(lectures) == 3
    builder.oublier()


def test_session_d_enfant_reecrite_relue(tmp_path):
    import json
    import os
    from pathlib import Path
    from bouzecode.web_v2.runtime.context_viewer import builder
    builder.oublier()
    agents = _enfants_sur_disque(tmp_path)
    charger, lectures = _chargeur_compte()
    avant = recap_service.aggregate_children_recaps("mgr", agents, charger)
    chemin = Path(agents[0].session_path)
    nouveau = {"symptoms": "autre", "explanation": "e", "tests": "t", "changes": []}
    chemin.write_text(json.dumps(_session(nouveau)), encoding="utf-8")
    st = chemin.stat()
    os.utime(chemin, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10**9))
    apres = recap_service.aggregate_children_recaps("mgr", agents, charger)
    assert avant[0]["recap"]["symptoms"] == "s" and apres[0]["recap"] == nouveau
    assert apres[1:] == avant[1:]
    assert len(lectures) == 4
    builder.oublier()
