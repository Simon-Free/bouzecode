# [desc] Un enfant dont le PROVISIONNEMENT échoue réveille son manager au lieu de le laisser
# attendre un verdict qui ne viendra jamais, et se voit sur le board comme échoué. [/desc]
"""Cas réel du 2026-07-28 (ticket 60f34332) : `git worktree add` tué au bout de 120 s, le
ticket reste sans run, sans worktree, `done=False`, et son manager — qui avait clos son tour
en attendant le verdict de cet enfant — a attendu 27 minutes en silence. Zéro agent LLM,
zéro git : on joue le ticket tel que le serveur l'a écrit."""
from bouzecode.web_v2.services.work import closure_guard, dispatch, wake, workflow
from bouzecode.web_v2.services.work import tickets as tickets_svc

MANAGER = "9d0789f2fdca"
MOTIF = "git worktree add ... timed out after 120 seconds"


class _FakeParent:
    """Le manager : process terminé, son tour clos, en attente du verdict de son enfant."""

    def __init__(self, slug="proj", ticket_id="mgr1"):
        self.agent_id = MANAGER
        self.cwd = ""
        self.ticket_slug = slug
        self.ticket_id = ticket_id


def _enfant_mort_ne(ticket_id="60f34332") -> dict:
    """L'enfant tel que le serveur le laisse quand le provisionnement a échoué."""
    return {"id": ticket_id, "title": "revalider T5", "parent": MANAGER, "typology": "validate",
            "runs": [], "done": False,
            "launch_failed": {"error": MOTIF, "at": "2026-07-28T16:25:00"}}


def _wire_wake(monkeypatch, tmp_path, kids, parent=None):
    """Branche `process_wakes` sur des enfants en mémoire et un manager factice."""
    reveils: list[tuple[str, str]] = []
    monkeypatch.setattr(wake, "WAKE_STATE_PATH", tmp_path / "wake_state.json")
    monkeypatch.setattr(wake.projects, "list_projects", lambda: [{"slug": "proj"}])
    monkeypatch.setattr(wake.tickets_svc, "list_tickets",
                        lambda slug, refresh=False, include_archived=False: list(kids))
    monkeypatch.setattr(wake.tickets_svc, "refresh_verdicts",
                        lambda slug, rows, persist=True: None)
    monkeypatch.setattr(wake.runner, "load_agent",
                        lambda aid: (parent or _FakeParent()) if aid == MANAGER else None)
    monkeypatch.setattr(wake.store, "agent_status", lambda agent: {"state": "finished"})
    monkeypatch.setattr(wake.runner, "continue_agent",
                        lambda agent, message: reveils.append((agent.agent_id, message)))
    return reveils


# ── (a) le parent est débloqué ────────────────────────────────────────────────

def test_le_manager_est_reveille_quand_le_lancement_de_son_enfant_echoue(monkeypatch, tmp_path):
    reveils = _wire_wake(monkeypatch, tmp_path, [_enfant_mort_ne()])

    woken = wake.process_wakes()

    assert woken == [MANAGER], "le manager n'a pas été réveillé : il attend un enfant inexistant"
    _, digest = reveils[0]
    assert "ÉCHEC DE LANCEMENT" in digest, "le manager n'apprend pas POURQUOI l'enfant n'a rien rendu"
    assert MOTIF in digest, "le motif exact de l'échec n'est pas transmis au manager"
    assert "60f34332" in digest


def test_le_manager_nest_pas_reveille_tant_que_le_lancement_est_en_vol(monkeypatch, tmp_path):
    """Non-régression : un enfant en cours de (re)lancement n'est PAS un enfant terminé."""
    en_vol = {"id": "c1", "title": "t", "parent": MANAGER, "runs": [], "launching": True}
    reveils = _wire_wake(monkeypatch, tmp_path, [en_vol])

    assert wake.process_wakes() == []
    assert reveils == []


def test_le_manager_est_reveille_une_seule_fois_pour_le_meme_echec(monkeypatch, tmp_path):
    """L'issue est STABLE : deux ticks du watchdog ne relancent pas le manager en boucle."""
    reveils = _wire_wake(monkeypatch, tmp_path, [_enfant_mort_ne()])

    wake.process_wakes()
    wake.process_wakes()

    assert len(reveils) == 1


# ── (b) l'état est visible ────────────────────────────────────────────────────

def test_un_ticket_mort_ne_ne_se_presente_pas_comme_un_ticket_ordinaire():
    assert tickets_svc.derive_status(_enfant_mort_ne()) == "lancement échoué"
    # Contraste : un ticket jamais lancé, lui, reste « à faire ».
    assert tickets_svc.derive_status({"id": "x", "runs": [], "done": False}) == "à faire"


def test_un_done_ne_peut_pas_masquer_un_lancement_echoue():
    """`done` posé à la main (ou par un hook trop généreux) ne transforme pas un ticket
    mort-né en succès : le statut est testé AVANT `done`, comme `crashed`."""
    ticket = {**_enfant_mort_ne(), "done": True}
    assert tickets_svc.derive_status(ticket) == "lancement échoué"


