# [desc] Tests du vérificateur d'invariants des E2E : chaque règle détecte l'incohérence réellement observée en recette et se tait sur l'état sain ; la surveillance ignore les écarts brefs. [/desc]
"""Les règles de `e2e_sandbox/invariants.py` sur des instantanés construits à la main."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "e2e_sandbox"))
import invariants as inv  # noqa: E402


def noeud(agent_id, etat, parent="dispatcher:manual", liveness="running", **extra):
    return {"agent_id": agent_id, "etat": etat, "parent": parent, "liveness": liveness,
            "libelle_etat": "", **extra}


def arbre(*noeuds):
    return {"arbre": {"nodes": list(noeuds)}}


def regles(inst):
    return {v.regle for v in inv.violations(inst)}


def test_un_manager_releve_qui_travaille_n_est_pas_affiche_en_attente_de_ses_enfants():
    """Le cas observé en recette : parent « orchestrating », enfants finis et crashé."""
    inst = arbre(noeud("m", "orchestrating"),
                 noeud("a", "finished", parent="m", liveness="delivered"),
                 noeud("b", "finished", parent="m", liveness="delivered"),
                 noeud("c", "crashed", parent="m", liveness="crashed"))
    assert "orchestration_sans_enfant_actif" in regles(inst)


def test_un_manager_qui_attend_un_enfant_qui_tourne_est_coherent():
    inst = arbre(noeud("m", "orchestrating", liveness="idle"),
                 noeud("a", "running", parent="m"),
                 noeud("c", "crashed", parent="m", liveness="crashed"))
    assert "orchestration_sans_enfant_actif" not in regles(inst)


def test_un_petit_enfant_actif_compte_pour_son_grand_parent():
    inst = arbre(noeud("m", "orchestrating", liveness="idle"),
                 noeud("a", "orchestrating", parent="m", liveness="idle"),
                 noeud("aa", "awaiting_input", parent="agent/a", liveness="awaiting_input"))
    assert "orchestration_sans_enfant_actif" not in regles(inst)


def test_en_cours_sans_process_vivant_est_signale():
    assert "travaille_sans_process" in regles(arbre(noeud("x", "running", liveness="crashed")))
    assert "travaille_sans_process" not in regles(arbre(noeud("x", "running", liveness="running")))
    #  Un process chaud (warm pool) qui reçoit une relance est vivant.
    assert "travaille_sans_process" not in regles(arbre(noeud("x", "thinking", liveness="idle")))


def _session(tmp_path, messages):
    chemin = tmp_path / "agent.session.json"
    chemin.write_text(json.dumps({"messages": messages}), encoding="utf-8")
    return str(chemin)


def test_un_agent_tue_pendant_sa_propre_integration_est_signale(tmp_path):
    session = _session(tmp_path, [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "m1", "name": "Methodology", "input": {}},
            {"id": "i1", "name": "Environment", "input": {"action": "integrate"}}]},
        {"role": "tool", "tool_call_id": "m1", "name": "Methodology", "content": "ok"},
    ])
    inst = arbre(noeud("s", "crashed", liveness="crashed", returncode=-15, session_path=session))
    assert "tue_par_son_propre_outil" in regles(inst)


def test_un_agent_arrete_apres_le_resultat_de_son_outil_n_est_pas_un_suicide(tmp_path):
    session = _session(tmp_path, [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "i1", "name": "Environment", "input": {"action": "integrate"}}]},
        {"role": "tool", "tool_call_id": "i1", "name": "Environment", "content": "Merge propre"},
    ])
    inst = arbre(noeud("s", "crashed", liveness="crashed", returncode=-15, session_path=session))
    assert "tue_par_son_propre_outil" not in regles(inst)


def _lignes(*taches):
    return {"lignes": {"chantiers": [{"lignes": list(taches)}], "non_rattachees": []}}


def test_travail_integre_jamais_arrete_ni_en_echec():
    tache = {"id": "t", "statut_ui": "en_echec",
             "passages": [{"agent_id": "p", "etat": "crashed", "integre": True}]}
    assert {"integre_mais_en_echec", "integre_mais_arrete"} <= regles(_lignes(tache))


def test_deux_agents_actifs_sur_une_meme_tache():
    tache = {"id": "t", "statut_ui": "en_cours",
             "passages": [{"agent_id": "p2", "etat": "running"}, {"agent_id": "p1", "etat": "thinking"}]}
    assert "deux_agents_actifs" in regles(_lignes(tache))


def test_un_recap_decoupe_en_caracteres_est_signale():
    """Le cas observé : une liste JSON stockée en texte, itérée caractère par caractère."""
    tache = {"id": "t", "passages": [{"agent_id": "p", "etat": "finished",
                                      "recap": {"fait": list('["Traité : x"]')}}]}
    assert "recap_decoupe" in regles(_lignes(tache))
    sain = {"id": "t", "passages": [{"agent_id": "p", "etat": "finished", "recap": {"fait": ["Traité : x"]}}]}
    assert "recap_decoupe" not in regles(_lignes(sain))


def test_les_pastilles_disent_ce_que_montrent_la_boite_et_l_arbre():
    inst = {**arbre(noeud("x", "running")), "nav": {"a_moi": 2, "en_cours": 0}, "boite": {"compte": 3}}
    assert {"compteur_a_moi", "compteur_en_cours"} <= regles(inst)
    ok = {**arbre(noeud("x", "running")), "nav": {"a_moi": 3, "en_cours": 1}, "boite": {"compte": 3}}
    assert not {"compteur_a_moi", "compteur_en_cours"} & regles(ok)


def test_aucun_mot_technique_banni_dans_les_libelles():
    assert "mot_banni" in regles(arbre(noeud("x", "finished", libelle_etat="Ticket terminé")))
    assert "mot_banni" not in regles(arbre(noeud("x", "finished", libelle_etat="Terminé")))


def test_la_surveillance_ne_retient_que_ce_qui_dure():
    s = inv.Surveillant(["b"], persistance=5)
    mauvais = arbre(noeud("x", "running", liveness="crashed"))
    s.observer("b", {**mauvais, "t": 100})
    s.observer("b", {**arbre(noeud("x", "running")), "t": 101})     # résorbé : oublié
    s.observer("b", {**mauvais, "t": 102})
    s.observer("b", {**mauvais, "t": 106})
    assert not s.retenues                                            # 4 s seulement
    s.observer("b", {**mauvais, "t": 108})
    assert [v.regle for _, _, v in s.retenues.values()] == ["travaille_sans_process"]


def test_une_violation_heritee_du_debut_du_test_est_ignoree():
    s = inv.Surveillant(["b"], persistance=0, ignorer={("b", "travaille_sans_process", "x")})
    s.observer("b", {**arbre(noeud("x", "running", liveness="crashed")), "t": 1})
    assert not s.retenues


def test_en_cours_compare_a_la_pastille_lue_juste_apres_l_arbre():
    """Chaque pastille est comparée à la page qu'elle résume, lue JUSTE avant elle : entre
    l'arbre et la pastille de fin d'instantané, /api/lignes et /api/inbox prennent des centaines
    de millisecondes, pendant lesquelles un agent du bac a le temps de naître ou de finir."""
    inst = {**arbre(noeud("x", "running")), "nav_arbre": {"en_cours": 1},
            "nav": {"a_moi": 3, "en_cours": 0}, "boite": {"compte": 3}}
    assert "compteur_en_cours" not in regles(inst)
    inst["nav_arbre"] = {"en_cours": 0}
    assert "compteur_en_cours" in regles(inst)


def test_un_ecart_de_pastille_qui_dure_fait_echouer_comme_les_autres_regles():
    """Plus de tolérance de 30 s propre aux pastilles : elle masquait un écart de 15 s entre la
    pastille « en cours » et la page Agents, présent à chaque passe complète."""
    s = inv.Surveillant(["b"])
    ecart = {**arbre(noeud("x", "running")), "nav": {"en_cours": 0}}
    s.observer("b", {**ecart, "t": 100})
    s.observer("b", {**ecart, "t": 100 + inv.PERSISTANCE + 1})
    assert [v.regle for _, _, v in s.retenues.values()] == ["compteur_en_cours"]


def test_un_ecart_de_pastille_d_un_instant_n_est_pas_signale_au_depart_du_test():
    """Le relevé « déjà violés au début des tests » est un instantané UNIQUE : un écart d'un
    instant entre deux lectures de pastilles globales n'y a pas sa place (la surveillance,
    elle, fait échouer un écart qui dure)."""
    vues = inv.violations({**arbre(noeud("x", "running", liveness="crashed")), "nav": {"en_cours": 0}})
    assert {v.regle for v in vues} == {"travaille_sans_process", "compteur_en_cours"}
    assert [v.regle for v in inv.a_signaler_au_depart(vues)] == ["travaille_sans_process"]
