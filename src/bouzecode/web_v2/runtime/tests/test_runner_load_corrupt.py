# [desc] Régression : load_agent(id) renvoie None sur un fichier agent corrompu au lieu de lever (évite le 500 sur la home via _attach_run_state). [/desc]
"""Un `<id>.json` au JSON invalide faisait remonter JSONDecodeError depuis
load_agent → tickets._attach_run_state → 500 sur la home. Comme la liste
(_list_agents_uncached) saute déjà les fichiers corrompus, load_agent doit faire
de même et renvoyer None.
"""
import bouzecode.web_v2.runtime.runner as runner


def test_load_agent_returns_none_on_corrupt_file(tmp_path):
    orig = runner.AGENTS_DIR
    runner.AGENTS_DIR = tmp_path
    try:
        (tmp_path / "deadbeef.json").write_text("{not valid json", encoding="utf-8")
        assert runner.load_agent("deadbeef") is None
    finally:
        runner.AGENTS_DIR = orig


def test_load_agent_returns_none_when_missing(tmp_path):
    orig = runner.AGENTS_DIR
    runner.AGENTS_DIR = tmp_path
    try:
        assert runner.load_agent("nope") is None
    finally:
        runner.AGENTS_DIR = orig