def test_une_relance_efface_letiquette_dechec(tmp_path):
    """Dès qu'une nouvelle tentative est en vol, le ticket redevient « en cours »."""
    ticket = tickets_svc.create_ticket("proj", "revalider T5", "fais X")
    dispatch.record_launch_failure("proj", ticket, MOTIF)
    assert tickets_svc.derive_status(tickets_svc.get_ticket("proj", ticket["id"])) == "lancement échoué"

    tickets_svc.set_launching("proj", ticket)

    relance = tickets_svc.get_ticket("proj", ticket["id"])
    assert "launch_failed" not in relance
    assert tickets_svc.derive_status(relance) == "en cours"


def test_lechec_est_ecrit_sur_le_ticket_et_commente(tmp_path):
    ticket = tickets_svc.create_ticket("proj", "revalider T5", "fais X")
    tickets_svc.set_launching("proj", ticket)

    dispatch.record_launch_failure("proj", ticket, MOTIF)

    stocke = tickets_svc.get_ticket("proj", ticket["id"])
    assert "launching" not in stocke, "l'état transitoire de lancement doit être retiré"
    assert stocke["launch_failed"]["error"] == MOTIF
    assert any("Lancement échoué" in c["text"] for c in stocke["comments"])


def test_un_echec_dans_le_thread_de_lancement_est_grave_sur_le_ticket(monkeypatch, tmp_path):
    """Le seam réel : `_launch_bg` est le thread qui provisionne puis spawne. Ce qu'il rate
    doit atterrir SUR le ticket — pas seulement dans les logs du serveur."""
    ticket = tickets_svc.create_ticket("proj", "revalider T5", "fais X")
    tickets_svc.set_launching("proj", ticket)

    def provisionnement_impossible(*args):
        raise RuntimeError(MOTIF)

    monkeypatch.setattr(dispatch, "_launch", provisionnement_impossible)

    dispatch._launch_bg("proj", ticket, str(tmp_path), "", "", "worktree", MANAGER)

    stocke = tickets_svc.get_ticket("proj", ticket["id"])
    assert stocke["launch_failed"]["error"] == MOTIF
    assert wake.ticket_terminal(stocke) is True, "l'enfant doit devenir une issue pour le parent"


# ── (c) le manager ne peut pas se clore « terminé » par-dessus ────────────────

def test_le_manager_nest_pas_marque_termine_par_dessus_un_enfant_mort_ne(monkeypatch, tmp_path):
    typologie = sorted(workflow.NON_CODING_TYPOLOGIES)[0]
    manager = tickets_svc.create_ticket("proj", "orchestration", "supervise")
    tickets_svc.update_ticket("proj", {**manager, "typology": typologie})
    monkeypatch.setattr(wake.reaper, "reap_ticket", lambda slug, ticket: False)

    clos = wake._finalize_noncoding_parent(_FakeParent(ticket_id=manager["id"]),
                                           [_enfant_mort_ne()])

    assert clos is False, "un manager dont un enfant n'a jamais démarré ne doit pas être « terminé »"
    frais = tickets_svc.get_ticket("proj", manager["id"])
    assert not frais.get("done")
    assert tickets_svc.derive_status(frais) == "clôture bloquée"
    assert any("lancement échoué" in c["text"] for c in frais["comments"])


def test_le_garde_fou_nomme_lenfant_mort_ne():
    bloquants = closure_guard.blocking_children([_enfant_mort_ne()])
    assert [b[0] for b in bloquants] == ["60f34332"]
    assert "aucun agent n'a démarré" in bloquants[0][1]


def test_un_manager_dont_lenfant_a_livre_reste_finalisable(monkeypatch, tmp_path):
    """Cas nominal : rien de tout ceci ne bloque un enfant qui a réellement livré."""
    typologie = sorted(workflow.NON_CODING_TYPOLOGIES)[0]
    manager = tickets_svc.create_ticket("proj", "orchestration", "supervise")
    tickets_svc.update_ticket("proj", {**manager, "typology": typologie})
    monkeypatch.setattr(wake.reaper, "reap_ticket", lambda slug, ticket: False)
    livre = {"id": "c9", "title": "t", "parent": MANAGER,
             "runs": [{"agent_id": "a", "kind": "work", "completed": True}]}

    assert wake._finalize_noncoding_parent(_FakeParent(ticket_id=manager["id"]), [livre]) is True
    assert tickets_svc.get_ticket("proj", manager["id"])["done"] is True


def test_les_predicats_ne_levent_pas_sur_un_launch_failed_malforme():
    """`launch_failed` peut arriver tronqué (legacy, écriture partielle) : aucun prédicat pur
    ne doit lever, et le réveil ne doit jamais contredire le board sur la même donnée."""
    for tordu in ({"id": "1", "launch_failed": True}, {"id": "2", "launch_failed": {}},
                  {"id": "3", "launch_failed": {"error": None}}, {"id": "4"}):
        echoue = tickets_svc.derive_status(tordu) == "lancement échoué"
        assert wake.launch_failed(tordu) is echoue, "le réveil et le board se contredisent"
        assert isinstance(wake.ticket_outcome(tordu), str)
        if echoue:
            assert wake.ticket_terminal(tordu) is True, "un mort-né doit rester une issue"
