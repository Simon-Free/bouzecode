# [desc] Serveur de RÉFÉRENCE : un seul process par parc d'agents (verrou OS exclusif) a le droit d'agir seul sur la flotte (watchdog, ménage du pool, reprise au boot) ; les autres sont passifs. [/desc]
"""Un seul serveur agit de lui-même sur un parc d'agents donné.

Le 2026-09-29, un agent a lancé `create_app(); app.run(port=5099)` sur les VRAIES données pour
un test de fumée : ce second serveur armait son watchdog (capable de relancer des agents) et
son ménage du pool chaud, en parallèle du serveur de production, avec le code d'un worktree.
Un `python -m bouzecode.web_v2 --port 5099` passait, lui, par `main` et rejouait même la
reprise automatique des sous-agents.

Règle : l'automatisme qui agit sur la flotte sans demande humaine (watchdog `wake`, ménage du
pool chaud, réconciliation et reprise au boot) ne démarre que dans le process qui détient le
verrou EXCLUSIF `<parc>/.serveur_de_reference.lock`. Le verrou est tenu par l'OS pour la durée
du process : il tombe tout seul si le serveur meurt (pas de fichier « pid » à nettoyer). Le
premier `main()` sur un parc le prend (bouzeui.ps1 → le serveur de production) ; un bac à sable
au HOME isolé a son propre parc, donc son propre verrou. `create_app()` seul ne le prend jamais.

La CLI (`bouzecode tickets suivre`, ui/tickets_cli) sans serveur tient le verrou le temps d'UN
pas de suivi (`pour_un_pas_cli`, marque `.suivi_cli.<pid>.json`) ; `acquerir` attend la fin d'un tel
pas, et `serveur_vivant` ne le prend pas pour un serveur.
"""
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from bouzecode.web_v2.services.horodatage import maintenant_iso

NOM_DU_VERROU = ".serveur_de_reference.lock"
NOM_DE_LA_FICHE = ".serveur_de_reference.json"
#: Posé par la CLI (`bouzecode tickets suivre`) le temps d'UN pas de suivi : un serveur qui
#: démarre à cet instant attend la fin du pas au lieu de rester passif toute sa vie.
#: Une marque PAR process (`.suivi_cli.<pid>.json`) : deux CLI ne s'effacent pas l'une l'autre.
PREFIXE_DU_PAS_CLI = ".suivi_cli."
ATTENTE_PAS_CLI_S = 60.0

_verrou = None  # descripteur tenu ouvert tant que le process vit


def _parc() -> Path:
    from .runtime.runner import agent_fiche  # relu à l'appel : les tests isolent AGENTS_DIR
    return Path(agent_fiche.AGENTS_DIR)


def _verrouiller(fichier) -> bool:
    """Verrou exclusif NON bloquant sur le 1er octet ; False s'il est déjà tenu."""
    try:
        fichier.seek(0)  # msvcrt verrouille à partir de la position courante
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fichier.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fichier.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _deverrouiller(fichier) -> None:
    fichier.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(fichier.fileno(), msvcrt.LK_UNLCK, 1)
    fichier.close()


def _ouvrir_et_verrouiller():
    """Le fichier du verrou, verrouillé par ce process ; None si quelqu'un le tient."""
    parc = _parc()
    parc.mkdir(parents=True, exist_ok=True)
    fichier = open(parc / NOM_DU_VERROU, "a+b")  # noqa: SIM115 — tenu par l'appelant
    if not _verrouiller(fichier):
        fichier.close()
        return None
    return fichier


def marque_du_pas_cli(pid: int | None = None) -> Path:
    return _parc() / f"{PREFIXE_DU_PAS_CLI}{pid or os.getpid()}.json"


def _pas_cli_en_cours() -> bool:
    """Une AUTRE CLI est dans un pas de suivi (sa marque existe, son process vit)."""
    import psutil
    pids = {marque.name[len(PREFIXE_DU_PAS_CLI):-len(".json")]
            for marque in _parc().glob(f"{PREFIXE_DU_PAS_CLI}*.json")}
    return any(pid.isdigit() and int(pid) != os.getpid() and psutil.pid_exists(int(pid))
               for pid in pids)


def acquerir(port: int) -> bool:
    """Prend le rôle de serveur de référence du parc courant. True si ce process l'a. Si une CLI
    le tient pour un pas de suivi, attend la fin du pas (au plus `ATTENTE_PAS_CLI_S`)."""
    global _verrou
    if _verrou is not None:
        return True
    limite = time.monotonic() + ATTENTE_PAS_CLI_S
    fichier = _ouvrir_et_verrouiller()
    while fichier is None and _pas_cli_en_cours() and time.monotonic() < limite:
        time.sleep(0.2)
        fichier = _ouvrir_et_verrouiller()
    if fichier is None:
        return False
    _verrou = fichier
    (_parc() / NOM_DE_LA_FICHE).write_text(json.dumps({
        "pid": os.getpid(), "port": port, "depuis": maintenant_iso("auto"),
    }), encoding="utf-8")
    return True


def est_reference() -> bool:
    return _verrou is not None


def tenu_ailleurs() -> bool:
    """Un AUTRE process tient le verrou (un serveur de référence vit sur ce parc)."""
    if _verrou is not None:
        return False
    fichier = _ouvrir_et_verrouiller()
    if fichier is None:
        return True
    _deverrouiller(fichier)
    return False


def serveur_vivant() -> bool:
    """Un serveur de référence tient ce parc. Le pas de suivi d'une CLI (qui tient le verrou
    quelques secondes) n'en est pas un : on attend qu'il finisse avant de conclure."""
    limite = time.monotonic() + ATTENTE_PAS_CLI_S
    while tenu_ailleurs():
        if not _pas_cli_en_cours() or time.monotonic() > limite:
            return True
        time.sleep(0.2)
    return False


@contextmanager
def pour_un_pas_cli():
    """Tient le verrou le temps d'UN pas de suivi de la CLI, sans réécrire la fiche du serveur.
    Rend True si ce process agit seul sur la flotte pendant le pas, False si un serveur le tient
    (le pas doit alors se contenter de lire)."""
    if _verrou is not None:
        yield True
        return
    marque = marque_du_pas_cli()
    marque.parent.mkdir(parents=True, exist_ok=True)
    marque.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    fichier = _ouvrir_et_verrouiller()
    try:
        yield fichier is not None
    finally:
        if fichier is not None:
            _deverrouiller(fichier)
        marque.unlink(missing_ok=True)


def detenteur() -> dict:
    """Ce que le serveur de référence a déclaré (pid, port), pour le message du passif."""
    try:
        return json.loads((_parc() / NOM_DE_LA_FICHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def relacher() -> None:
    """Rend le verrou (tests ; en production il tombe avec le process)."""
    global _verrou
    if _verrou is not None:
        _verrou.close()
        _verrou = None
