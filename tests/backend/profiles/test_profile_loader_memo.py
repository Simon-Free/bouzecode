"""Profils YAML : décodés une fois par version du fichier (décodeur C de libyaml si présent)."""
import os
from dataclasses import asdict

import yaml

from bouzecode.backend.profiles import loader
from bouzecode.backend.profiles.discovery import builtin_dir


def _ecrire(chemin, texte, decalage_s=0):
    chemin.write_text(texte, encoding="utf-8")
    if decalage_s:
        st = chemin.stat()
        os.utime(chemin, ns=(st.st_atime_ns, st.st_mtime_ns + decalage_s * 10**9))


def test_profil_decode_une_fois_puis_relu_quand_le_fichier_change(tmp_path, monkeypatch):
    chemin = tmp_path / "revue.yaml"
    _ecrire(chemin, "name: revue\nskills: [a, b]\n")
    decodages = []
    vrai = yaml.load
    monkeypatch.setattr(yaml, "load", lambda *a, **k: decodages.append(1) or vrai(*a, **k))
    premiers = [loader.load_profile_from_path(chemin) for _ in range(3)]
    assert all(p == premiers[0] for p in premiers) and premiers[0].skills == ["a", "b"]
    assert len(decodages) == 1
    _ecrire(chemin, "name: revue\nskills: [c]\n", decalage_s=5)
    assert loader.load_profile_from_path(chemin).skills == ["c"]
    assert len(decodages) == 2


def test_modifier_un_profil_rendu_ne_touche_pas_la_memoire(tmp_path):
    chemin = tmp_path / "p.yaml"
    _ecrire(chemin, "name: p\nrequires_plugins:\n  - {name: x, source: git}\n")
    profil = loader.load_profile_from_path(chemin)
    profil.requires_plugins[0]["name"] = "intrus"
    profil.skills.append("intrus")
    relu = loader.load_profile_from_path(chemin)
    assert relu.requires_plugins == [{"name": "x", "source": "git"}] and relu.skills == []


def test_profils_livres_identiques_a_safe_load():
    """Même résultat que l'ancien `yaml.safe_load` pur Python, pour chaque profil livré."""
    fichiers = sorted(builtin_dir().glob("*.y*ml"))
    assert fichiers
    for chemin in fichiers:
        attendu = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        assert loader._lire_yaml(chemin) == attendu, chemin.name
        assert asdict(loader.load_profile_from_path(chemin))["name"] == str(attendu.get("name", chemin.stem))
