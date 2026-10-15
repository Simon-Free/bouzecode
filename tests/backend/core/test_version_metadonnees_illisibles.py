# [desc] Lire la version de bouzecode ne lève jamais : dist-info sans METADATA, METADATA vide ou sans Version, pyproject corrompu, rien d'installé — vrais site-packages temporaires, sans mock. [/desc]
"""Régression du déploiement Focus du 2026-10-12 : juste après `pip install` sur le partage CIFS
`/persistent`, `importlib.metadata.version("bouzecode")` a levé `TypeError: 'NoneType' object is not
subscriptable` au démarrage de deux runs. Un dist-info présent mais au METADATA illisible doit
donner la version du nom de dossier, avec un warning — jamais une exception."""
from __future__ import annotations

import logging
from importlib.metadata import Distribution

from bouzecode.backend.core.version_paquet import version_paquet
from bouzecode.backend.core.version_session import lire_version_bouzecode

JOURNAL = "bouzecode.backend.core.version_paquet"


def _site_packages(tmp_path, metadata: str | None):
    """Arborescence site-packages réelle : `bouzecode/` + `bouzecode-3.5.120.dist-info/`."""
    site = tmp_path / "site-packages"
    (site / "bouzecode").mkdir(parents=True)
    dist_info = site / "bouzecode-3.5.120.dist-info"
    dist_info.mkdir()
    if metadata is not None:
        (dist_info / "METADATA").write_text(metadata, encoding="utf-8")
    return site


def test_le_piege_existe_importlib_ne_rend_pas_de_version(tmp_path):
    site = _site_packages(tmp_path, metadata=None)
    distribution = next(iter(Distribution.discover(name="bouzecode", path=[str(site)])))
    # Python 3.12 : version None ; importlib récent : md_none(None)['Version'] → TypeError,
    # le plantage du 2026-10-12. Dans les deux cas, aucune version exploitable.
    try:
        resultat = distribution.version
    except TypeError as erreur:
        resultat = type(erreur).__name__
    assert resultat in (None, "TypeError")


def test_dist_info_sans_metadata_rend_la_version_du_dossier(tmp_path, caplog):
    site = _site_packages(tmp_path, metadata=None)
    with caplog.at_level(logging.WARNING, logger=JOURNAL):
        assert version_paquet("bouzecode", chemins=[str(site)]) == "3.5.120"
    assert "dist-info" in caplog.text and "3.5.120" in caplog.text


def test_metadata_vide_rend_la_version_du_dossier(tmp_path, caplog):
    site = _site_packages(tmp_path, metadata="")
    with caplog.at_level(logging.WARNING, logger=JOURNAL):
        assert version_paquet("bouzecode", chemins=[str(site)]) == "3.5.120"
    assert "Version" in caplog.text


def test_metadata_sans_champ_version_rend_la_version_du_dossier(tmp_path):
    site = _site_packages(tmp_path, metadata="Metadata-Version: 2.1\nName: bouzecode\n")
    assert version_paquet("bouzecode", chemins=[str(site)]) == "3.5.120"


def test_metadata_saine_est_lue_sans_warning(tmp_path, caplog):
    site = _site_packages(tmp_path, metadata="Metadata-Version: 2.1\nName: bouzecode\nVersion: 3.5.121\n")
    with caplog.at_level(logging.WARNING, logger=JOURNAL):
        assert version_paquet("bouzecode", chemins=[str(site)]) == "3.5.121"
    assert caplog.text == ""


def test_paquet_absent_rend_none(tmp_path):
    vide = tmp_path / "vide"
    vide.mkdir()
    assert version_paquet("bouzecode", "bouzecode", chemins=[str(vide)]) is None


def test_lire_version_bouzecode_survit_au_metadata_absent(tmp_path, caplog):
    site = _site_packages(tmp_path, metadata=None)
    with caplog.at_level(logging.WARNING, logger=JOURNAL):
        assert lire_version_bouzecode(site / "bouzecode", chemins=[str(site)]) == "3.5.120"


def test_lire_version_bouzecode_rend_unknown_quand_rien_n_est_lisible(tmp_path, caplog):
    vide = tmp_path / "vide"
    (vide / "bouzecode").mkdir(parents=True)
    with caplog.at_level(logging.WARNING, logger=JOURNAL):
        assert lire_version_bouzecode(vide / "bouzecode", chemins=[str(vide)]) == "unknown"
    assert "unknown" in caplog.text


def test_pyproject_corrompu_retombe_sur_le_paquet_installe(tmp_path, caplog):
    site = _site_packages(tmp_path, metadata="Metadata-Version: 2.1\nName: bouzecode\nVersion: 3.5.122\n")
    (site / "bouzecode" / "pyproject.toml").write_text("[project\nname = ", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=JOURNAL):
        assert lire_version_bouzecode(site / "bouzecode", chemins=[str(site)]) == "3.5.122"
    assert "illisible" in caplog.text
