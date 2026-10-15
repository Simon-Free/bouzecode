"""The pytest progress of a sub-agent is printed only in that sub-agent's view."""
from types import SimpleNamespace

from bouzecode.backend.multi_agent.en_process.fiche import FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.ui.barre_agents.ecran import EcranAgents


def _ecran():
    registre = RegistreAgents()
    registre.declarer_principal(SimpleNamespace(messages=[]), "claude-sonnet-4-5")
    registre.ajouter(FicheAgent(id="a1", description="tests", state=SimpleNamespace(messages=[])))
    return registre, EcranAgents(registre, {})


def test_progress_shown_in_sub_agent_view_once(capsys):
    registre, ecran = _ecran()
    ecran.nav.vue = "a1"
    ecran._vue_affichee = "a1"
    registre.changer("a1", progression="pytest: 2/3 , ✅2 ❌0 ⏭0")
    ecran.imprimer_nouveautes()
    ecran.imprimer_nouveautes()
    out = capsys.readouterr().out
    assert out.count("pytest: 2/3") == 1


def test_progress_not_shown_in_main_view(capsys):
    registre, ecran = _ecran()
    registre.changer("a1", progression="pytest: 2/3 , ✅2 ❌0 ⏭0")
    ecran.imprimer_nouveautes()
    assert "pytest" not in capsys.readouterr().out


LONG = "src/bouzecode/web_v2/tests/test_brouillons_de_fusion_archives.py::test_integrer_la_branche"


def _etat(done, passed, longest_s):
    return {"state": "running", "total": 23, "done": done, "passed": passed, "failed": 0,
            "skipped": 0, "workers": 2, "longest": {"id": LONG, "elapsed_s": longest_s}}


def _run_simule(registre, ecran, sondages):
    """Le démon sondé deux fois par seconde : chaque sondage pousse sa ligne d'avancement."""
    from bouzecode.backend.testd.rendu import ligne_avancement
    ecran.nav.vue = ecran._vue_affichee = "a1"
    for etat in sondages:
        registre.changer("a1", progression=ligne_avancement(etat))
        ecran.imprimer_nouveautes()


def test_elapsed_ticks_of_longest_test_print_nothing_new(capsys):
    """Le test le plus long qui tourne 5 s → 59 s sans qu'aucun test ne finisse : une seule ligne."""
    registre, ecran = _ecran()
    _run_simule(registre, ecran, [_etat(4, 4, s / 2) for s in range(10, 118)])
    lignes = [l for l in capsys.readouterr().out.splitlines() if "pytest:" in l]
    assert len(lignes) == 1 and "4/23" in lignes[0]


def test_each_count_change_prints_and_final_line_shows(capsys):
    """23 tests qui finissent un par un : une ligne par compte, la dernière est 23/23."""
    registre, ecran = _ecran()
    sondages = [_etat(done, done, 12 + t) for done in range(1, 24) for t in range(4)]
    _run_simule(registre, ecran, sondages)
    lignes = [l for l in capsys.readouterr().out.splitlines() if "pytest:" in l]
    assert len(lignes) == 23
    assert "23/23 , ✅23" in lignes[-1]


def test_queue_wait_seconds_print_nothing_new(capsys):
    """En file d'attente, les secondes qui passent ne font pas une ligne ; la position, si."""
    registre, ecran = _ecran()
    ecran.nav.vue = ecran._vue_affichee = "a1"
    for position, attente in [(2, 1), (2, 2), (2, 3), (1, 4), (1, 5)]:
        registre.changer("a1", progression=f"pytest: en file d'attente, position {position} "
                                           f"depuis {attente} s (4 workers)")
        ecran.imprimer_nouveautes()
    assert capsys.readouterr().out.count("en file d'attente") == 2
