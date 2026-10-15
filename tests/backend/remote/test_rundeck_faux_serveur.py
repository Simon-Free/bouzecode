"""Client Rundeck contre un faux serveur HTTP local + gabarit de job + refus de lancer_sur_rundeck."""
import base64
import re

import pytest
import yaml


from bouzecode.remote import lancer_sur_rundeck
from bouzecode.remote.lancement import commande_agent, projets_demandes
from bouzecode.remote.transport.rundeck_client import ClientRundeck, ErreurRundeck
from bouzecode.remote.transport.settings import EnvironnementInterdit, ReglagesDistants, charger_reglages
from bouzecode.remote.vm.job_template import yaml_job


def reglages(url: str, jeton: str = "jeton-test") -> ReglagesDistants:
    return ReglagesDistants("rec", url, jeton, "https://compte.file.core.windows.net", "share", "", "")


def test_cycle_complet_import_lancement_suivi_suppression(faux_rundeck, etat_faux_rundeck):
    client = ClientRundeck(reglages(faux_rundeck))
    job_id = client.importer_job(yaml_job("bz_1", {"a.py": "print(1)"}, "a.py", ["RUN_ID"], "essai"))
    lancement = client.lancer_job(job_id, {"RUN_ID": "bz_1"})
    etat = client.attendre_fin(lancement["execution_id"], delai_max_s=5, pas_s=0.1)

    assert lancement == {"execution_id": "77", "url": "http://rundeck/execution/77"}
    assert etat["statut"] == "succeeded" and etat["termine"] is True
    assert client.journal_execution("77") == "ligne 1\nligne 2"
    client.supprimer_job(job_id)
    assert etat_faux_rundeck.jobs == {}


def test_import_ne_reecrit_jamais_un_job_existant(faux_rundeck):
    client = ClientRundeck(reglages(faux_rundeck))
    client.importer_job(yaml_job("bz_1", {"a.py": ""}, "a.py", [], "essai"))
    with pytest.raises(ErreurRundeck, match="import refuse"):
        client.importer_job(yaml_job("bz_1", {"a.py": ""}, "a.py", [], "essai"))


def test_jeton_invalide_leve_une_erreur_lisible(faux_rundeck):
    with pytest.raises(ErreurRundeck, match="HTTP 403"):
        ClientRundeck(reglages(faux_rundeck, jeton="mauvais")).verifier_acces()


def test_gabarit_job_embarque_le_code_et_exporte_les_options():
    job = yaml.safe_load(yaml_job("bz_2", {"run.py": "print('é')"}, "run.py", ["RUN_ID"], "essai",
                                  options_secretes=("ANTHROPIC_AUTH_TOKEN",)))[0]
    script = job["sequence"]["commands"][0]["script"]
    code_b64 = re.search(r"echo '([A-Za-z0-9+/=]+)' \| base64 -d", script).group(1)

    assert job["name"] == "BZ_bz_2" and job["scheduleEnabled"] is False
    assert base64.b64decode(code_b64).decode("utf-8") == "print('é')"
    assert "export RD_OPTION_RUN_ID='@option.RUN_ID@'" in script
    assert [o for o in job["options"] if o["name"] == "ANTHROPIC_AUTH_TOKEN"][0]["secure"] is True


def test_seul_rec_est_autorise():
    with pytest.raises(EnvironnementInterdit):
        charger_reglages("prod")


def test_refus_explicites_de_lancer_sur_rundeck(monkeypatch):
    assert lancer_sur_rundeck({}, {"cible": "local"})["code"] == "cible_indisponible"
    assert lancer_sur_rundeck({}, {"cible": "rundeck", "environnement": "prod"})["code"] == "environnement_interdit"
    monkeypatch.delenv("RUNDECK_PRIVATE_TOKEN_REC", raising=False)
    refus = lancer_sur_rundeck({}, {"cible": "rundeck", "projets": ["x"]})
    assert refus["ok"] is False and refus["code"] == "acces_rundeck_manquant"
    assert "RUNDECK_PRIVATE_TOKEN_REC" in refus["message"]


def test_projet_principal_vient_de_l_execution_sinon_du_slug_du_ticket():
    assert projets_demandes({"slug": "demo"}, {"projets": ["outils", "demo"]}) == ["outils", "demo"]
    assert projets_demandes({"slug": "demo"}, {}) == ["demo"]
    assert projets_demandes({}, {}) == []
    assert '--cwd "$BZ_TRAVAIL/outils"' in commande_agent("outils")
