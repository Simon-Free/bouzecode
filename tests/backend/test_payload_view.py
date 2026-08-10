# [desc] Le contexte d'un tour est une VUE : le journal stocke des deltas, la lecture rend le payload entier. [/desc]
"""Le journal des payloads ne stocke que ce qui change ; le payload complet est reconstitué.

LE DÉFAUT (2026-07-30) : chaque enregistrement portait le tableau `messages` ENTIER — toute la
conversation telle que le modèle la voyait. Croissance en O(tours²). Mesuré sur une session
réelle : 219 Mo pour 431 enregistrements, dont le dernier — le seul complet — pèse 1 Mo. Sur
le parc : 3 191 sessions, 8 Go.

Ces tests figent les quatre situations que le repli doit traverser sans se tromper : l'ajout
normal, la compaction (qui réécrit la tête), la reprise de process (enregistrement absolu), et
les journaux écrits AVANT le changement.
"""
import json

from bouzecode.backend.core.payload_view import (
    fold_records,
    load_turn_map,
    load_turn_records,
)

MSG = lambda t: {"role": "user", "content": t}  # noqa: E731 — lisibilité des cas


def test_un_tour_qui_ajoute_des_messages_ne_stocke_que_les_nouveaux():
    """Le cas courant : la conversation s'allonge, seul l'ajout est écrit."""
    replie = fold_records([
        {"turn": 1, "messages": [MSG("a")]},
        {"turn": 2, "keep": 1, "append": [MSG("b"), MSG("c")]},
    ])

    assert [m["content"] for m in replie[1]["messages"]] == ["a", "b", "c"]


def test_une_compaction_qui_reecrit_la_tete_se_decrit_toute_seule():
    """Compaction : `keep` petit, `append` gros — le repli repart de la nouvelle tête."""
    replie = fold_records([
        {"turn": 1, "messages": [MSG("a"), MSG("b"), MSG("c")]},
        {"turn": 2, "keep": 1, "append": [MSG("RESUME")]},
    ])

    assert [m["content"] for m in replie[1]["messages"]] == ["a", "RESUME"]


def test_un_enregistrement_absolu_reinitialise_la_base():
    """Après une reprise de process, on ne connaît plus l'état précédent : on écrit tout."""
    replie = fold_records([
        {"turn": 1, "keep": 0, "append": [MSG("a")]},
        {"turn": 2, "messages": [MSG("apres reprise")]},
        {"turn": 3, "keep": 1, "append": [MSG("suite")]},
    ])

    assert [m["content"] for m in replie[2]["messages"]] == ["apres reprise", "suite"]


def test_un_journal_ecrit_avant_le_changement_se_relit_tel_quel():
    """Compatibilité : tout enregistrement ancien porte `messages`, donc reste absolu."""
    ancien = [
        {"turn": 1, "messages": [MSG("a")]},
        {"turn": 2, "messages": [MSG("a"), MSG("b")]},
    ]

    replie = fold_records(ancien)

    assert [m["content"] for m in replie[1]["messages"]] == ["a", "b"]


def test_le_dernier_enregistrement_d_un_tour_gagne(tmp_path):
    """Deux enregistrements par tour (avant/après stream) : le plus riche est écrit en dernier."""
    journal = tmp_path / "turns.jsonl"
    journal.write_text("\n".join(json.dumps(r) for r in [
        {"turn": 1, "messages": [MSG("a")]},
        {"turn": 1, "keep": 1, "append": [], "token_counts": {"in_tokens": 42}},
    ]), encoding="utf-8")

    par_tour = load_turn_map("peu-importe", payloads_dir=tmp_path)

    assert par_tour[1]["token_counts"]["in_tokens"] == 42
    assert [m["content"] for m in par_tour[1]["messages"]] == ["a"]


def test_un_journal_absent_ne_fait_pas_echouer_la_lecture(tmp_path):
    """Une session sans journal (dumps purgés) rend une liste vide, jamais une erreur."""
    assert load_turn_records("inconnue", payloads_dir=tmp_path / "vide") == []


