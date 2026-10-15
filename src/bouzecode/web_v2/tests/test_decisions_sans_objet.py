"""« Décision à prendre » sur le worktree / la branche d'un agent : une seule ligne ouverte par
objet, et archivée automatiquement (avec une trace) quand cet objet n'existe plus.

Cas réel (essai 3, 2026-09-24/25) : la racine a clos trois fois (clôture, puis deux réveils)
et déclaré à chaque fois la même décision sur le worktree résiduel `agent/fee42a91`, sous trois
titres différents. Le Bureau affichait trois lignes « Décision à prendre », et elles y sont
restées alors que le worktree et la branche avaient déjà disparu.

Vrai dépôt git en tmp, vrai worktree (`worktrees.provision` / `reap`), vraie base isolée ; la
clôture passe par `ouvrir_micros_de_cloture` (le pont de `FinalAnswer`), le tick par
`wake.tick`, et on lit `/api/lignes` comme le front.
"""
import subprocess

from bouzecode.web_v2.services.work import micros, tickets, wake, worktrees
from bouzecode.web_v2.services.work.cloture_micros import ouvrir_micros_de_cloture
from bouzecode.web_v2.tests.test_v3_statut_des_taches import SLUG, client, ligne  # noqa: F401


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True, text=True)


def _enfant_dans_son_worktree(tmp_path) -> dict:
    """Un ticket d'enfant qui a travaillé dans son worktree (branche agent/<id>)."""
    depot = tmp_path / "depot"
    depot.mkdir()
    _git(depot, "init", "-b", "main")
    _git(depot, "commit", "--allow-empty", "-m", "init")
    ticket = tickets.create_ticket(SLUG, "Vue Tinder", "go")
    ticket["worktree"] = worktrees.provision(str(depot), ticket["id"], base_branch="main")
    tickets.update_ticket(SLUG, ticket)
    return ticket


def _decision(titre: str, corps: str = "") -> dict:
    return {"titre": titre, "corps": corps, "decision": True}


def _decisions_ouvertes_sur(objet: str) -> list[dict]:
    return [m for m in micros.list_micros(decision=True)
            if objet in m["titre"] and m["etat"] in ("brouillon", "prete")]


def test_trois_clotures_sur_le_meme_worktree_ne_font_qu_une_decision(tmp_path):
    """Trois clôtures, trois libellés, un seul objet (agent/<id>) → une seule ligne à décider."""
    ticket = _enfant_dans_son_worktree(tmp_path)
    branche = f"agent/{ticket['id']}"

    for titre in (f"Trancher le sort du worktree résiduel {branche} (vue Tinder non commitée)",
                  f"Trancher le sort du worktree résiduel {branche} (brouillon non commité)",
                  f"Worktree résiduel {branche} : le garder ou le supprimer ?"):
        ouvrir_micros_de_cloture([_decision(titre)], ticket_id="racine01", slug=SLUG)

    assert len(_decisions_ouvertes_sur(branche)) == 1


def test_deux_decisions_sur_deux_objets_distincts_restent_deux_lignes(tmp_path):
    """Contrôle : le rapprochement se fait par objet, pas par ressemblance du libellé."""
    ouvrir_micros_de_cloture([_decision("Worktree résiduel agent/0000aaaa : le garder ?"),
                              _decision("Worktree résiduel agent/0000bbbb : le garder ?")],
                             ticket_id="racine02", slug=SLUG)

    assert len(_decisions_ouvertes_sur("agent/0000aaaa")) == 1
    assert len(_decisions_ouvertes_sur("agent/0000bbbb")) == 1


def test_une_decision_dont_le_worktree_et_la_branche_ont_disparu_est_archivee_avec_une_trace(
        client, tmp_path):
    """Worktree et branche supprimés → au tick, la ligne passe « abandonnée » et dit pourquoi."""
    ticket = _enfant_dans_son_worktree(tmp_path)
    branche = f"agent/{ticket['id']}"
    [creee] = ouvrir_micros_de_cloture(
        [_decision(f"Worktree résiduel {branche} : le garder ou le supprimer ?")],
        ticket_id="racine03", slug=SLUG)

    wake.tick()
    assert ligne(client, creee["id"])["statut_ui"] == "a_decider", "objet encore là : intact"

    worktrees.reap(ticket["worktree"])
    wake.tick()

    vue = ligne(client, creee["id"])
    assert (vue["statut_ui"], vue["segment"]) == ("abandonnee", "archivees")
    assert vue["archive_auto"]["texte"].startswith(
        f"Archivée automatiquement : décision sans objet — le worktree "
        f"{ticket['worktree']['worktree']} et la branche {branche} n'existent plus")


def test_les_doublons_deja_en_base_sont_archives_en_gardant_le_plus_ancien(client, tmp_path):
    """Lignes créées avant ce correctif, objet toujours là → la plus ancienne reste seule."""
    ticket = _enfant_dans_son_worktree(tmp_path)
    branche = f"agent/{ticket['id']}"
    premiere = micros.create_micro(titre=f"Trancher le sort de {branche}", decision=True)
    seconde = micros.create_micro(titre=f"Worktree résiduel {branche} : garder ?", decision=True)

    wake.tick()

    assert ligne(client, premiere["id"])["statut_ui"] == "a_decider"
    vue = ligne(client, seconde["id"])
    assert vue["statut_ui"] == "abandonnee"
    assert vue["archive_auto"]["texte"] == (
        f"Archivée automatiquement : doublon de la décision « Trancher le sort de {branche} » "
        f"({premiere['id']}), même objet {branche}.")
