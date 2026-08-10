"""Fix 1 — derive_status : statuts actionnables qui priment sur 'terminé'/'à relire'.

Tests user-centric de la fonction PURE derive_status (aucun store, aucun mock) : on lui
passe un dict ticket dans l'état réel qu'il aurait sur le board et on vérifie le libellé.
Cas réels couverts : d677b7d5 (needs_attention posé manuellement done), échec tests
(gate_failed_cap) et échec validation (KO au plafond) qui restaient 'à relire' à vie.
"""
from bouzecode.web_v2.services.work import tickets as tickets_svc


def test_crashed_prime_sur_done():
    """Un ticket done ET crashed (faux 'terminé' masquant un plantage) = 'planté'."""
    ticket = {"id": "t", "done": True, "crashed": True}
    assert tickets_svc.derive_status(ticket) == "planté"


def test_merge_bloque_prime_sur_done():
    """Cas d677b7d5 : worktree needs_attention + done posé à la main = 'merge bloqué',
    pas 'terminé' (le merge était bloqué)."""
    ticket = {"id": "t", "done": True, "worktree": {"state": "needs_attention"}}
    assert tickets_svc.derive_status(ticket) == "merge bloqué"


def test_needs_attention_acquitte_redevient_terminable():
    """Une fois acquitté (state=cleaned, cf. Fix2), le done reprend la main = 'terminé'."""
    ticket = {"id": "t", "done": True,
              "worktree": {"state": "cleaned", "resolved_by": "manual-done"}}
    assert tickets_svc.derive_status(ticket) == "terminé"


# La notion de PLAFOND de passes a disparu avec la boucle d'orchestration p10
# (`docs/design_p10_orchestration.md` : « `_MAX_WORK_PASSES`, `gate_failed_cap` retirés avec
# la boucle, n'ont plus d'objet »). Les deux tests qui distinguaient « KO au plafond » de
# « KO sous le plafond » pinnaient donc un contrat mort, et référençaient un symbole supprimé.
# Ce qui compte pour l'utilisateur du board survit et est ce qu'on tient ici : un verdict KO
# ne se présente JAMAIS comme un simple « à relire ».


def test_verdict_ko_est_echec_validation_quel_que_soit_le_nombre_de_passes():
    """Un KO est actionnable : il s'affiche comme tel dès la première passe comme après
    plusieurs, là où l'ancien contrat le masquait en « à relire » sous le plafond."""
    une_passe = {"id": "t", "runs": [{"kind": "work"}, {"kind": "validate", "verdict": "KO"}]}
    assert tickets_svc.derive_status(une_passe) == "échec validation"

    plusieurs = {"id": "t", "runs": [{"kind": "work"}, {"kind": "work"}, {"kind": "work"},
                                     {"kind": "validate", "verdict": "KO"}]}
    assert tickets_svc.derive_status(plusieurs) == "échec validation"


def test_gate_failed_cap_n_est_plus_un_statut():
    """Le drapeau de l'ancienne boucle ne fabrique plus de statut à lui seul : un ticket qui
    le porte encore (store écrit avant p10) retombe sur le statut ordinaire de son travail,
    au lieu d'un « échec tests » que plus rien n'alimente ni ne retire."""
    ticket = {"id": "t", "gate_failed_cap": True, "runs": [{"kind": "work"}]}
    assert tickets_svc.derive_status(ticket) == "à relire"