def test_ecriture_puis_relecture_rendent_les_payloads_d_origine(tmp_path, monkeypatch):
    """Le tour complet : on écrit trois appels, on relit — chaque payload est celui envoyé."""
    from bouzecode.backend.agent import payload_dump

    monkeypatch.setattr(payload_dump, "_payload_dir", lambda sid: tmp_path)
    payload_dump._last_payload.clear()
    etat = type("S", (), {"turn_count": 0, "context_state": type("C", (), {"notes": {}})()})()

    envoyes = [
        [MSG("a")],
        [MSG("a"), MSG("b")],
        [MSG("a"), MSG("REMPLACE")],          # compaction : la tête change
    ]
    for i, payload in enumerate(envoyes, start=1):
        etat.turn_count = i
        payload_dump.dump_turn_payload(etat, "sess", payload)

    relus = load_turn_records("sess", payloads_dir=tmp_path)

    assert [r["messages"] for r in relus] == envoyes


def test_les_gros_textes_ne_sont_ecrits_qu_une_fois(tmp_path, monkeypatch):
    """Le VRAI poste du journal : la note et les blocs système, pas les messages.

    Mesuré sur une session réelle de 219 Mo : les notes pesaient 137 Mo (63 %) et les blocs
    système 78 Mo (35 %) — les messages, 2 Mo. Les deux gros champs contiennent le MÊME texte
    de méthodologie, qui grossit d'un bloc par tour et était réécrit en entier à chaque fois.
    Adressés par bloc, ils ne sont écrits qu'une fois, et partagent leurs blocs entre eux."""
    from bouzecode.backend.agent import payload_dump

    monkeypatch.setattr(payload_dump, "_payload_dir", lambda sid: tmp_path)
    payload_dump._last_payload.clear()
    payload_dump._blocs_connus.clear()
    etat = type("S", (), {"turn_count": 0, "context_state": type("C", (), {"notes": {}})()})()

    blocs = []
    for tour in range(1, 21):
        blocs.append(f"## bloc {tour}\n" + "x" * 2000)
        note = "\n\n".join(blocs)
        etat.turn_count = tour
        etat.context_state.notes = {"methodology": note}
        payload_dump.dump_turn_payload(
            etat, "sess", [MSG(f"tour {tour}")],
            system_blocks=[{"text": "PROMPT FIXE", "cache_control": {"type": "ephemeral"}},
                           {"text": note}])

    poids = (tmp_path / "turns.jsonl").stat().st_size
    note_finale = "\n\n".join(blocs)
    # L'ancien comportement écrivait la note ET les blocs système en entier à chaque tour.
    cumul = sum(len("\n\n".join(blocs[:t])) * 2 for t in range(1, 21))
    assert poids < cumul / 5, f"{poids} octets pour {cumul} en cumul : le gain n'est pas là"

    dernier = load_turn_records("sess", payloads_dir=tmp_path)[-1]
    assert dernier["context_state"]["notes"]["methodology"] == note_finale
    assert dernier["system_blocks"][0]["text"] == "PROMPT FIXE"
    assert dernier["system_blocks"][0]["cache_control"] == {"type": "ephemeral"}
    assert dernier["system_blocks"][1]["text"] == note_finale


def test_le_journal_pese_les_ajouts_et_non_le_cumul(tmp_path, monkeypatch):
    """La garantie de fond : 20 tours d'ajouts ne stockent pas 20 fois la conversation."""
    from bouzecode.backend.agent import payload_dump

    monkeypatch.setattr(payload_dump, "_payload_dir", lambda sid: tmp_path)
    payload_dump._last_payload.clear()
    etat = type("S", (), {"turn_count": 0, "context_state": type("C", (), {"notes": {}})()})()

    conversation = []
    for tour in range(1, 21):
        conversation = conversation + [MSG("m" * 500)]
        etat.turn_count = tour
        payload_dump.dump_turn_payload(etat, "sess", list(conversation))

    poids = (tmp_path / "turns.jsonl").stat().st_size
    # Cumul (l'ancien comportement) = 1+2+…+20 = 210 messages ecrits ; deltas = 20.
    assert poids < 20 * 500 * 3, f"journal de {poids} octets : la croissance reste quadratique"
