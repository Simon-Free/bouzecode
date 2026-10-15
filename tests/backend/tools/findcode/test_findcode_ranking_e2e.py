"""Ce que FindCode montre et ce qu'il tait : fichiers ignorés, tests relégués, réponse
bornée, symbole introuvable. Modèle simulé, outil réel, dépôt réel dans tmp_path."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."


def findcode(**params) -> str:
    """Un tour : le modèle appelle FindCode avec `params` ; rend le résultat de l'outil."""
    body = "".join(f'<param name="{k}">{v}</param>' for k, v in params.items())
    call = f'{METH}\n<tool_use name="FindCode" id="f1">{body}</tool_use>'
    result = bouzecode(["cherche"], mock_llm=MockLLM([call, CLOSE]))
    return next(m["content"] for m in result.messages
                if m.get("role") == "tool" and m.get("name") == "FindCode")


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_les_fichiers_ignores_et_node_modules_n_apparaissent_pas(tmp_path):
    """Seul le code du projet est indexé : ni .gitignore, ni node_modules, ni .venv."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _write(tmp_path, ".gitignore", "genere/\n")
    _write(tmp_path, "app.py", "def calculer_tarif():\n    return 1\n")
    _write(tmp_path, "genere/copie.py", "def calculer_tarif_copie():\n    return 1\n")
    _write(tmp_path, "node_modules/lib/index.js", "function calculerTarif() {}\n")
    _write(tmp_path, ".venv/lib/site.py", "def calculer_tarif_venv():\n    return 1\n")

    out = findcode(query="calculer tarif", path=tmp_path)

    assert "app.py:L1-2 def calculer_tarif()" in out
    assert "copie" not in out and "node_modules" not in out and "venv" not in out


def test_le_code_passe_avant_ses_tests_sauf_si_la_requete_parle_de_tests(tmp_path):
    """« où est calculé le tarif » : le code d'abord ; « tests du tarif » : les tests d'abord."""
    _write(tmp_path, "tarif.py", "def calculer_tarif(km):\n    return km * 2\n")
    _write(tmp_path, "tests/test_tarif.py",
           "from tarif import calculer_tarif\n\n\ndef test_calculer_tarif():\n"
           "    assert calculer_tarif(1) == 2\n")

    code_first = findcode(query="calculer tarif", path=tmp_path).splitlines()[1]
    tests_first = findcode(query="tests calculer tarif", path=tmp_path).splitlines()[1]

    assert code_first.startswith("1. tarif.py:L1-2 def calculer_tarif(km)")
    assert tests_first.startswith("1. tests/test_tarif.py:L4-5 def test_calculer_tarif()")


def test_un_nom_exact_passe_devant_les_noms_partiels(tmp_path):
    """Un identifiant donné tel quel sort en premier, même entouré de noms voisins."""
    _write(tmp_path, "a.py", "def charger_config_projet():\n    pass\n\n\n"
                             "def charger_config():\n    pass\n\n\n"
                             "def config_charger_tout():\n    pass\n")

    out = findcode(query="charger_config", path=tmp_path)

    assert out.splitlines()[1].startswith("1. a.py:L5-6 def charger_config()")


def test_la_reponse_reste_courte_sur_un_gros_depot(tmp_path):
    """Des centaines de correspondances : dix lignes, et moins de ~1 000 tokens.

    Les 1 200 définitions tiennent dans 12 fichiers : ce qui est éprouvé ici, c'est le
    nombre de CORRESPONDANCES à trier, pas le nombre de fichiers du dépôt (mesuré le
    2026-09-29 : le premier `open` d'un fichier fraîchement écrit sous `Temp` coûte
    plusieurs millisecondes, 300 fichiers pesaient 9,2 s de mise en place pour rien).
    """
    for i in range(12):
        _write(tmp_path, f"pkg{i}/module_{i}.py",
               "\n\n".join(f'def traiter_commande_{i}_{j}(commande, client, options=None):\n'
                           f'    """Traite la commande {j} du client, avec ses options."""\n'
                           f'    return commande' for j in range(100)) + "\n")

    out = findcode(query="traiter commande client", path=tmp_path)

    assert "1200 definitions match, best 10" in out
    assert len(out) < 4000


def test_un_symbole_introuvable_propose_les_plus_proches(tmp_path):
    """Un nom légèrement faux ne renvoie pas un échec sec mais les définitions voisines."""
    _write(tmp_path, "svc.py", "def valider_champs(champs):\n    return champs\n")

    out = findcode(symbol="valider_champ", path=tmp_path)

    assert "No definition named exactly 'valider_champ'" in out
    assert "svc.py:L1-2 def valider_champs(champs)" in out


def test_un_fichier_crlf_donne_les_memes_plages(tmp_path):
    """Les fins de ligne Windows ne décalent pas les numéros de ligne."""
    (tmp_path / "win.py").write_bytes(b"import os\r\n\r\n\r\ndef lire_disque():\r\n    return os\r\n")

    out = findcode(query="lire disque", path=tmp_path)

    assert "win.py:L4-5 def lire_disque()" in out


def test_un_appele_n_est_jamais_une_fonction_de_test_homonyme(tmp_path):
    """Le code qui appelle `charger()` ne « dépend » pas du `charger` défini dans un test."""
    _write(tmp_path, "app.py", "def executer(source):\n    return source.charger()\n")
    _write(tmp_path, "tests/test_app.py", "class Faux:\n    def charger(self):\n        return 1\n")

    out = findcode(symbol="executer", path=tmp_path)

    assert "tests/" not in out


def test_un_mot_courant_de_la_requete_ne_fait_pas_charger_son_homonyme(tmp_path):
    """Cas vécu (B6, « version drift stale api version ») : `load=true` joignait `api()`, une
    fonction de 3 lignes qui porte le nom d'un mot banal de la requête, au lieu de la fonction
    qui couvre la requête. Un nom écrit comme un identifiant (`api_version`) reste, lui, exact."""
    _write(tmp_path, "client.py", "def api(url):\n    return url\n")
    _write(tmp_path, "version.py",
           "def version_drift(boot, disque):\n"
           "    \"\"\"Dérive entre la version chargée au boot et celle du disque (stale).\"\"\"\n"
           "    return boot != disque\n")

    vague = findcode(query="version drift stale api", load="true", path=tmp_path)
    nomme = findcode(query="api", load="true", path=tmp_path)

    assert "--- version.py :: version_drift" in vague and ":: api (" not in vague
    assert "--- client.py :: api (L1-2) ---" in nomme


def test_sans_premier_net_plusieurs_corps_sont_joints_et_c_est_dit(tmp_path):
    """Deux définitions à égalité : pas de faux « meilleur » — les deux corps, et un mot pour le dire."""
    _write(tmp_path, "a.py", "def tarif_nuit():\n    return 2\n\n\ndef tarif_jour():\n    return 1\n")

    out = findcode(query="tarif", load="true", path=tmp_path)

    assert "No clear best match: bodies of the 2 closest" in out
    assert ":: tarif_nuit (" in out and ":: tarif_jour (" in out
