"""Course wake : un run dont la session DISQUE porte un close_reason CONTRÔLÉ mais dont le
PROCESS est mort SANS que POST /completed soit passé (callback perdu, agent déchargé) NE doit
JAMAIS être déclaré planté. Le watchdog rejoue la fin du run selon la table
`close_reasons.issue_de_fin` : livré pour une clôture qui prouve une livraison, « arrêté sans
finir » (`idle_no_delivery`) pour une fin maîtrisée sans réponse — jamais `stopped`.

Joué par le watchdog lui-même (`wake.tick`) sur une vraie session JSON et un vrai store ;
l'agent est DÉCHARGÉ (aucune fiche) : seule sa session dans le parc dit comment il a fini."""
import ast
import json
from pathlib import Path

import pytest

from bouzecode.web_v2 import close_reasons
from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import constats, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import en_cours, projet


def _write_session(path: Path, *, close_reason: str) -> None:
    path.write_text(
        json.dumps({"messages": [{"role": "assistant", "content": "VERDICT: OK"}],
                    "close_reason": close_reason}),
        encoding="utf-8",
    )


@pytest.fixture()
def parc(tmp_path, monkeypatch):
    projet(tmp_path, monkeypatch, "proj")
    return agent_fiche.AGENTS_DIR


def _ticket_au_callback_perdu(parc: Path, agent_id: str, close_reason: str) -> dict:
    """Un run ouvert (le hook /completed n'est jamais passé), agent déchargé, dont la
    session disque porte `close_reason`."""
    parc.mkdir(parents=True, exist_ok=True)
    _write_session(parc / f"{agent_id}.session.json", close_reason=close_reason)
    return en_cours("proj", agent_id)


def _ticks(n: int = constats.MORTS_AVANT_CRASH + 1) -> None:
    for _ in range(n):
        wake.tick()


@pytest.mark.parametrize("close_reason", sorted(close_reasons.CONTROLLED_CLOSE_REASONS))
def test_une_fin_controlee_n_est_jamais_un_plantage(parc, close_reason):
    """Pour CHAQUE close_reason contrôlé, un callback /completed perdu est réconcilié par le
    watchdog et le ticket n'est jamais déclaré planté. Le cas 'final_answer_deferred' est le
    bug réel observé (ticket bloqué 'à relire')."""
    ticket = _ticket_au_callback_perdu(parc, "gracefuldead001", close_reason)
    _ticks()
    frais = tickets_svc.get_ticket("proj", ticket["id"])
    attendu, _code = close_reasons.issue_de_fin(close_reason)
    assert frais["state"] == attendu != etats.STOPPED
    assert bool(frais["runs"][0].get("completed")) is (attendu == etats.DELIVERED)


def test_une_mort_en_vol_reste_un_arret(parc):
    """Un close_reason de mort en vol (ex 'partial_stream') n'a pas fini proprement."""
    ticket = _ticket_au_callback_perdu(parc, "brokendead001", "partial_stream")
    _ticks()
    frais = tickets_svc.get_ticket("proj", ticket["id"])
    assert frais["state"] == etats.STOPPED and frais["runs"][0].get("completed") is not True


def test_deferred_close_gated_until_checks_drain(parc):
    """Un close `final_answer_deferred` dont les checks différés ne sont PAS encore drainés
    (`<session>.deferred.json` encore sur disque) n'avance pas : l'avancer livrerait avant le
    déploiement en file. Drain terminé → réconciliation."""
    agent_id = "deferredpending01"
    ticket = _ticket_au_callback_perdu(parc, agent_id, "final_answer_deferred")
    deferred_file = parc / f"{agent_id}.session.json.deferred.json"
    deferred_file.write_text(
        json.dumps({"answer": "deploying", "checks": [{"command": "deploy", "timeout": 900}]}),
        encoding="utf-8")
    _ticks()
    assert tickets_svc.get_ticket("proj", ticket["id"])["state"] == etats.RUNNING, (
        "close deferred réconcilié AVANT le drain de ses checks (merge prématuré)")
    deferred_file.unlink()
    wake.tick()
    assert tickets_svc.get_ticket("proj", ticket["id"])["state"] == etats.DELIVERED


def test_graceful_reasons_stay_in_sync_with_loop_fire_completion():
    """GARDE ANTI-DIVERGENCE : tout close_reason passé à `_fire_completion` dans
    backend/agent/loop.py DOIT faire avancer le ticket côté reconciler. Sinon un agent qui a
    déclenché `on_completion` — donc fini proprement — reste « à relire » indéfiniment :
    c'est le bug qu'avait causé l'omission de 'final_answer_deferred'.

    Le parse doit tolérer `_fire_completion(state, config, state.close_reason or "x")` : la
    version précédente exigeait un littéral en 3ᵉ position et est devenue AVEUGLE quand la
    boucle s'est mise à honorer le close_reason déjà posé — elle n'y voyait plus qu'une
    raison sur trois. L'égalité stricte a laissé place à une inclusion : les raisons venues
    de loop_turn.py (`ends_turn_tool`…) n'apparaissent pas ici mais avancent aussi. Le
    recouvrement complet est tenu par tests/web_v2/test_close_reasons_table.py."""
    from bouzecode.backend.agent import loop as loop_mod

    tree = ast.parse(Path(loop_mod.__file__).read_text(encoding="utf-8"))
    fired = {
        constante.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_fire_completion" and len(node.args) >= 3
        for constante in ast.walk(node.args[2])
        if isinstance(constante, ast.Constant) and isinstance(constante.value, str)
    }
    assert fired, "aucun call site _fire_completion trouvé — le parse a-t-il changé ?"
    assert {"final_answer", "final_answer_deferred", "text_no_tools"} <= fired, (
        f"le parse ne voit plus les clôtures gracieuses connues : {sorted(fired)}")
    manquantes = sorted(fired - set(close_reasons.CONTROLLED_CLOSE_REASONS))
    assert not manquantes, (
        f"divergence watchdog/loop : loop.py déclenche on_completion sur {manquantes}, que la "
        f"table des fins (close_reasons) classerait en mort en vol")
