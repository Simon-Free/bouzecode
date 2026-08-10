# [desc] Tests du cache TTL de l'etat de version servi par GET /api/version : rafale de polls = un seul calcul, derive quand meme detectee apres le TTL, node_modules hors empreinte. [/desc]
"""GET /api/version est poll en tache de fond par toutes les pages. Relire git + scanner le
source a chaque appel le faisait repondre en ~300-500 ms (l'endpoint le plus lent de l'API,
30x les autres). Il est desormais memorise quelques secondes : ces tests verrouillent le gain
ET le fait que le bandeau de derive reste fiable."""
import os

from bouzecode.web_v2 import version as _version


class _Clock:
    """Horloge injectee : le test avance le temps a la main, aucun sleep reel."""

    def __init__(self):
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds


class _CountingState:
    """Compte les recalculs et delegue au VRAI version_state (aucun mock)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *args):
        self.calls += 1
        return _version.version_state(*args)


def _source_tree(tmp_path) -> tuple[str, str]:
    """Un dossier source d'un fichier ; renvoie (chemin, empreinte de « boot »)."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "mod.py").write_text("v1", encoding="utf-8")
    return str(source), _version.source_fingerprint(str(source))


def _touch_after_boot(source: str) -> None:
    """Edite le source comme le ferait un merge apres le demarrage du serveur."""
    edited = os.path.join(source, "mod.py")
    with open(edited, "w", encoding="utf-8") as handle:
        handle.write("v2 — edite apres le boot")
    os.utime(edited, (2_000_000_000, 2_000_000_000))


def test_deux_polls_rapproches_ne_relisent_pas_le_disque(tmp_path):
    """Deux appels dans la meme seconde partagent UN seul calcul."""
    source, boot_fingerprint = _source_tree(tmp_path)
    clock, compute = _Clock(), _CountingState()
    args = ("bootsha", "1.2.3", str(tmp_path), boot_fingerprint, source)

    first = _version.cached_version_state(*args, now=clock, ttl=10.0, compute=compute)
    _touch_after_boot(source)  # le source bouge JUSTE apres le premier appel
    clock.seconds += 1.0
    second = _version.cached_version_state(*args, now=clock, ttl=10.0, compute=compute)

    assert compute.calls == 1
    assert second == first
    assert second["source_drift"] is False  # vu au prochain recalcul, pas dans la seconde


def test_une_modif_est_detectee_une_fois_le_ttl_expire(tmp_path):
    """Le cache retarde le bandeau de quelques secondes, il ne l'annule pas."""
    source, boot_fingerprint = _source_tree(tmp_path)
    clock, compute = _Clock(), _CountingState()
    args = ("bootsha", "1.2.3", str(tmp_path), boot_fingerprint, source)

    assert _version.cached_version_state(
        *args, now=clock, ttl=10.0, compute=compute)["source_drift"] is False

    _touch_after_boot(source)
    clock.seconds += 10.1  # TTL ecoule

    state = _version.cached_version_state(*args, now=clock, ttl=10.0, compute=compute)
    assert compute.calls == 2
    assert state["source_drift"] is True
    assert state["drift"] is True


def test_le_scan_ignore_node_modules(tmp_path):
    """node_modules pesait 825 des 877 repertoires parcourus pour un seul fichier que le
    process ne charge pas : il sort de l'empreinte (scan 66 ms -> 3,5 ms)."""
    source, boot_fingerprint = _source_tree(tmp_path)
    (tmp_path / "src" / "node_modules" / "pkg").mkdir(parents=True)

    (tmp_path / "src" / "node_modules" / "pkg" / "index.html").write_text("x", encoding="utf-8")

    assert _version.source_fingerprint(source) == boot_fingerprint
