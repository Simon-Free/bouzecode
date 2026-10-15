# [desc] testd : vrai démon sur port éphémère — file à 1 slot (position visible), échecs remontés pendant le run, test le plus long en cours, annulation, état relu sur disque [/desc]
from __future__ import annotations

import os
import time

from bouzecode.backend.testd.rendu import attendre, texte_etat
from tests.backend.testd.aides import commande, projet

_LENT = {
    "test_lent.py": """
        import time
        def test_echoue_vite():
            assert "rouge" == "vert", "couleur inattendue"
        def test_long():
            time.sleep(6)
    """,
}


def _attendre_etat(client, job_id, predicat, delai_s=60):
    fin = time.monotonic() + delai_s
    while time.monotonic() < fin:
        etat = client.etat(job_id)
        if predicat(etat):
            return etat
        time.sleep(0.2)
    raise AssertionError(f"état jamais atteint : {etat}")


def test_file_echecs_en_direct_et_rapport_final(demon, tmp_path):
    racine = projet(tmp_path / "p", _LENT)
    env = dict(os.environ)
    premier = demon.soumettre(commande("test_lent.py"), env, str(racine), 120, "")
    second = demon.soumettre(commande("test_lent.py"), env, str(racine), 120, "")
    assert second["position"] >= 1
    assert demon.etat(second["job_id"])["state"] == "queued"

    # L'échec arrive au modèle PENDANT que le test long tourne encore.
    etat = _attendre_etat(demon, premier["job_id"], lambda e: e["failures"] and e.get("longest"))
    assert etat["state"] == "running"
    assert "couleur inattendue" in etat["failures"][0]["excerpt"]
    assert etat["longest"]["id"].endswith("test_long")
    texte = texte_etat(etat)
    assert "✗" in texte and "test_echoue_vite" in texte and "le plus long en cours" in texte

    final = attendre(premier["job_id"], 60, au_premier_echec=False)
    assert final["state"] == "done" and (final["passed"], final["failed"]) == (1, 1)
    assert "1 failed, 1 passed" in texte_etat(final)

    annule = demon.annuler(second["job_id"])
    assert annule["state"] in ("cancelled", "running")
    assert _attendre_etat(demon, second["job_id"], lambda e: e["state"] == "cancelled")


def test_etat_relu_sur_disque_apres_arret_du_demon(demon, tmp_path):
    racine = projet(tmp_path / "p", {"test_ok.py": "def test_ok():\n    assert True\n"})
    job = demon.soumettre(commande("test_ok.py"), dict(os.environ), str(racine), 60, "")
    attendre(job["job_id"], 60, au_premier_echec=False)
    demon.arreter_demon()
    _attendre_disparition(tmp_path / "testd_home" / "daemon.json")
    # Le démon suivant ne connaît plus ce job : l'état final vient du disque.
    assert demon.etat(job["job_id"])["state"] == "done"


def _attendre_disparition(fichier, delai_s=30):
    fin = time.monotonic() + delai_s
    while fichier.exists() and time.monotonic() < fin:
        time.sleep(0.2)
    assert not fichier.exists()
