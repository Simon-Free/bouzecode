"""Supprimer un chantier depuis le Bureau ne doit JAMAIS emporter ses tickets.

On passe par les vrais endpoints HTTP, comme le fait le bouton ✕ de l'écran : créer un
chantier, y rattacher un ticket, supprimer le chantier, puis vérifier que le ticket est
toujours là — retombé dans « non rattachées », d'où l'utilisateur peut le replacer.
"""

import pytest


@pytest.fixture
def client():
    #  Pas de fixture partagée dans conftest.py : le pattern maison est de fabriquer
    #  l'app localement. La base est déjà isolée par l'autouse `_isolate_production_state`.
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_supprimer_un_chantier_detache_ses_tickets_sans_les_detruire(client):
    macro = client.post("/api/macros", json={"titre": "Chantier a jeter"})
    assert macro.status_code < 400, macro.get_data(as_text=True)
    macro_id = macro.get_json()["macro"]["id"]

    micro = client.post("/api/micros", json={"titre": "Ticket a garder", "macro_id": macro_id})
    assert micro.status_code < 400, micro.get_data(as_text=True)
    micro_id = micro.get_json()["micro"]["id"]

    efface = client.delete(f"/api/macros/{macro_id}")
    assert efface.status_code == 200, efface.get_data(as_text=True)
    corps = efface.get_json()
    assert corps["supprime"] == macro_id
    assert corps["detachees"] == 1

    restants = client.get("/api/macros").get_json()
    macros = restants.get("macros", restants) if isinstance(restants, dict) else restants
    assert macro_id not in [str(m.get("id")) for m in macros]

    lignes = client.get("/api/lignes").get_json()
    orphelines = [str(l.get("id")) for l in lignes["non_rattachees"]]
    assert micro_id in orphelines, "le ticket a disparu avec son chantier"
    ailleurs = [str(l.get("id")) for c in lignes["chantiers"] for l in c.get("lignes", [])]
    assert micro_id not in ailleurs


def test_supprimer_un_chantier_inconnu_repond_404(client):
    assert client.delete("/api/macros/inexistant-xyz").status_code == 404
