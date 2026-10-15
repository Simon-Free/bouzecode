"""Executeur VM joue localement : mode tests (JUnit) et mode agent (bundle reimporte en agent/<ticket>)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.remote.paquet.import_resultat import importer_bundle_resultat
from bouzecode.remote.paquet.paquet_transfert import construire_paquet
from bouzecode.remote.vm.vm_runner import environnement_vm, executer_paquet, main


def git(depot: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=depot, check=True, capture_output=True, text=True).stdout.strip()


def creer_depot(racine: Path) -> Path:
    racine.mkdir(parents=True)
    git(racine, "init", "-q", "-b", "travail")
    git(racine, "config", "user.email", "test@example.invalid")
    git(racine, "config", "user.name", "Test")
    (racine / "a.txt").write_bytes(b"a\n")
    git(racine, "add", "a.txt")
    git(racine, "commit", "-q", "-m", "initial")
    return racine


def script_python(tmp_path: Path, nom: str, code: str) -> str:
    chemin = tmp_path / nom
    chemin.write_text(code, encoding="utf-8")
    return f'"{sys.executable}" "{chemin}"'


def test_mode_tests_produit_junit_et_code(tmp_path):
    depot = creer_depot(tmp_path / "projet")
    commande = script_python(tmp_path, "faux_pytest.py", (
        "import os, pathlib\n"
        "pathlib.Path(os.environ['BZ_RESULTAT'], 'junit.xml').write_text('<testsuite tests=\"1\"/>')\n"
        "pathlib.Path('test-results').mkdir(); pathlib.Path('test-results', 'echec.png').write_bytes(b'png')\n"
        "print('lance dans', os.getcwd())\n"
        "print('HOME=' + os.environ['HOME'])\n"))
    construire_paquet("bz_t", "tests", commande, {"projet": depot}, {}, tmp_path / "paquet")

    bilan = executer_paquet(tmp_path / "paquet", tmp_path / "travail", tmp_path / "resultat")

    assert bilan["code"] == 0
    assert bilan["junit"] is True
    assert bilan["captures"] == ["test-results"]
    assert (tmp_path / "resultat" / "captures" / "test-results" / "echec.png").read_bytes() == b"png"
    assert json.loads((tmp_path / "resultat" / "resultat.json").read_text(encoding="utf-8")) == bilan
    sortie = (tmp_path / "resultat" / "sortie.log").read_text(encoding="utf-8")
    assert "lance dans" in sortie
    assert f"HOME={tmp_path / 'travail' / 'home'}" in sortie  # HOME jetable, pas celui du compte


def test_mode_agent_rend_une_branche_reimportable(tmp_path):
    depot = creer_depot(tmp_path / "projet")
    (depot / "brouillon.txt").write_bytes(b"non suivi local\n")
    commande = script_python(tmp_path, "faux_agent.py", (
        "import pathlib, subprocess\n"
        "pathlib.Path('b.txt').write_text('ecrit par agent\\n')\n"
        "subprocess.run(['git', 'add', 'b.txt'], check=True)\n"
        "subprocess.run(['git', 'commit', '-q', '-m', 'agent: ajoute b'], check=True)\n"
        "pathlib.Path('c.txt').write_text('oublie par agent\\n')\n"
        "pathlib.Path('__pycache__').mkdir(); pathlib.Path('__pycache__', 'b.cpython-311.pyc').write_bytes(b'x')\n"
        "pathlib.Path('.pytest_cache').mkdir(); pathlib.Path('.pytest_cache', 'v').write_text('x')\n"))
    manifeste = construire_paquet("bz_a", "agent", commande, {"projet": depot}, {"projet": ["brouillon.txt"]},
                                  tmp_path / "paquet")

    bilan = executer_paquet(tmp_path / "paquet", tmp_path / "travail", tmp_path / "resultat")
    info = bilan["projets"]["projet"]
    import_local = importer_bundle_resultat(depot, tmp_path / "resultat" / info["bundle"],
                                            manifeste["projets"][0]["branche_travail"], "agent/ticket42")

    assert bilan["code"] == 0
    assert info["auto_commites"] == ["c.txt"]
    assert import_local["ok"] is True
    assert import_local["sha"] == info["sha_fin"]
    assert git(depot, "log", "--format=%s", "agent/ticket42") == (
        "bz: travail non commite de l'agent distant\nagent: ajoute b\ninitial")
    assert git(depot, "show", "agent/ticket42:b.txt") == "ecrit par agent"
    assert "brouillon.txt" not in git(depot, "ls-tree", "-r", "--name-only", "agent/ticket42")
    assert git(depot, "rev-parse", "--abbrev-ref", "HEAD") == "travail"


def test_options_llm_deviennent_les_variables_de_l_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("RD_OPTION_LLM_OPENAI_API_KEY_PP", "cle")
    monkeypatch.setenv("RD_OPTION_LLM_PREPROD_ENDPOINT", "https://preprod.invalid")

    env = environnement_vm(tmp_path / "travail", tmp_path / "resultat")

    assert env["OPENAI_API_KEY_PP"] == "cle" and env["PREPROD_ENDPOINT"] == "https://preprod.invalid"
    assert not [cle for cle in env if cle.startswith("RD_OPTION_LLM_")]


def test_projet_outil_n_est_jamais_rapatrie(tmp_path):
    principal = creer_depot(tmp_path / "projet")
    outil = creer_depot(tmp_path / "outil")
    commande = script_python(tmp_path, "salit_l_outil.py",
                             "import pathlib\npathlib.Path('..', 'outil', 'trace.txt').write_text('x')\n")
    construire_paquet("bz_o", "agent", commande, {"projet": principal, "outil": outil}, {}, tmp_path / "paquet",
                      outils={"outil"})

    bilan = executer_paquet(tmp_path / "paquet", tmp_path / "travail", tmp_path / "resultat")

    assert list(bilan["projets"]) == ["projet"]
    assert not (tmp_path / "resultat" / "outil.resultat.bundle").exists()


def test_magasin_ca_du_systeme_est_impose_aux_clients_http(tmp_path, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")

    env = environnement_vm(tmp_path / "travail", tmp_path / "resultat", bundle_ca=bundle)
    sans_bundle = environnement_vm(tmp_path / "travail", tmp_path / "resultat", bundle_ca=tmp_path / "absent")

    assert env["SSL_CERT_FILE"] == env["REQUESTS_CA_BUNDLE"] == str(bundle)
    assert "REQUESTS_CA_BUNDLE" not in sans_bundle


def test_dossier_de_run_retire_meme_si_la_reconstruction_echoue(tmp_path):
    (tmp_path / "paquet").mkdir()
    (tmp_path / "paquet" / "manifeste.json").write_text(json.dumps({
        "run_id": "bz_x", "mode": "tests", "commande": "true", "projets": [
            {"slug": "p", "source": "bundle_complet", "bundle": "absent.bundle", "sha": "0" * 40,
             "branche_travail": "agent/x"}]}), encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError):
        main([str(tmp_path / "paquet"), str(tmp_path / "travail"), str(tmp_path / "resultat")])

    assert not (tmp_path / "travail").exists()
