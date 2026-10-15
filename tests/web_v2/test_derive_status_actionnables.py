"""Fix 1 — statuts actionnables qui priment sur 'terminé'/'à relire', conservés par la
correspondance des anciens drapeaux vers l'état unique (lot L2).

Un ticket écrit avant L2 (drapeaux `done`, `crashed`, `worktree.state`…) est migré par
`fsm.correspondance.etat_initial` ; son libellé est ensuite la projection de son état. On
vérifie que la migration garde ce que l'ancien libellé disait des cas réels : d677b7d5
(needs_attention posé manuellement done), plantage masqué par un `done`.
"""
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import correspondance


def _statut_migre(ancien: dict) -> str:
    state, raison = correspondance.etat_initial(ancien)
    return tickets_svc.derive_status({**ancien, "state": state, "state_reason": raison})


def test_crashed_prime_sur_done():
    """Un ticket done ET crashed (faux 'terminé' masquant un plantage) = 'planté'."""
    assert _statut_migre({"id": "t", "done": True, "crashed": True}) == "planté"


def test_merge_bloque_prime_sur_done():
    """Cas d677b7d5 : worktree needs_attention + done posé à la main = 'merge bloqué'."""
    ticket = {"id": "t", "done": True, "worktree": {"state": "needs_attention"}}
    assert _statut_migre(ticket) == "merge bloqué"


def test_merge_bloque_clos_explicitement_est_termine():
    ticket = {"id": "t", "done": True, "closed": {"outcome": "accepted"},
              "worktree": {"state": "needs_attention"}}
    assert _statut_migre(ticket) == "terminé"


def test_needs_attention_acquitte_redevient_terminable():
    """Une fois acquitté (state=cleaned), le ticket est clos : 'terminé'."""
    ticket = {"id": "t", "done": True,
              "worktree": {"state": "cleaned", "resolved_by": "manual-done"}}
    assert _statut_migre(ticket) == "terminé"


def test_un_run_validate_herite_ne_fabrique_aucun_statut():
    """Le validateur de tickets a été retiré (D1) : un ancien run `validate` n'a plus de sens,
    le ticket se lit par son run de TRAVAIL (livré ici)."""
    herite = {"id": "t", "runs": [{"kind": "validate", "verdict": "KO"},
                                  {"kind": "work", "completed": True}]}
    assert _statut_migre(herite) == "à relire"


def test_gate_failed_cap_n_est_plus_un_statut():
    """Le drapeau de l'ancienne boucle ne fabrique plus de statut à lui seul."""
    ticket = {"id": "t", "gate_failed_cap": True, "runs": [{"kind": "work", "completed": True}]}
    assert _statut_migre(ticket) == "à relire"


def test_lancement_echoue_prime_sur_done():
    ticket = {"id": "t", "done": True, "launch_failed": {"error": "git KO"}}
    assert _statut_migre(ticket) == "lancement échoué"
