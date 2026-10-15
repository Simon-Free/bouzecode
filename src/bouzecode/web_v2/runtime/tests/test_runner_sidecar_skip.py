# [desc] Régression : _list_agents_uncached saute les sidecars .pending/.deferred.json (pas seulement .session). [/desc]
"""Régression du 500 sur /api/projects : list_agents globait *.json et lisait les
sidecars `<id>.session.json.deferred.json` / `.pending.json` comme des companions,
ce qui (a) les mal-parsait et (b) courait avec le drain qui supprime .deferred.json.

Sidecar à JSON volontairement invalide : avec le bug, json.loads levait ; avec le
fix (`.session in path.stem`), le sidecar est sauté et la liste revient vide.
"""
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre


def test_list_agents_skips_session_sidecars(tmp_path):
    orig = agent_fiche.AGENTS_DIR
    agent_fiche.AGENTS_DIR = tmp_path
    try:
        # Sidecars dérivés de session, contenu NON parsable : ne doivent jamais être lus.
        (tmp_path / "abc.session.json.deferred.json").write_text("PAS DU JSON", encoding="utf-8")
        (tmp_path / "abc.session.json.pending.json").write_text("PAS DU JSON", encoding="utf-8")
        (tmp_path / "abc.session.json").write_text("PAS DU JSON", encoding="utf-8")
        # Aucun companion <id>.json -> liste vide, et surtout AUCUN crash.
        assert agent_registre._list_agents_uncached() == []
    finally:
        agent_fiche.AGENTS_DIR = orig
