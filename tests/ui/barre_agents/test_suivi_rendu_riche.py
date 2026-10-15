"""Le suivi en direct d'un sous-agent s'imprime EXACTEMENT comme le rejeu : en-tete
`╭─ bouzecode ●`, bloc `⚙ Outil(...)`, panneau Methodologie, `Outil → N lines`.

Regression (2026-10-13) : la vue d'un sous-agent etait riche a la bascule (rejeu) puis
passait a un formateur compact (`⏺`, `⎿`, `●`) pour tout ce qui arrivait ensuite.
"""
from types import SimpleNamespace

from bouzecode.backend.multi_agent.en_process.fiche import FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.ui.barre_agents.ecran import EcranAgents
from bouzecode.ui.replay import replay_messages

CONSIGNE = {"role": "user", "content": "consigne du sous-agent"}
LOT = {"role": "assistant", "content": "Je note la méthode puis je **liste** les captures.",
       "tool_calls": [{"id": "m1", "name": "Methodology", "input": {"content": "lister d'abord"}},
                      {"id": "b1", "name": "Bash", "input": {"command": "dir C:\\captures"}}]}
RESULTAT_METHODOLOGY = {"role": "tool", "tool_call_id": "m1", "name": "Methodology",
                        "content": "methodology append: now 120 chars"}
RESULTAT_BASH = {"role": "tool", "tool_call_id": "b1", "name": "Bash",
                 "content": "a.png\nb.png\nc.png"}
CONCLUSION = {"role": "assistant", "content": "Trois captures trouvées."}
TICKS = [[LOT], [RESULTAT_METHODOLOGY], [], [RESULTAT_BASH, CONCLUSION]]


def _suivre_en_direct(capsys) -> str:
    """Bascule sur le sous-agent (consigne seule), puis ses messages arrivent tick par tick."""
    registre = RegistreAgents()
    registre.declarer_principal(SimpleNamespace(messages=[]), "claude-sonnet-4-5")
    enfant = SimpleNamespace(messages=[CONSIGNE])
    registre.ajouter(FicheAgent(id="a1", description="captures", state=enfant))
    ecran = EcranAgents(registre, {})
    ecran.nav.vue = "a1"
    ecran.traiter(("vue", "a1"))
    #  La bascule imprime « \n╭─ sous-agent … » puis le rejeu : on ne garde que le rejeu.
    bascule = capsys.readouterr().out.split("\n", 2)[2]
    for nouveaux in TICKS:
        enfant.messages += nouveaux
        ecran.imprimer_nouveautes()
    return bascule + capsys.readouterr().out


def test_le_suivi_en_direct_a_les_marqueurs_du_rendu_riche(capsys):
    sortie = _suivre_en_direct(capsys)
    assert "╭─ bouzecode" in sortie and "⚙" in sortie and "Méthodologie" in sortie
    assert "Bash → 3 lines" in sortie and "Methodology noted" in sortie
    assert "⏺" not in sortie and "⎿" not in sortie


def test_le_suivi_en_direct_est_indiscernable_du_rejeu(capsys):
    sortie = _suivre_en_direct(capsys)
    replay_messages([CONSIGNE, *[m for tick in TICKS for m in tick]])
    assert sortie == capsys.readouterr().out


def test_l_appel_en_vol_s_annonce_et_son_resultat_vient_au_tick_suivant(capsys):
    deroule = replay_messages([CONSIGNE, LOT, RESULTAT_METHODOLOGY], en_cours=True)
    annonce = capsys.readouterr().out
    assert 'command="dir C:\\captures"' in annonce and "Bash →" not in annonce
    deroule.avancer([CONSIGNE, LOT, RESULTAT_METHODOLOGY])
    assert capsys.readouterr().out == ""
    deroule.avancer([CONSIGNE, LOT, RESULTAT_METHODOLOGY, RESULTAT_BASH])
    resultat = capsys.readouterr().out
    assert "Bash → 3 lines" in resultat and "⚙" not in resultat
