# [desc] Tout ce qui se joue AVANT app.run : garde d'instance unique + réconciliation au boot. [/desc]
"""Extrait d'`app.py` (seuil ~200 lignes). `main()` enchaîne ces deux étapes :
refuser un second serveur sur le port, puis remettre d'aplomb l'état laissé par
l'arrêt précédent (agents morts, sous-agents interrompus, bandeau « travaux interrompus »).
"""
from __future__ import annotations

import logging
import os
import socket


def _lineage() -> set[int]:
    """Notre pid et toute notre ascendance. Le python.exe d'un venv (lanceur uv/Windows)
    ré-exécute l'interpréteur réel comme ENFANT avec le même cmdline : sans cette exclusion,
    le vrai serveur verrait son propre lanceur comme une instance sœur."""
    import psutil
    lineage = {os.getpid()}
    try:
        cursor = psutil.Process(os.getpid()).ppid()
        for _ in range(20):
            if not cursor or cursor in lineage:
                break
            lineage.add(cursor)
            cursor = psutil.Process(cursor).ppid()
    except Exception:  # noqa: BLE001 — ascendance best-effort ; au pire on garde notre pid
        pass
    return lineage


def fail_if_sibling_server(port: int) -> None:
    """Refuse de démarrer si un autre process `bouzecode.web_v2 --port {port}` tourne déjà.

    Garde au niveau PROCESS, sans course : le bind exclusif de `fail_if_port_taken` a une
    fenêtre TOCTOU (Werkzeug rebinde avec SO_REUSEADDR) qui laissait deux instances coexister
    sur le même port."""
    import psutil
    lineage = _lineage()
    needles = (f"--port {port}", f"--port={port}")
    for proc in psutil.process_iter(["pid", "cmdline"]):
        if proc.info["pid"] in lineage:
            continue
        cmdline = " ".join(proc.info.get("cmdline") or [])
        if "bouzecode.web_v2" in cmdline and any(n in cmdline for n in needles):
            raise SystemExit(
                f"web_v2: une instance tourne DÉJÀ (pid {proc.info['pid']}) sur le port {port} "
                f"— arrête-la d'abord (bouzeui.ps1 kill, ou Stop-Process {proc.info['pid']})."
            )


def fail_if_port_taken(host: str, port: int) -> None:
    """Le dev server Flask bind avec SO_REUSEADDR : sous Windows deux serveurs
    peuvent se lier au même port en silence (agents fantômes, courses sur les
    caches, env différents selon l'instance qui répond). Bind exclusif de test
    pour refuser le démarrage si une instance écoute déjà."""
    fail_if_sibling_server(port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    else:
        # POSIX : sans SO_REUSEADDR, le bind échoue tant qu'il reste des connexions TIME_WAIT
        # sur le port — celles qu'une instance ARRÊTÉE laisse derrière elle pendant 60 s dès
        # qu'un client (navigateur, agent) avait une connexion ouverte. Le redémarrage était
        # alors refusé à tort. Avec SO_REUSEADDR, Linux refuse toujours le bind si un socket
        # ÉCOUTE sur le port : c'est exactement l'instance vivante qu'on veut détecter.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        raise SystemExit(
            f"web_v2: le port {port} est déjà servi par une autre instance — "
            f"arrête-la d'abord (Get-NetTCPConnection -LocalPort {port})."
        ) from exc
    finally:
        sock.close()


def message_instance_passive(detenteur: dict) -> str:
    """Ce qu'affiche un second serveur sur le même parc : il sert l'interface, sans plus."""
    qui = (f"pid {detenteur.get('pid', '?')}, port {detenteur.get('port', '?')}"
           if detenteur else "détenteur inconnu")
    return (f"web_v2: instance PASSIVE — le serveur de référence de ce parc tourne déjà "
            f"({qui}). Ni watchdog, ni ménage du pool chaud, ni réconciliation ni signalement "
            f"des interruptions au boot dans ce process : il ne fait que servir l'interface et l'API.")


def reconcile_boot_state() -> None:
    """Remet d'aplomb, mono-thread, ce que le dernier arrêt du serveur a laissé en plan.

    1. Réconcilie les agents morts non clôturés — sinon ces zombies se font réconcilier
       LAZY dans le chemin chaud `list_agents` et wedgent `/api/projects` + `/tree`.
    2. Signale chaque sous-agent (work dispatché par un manager, merge hérité) interrompu sur
       un ticket OUVERT : message mis en file pour son parent, ou signalement s'il n'a pas de
       parent joignable. AUCUN agent n'est relancé d'office (spec ticketing D4, principe B4).
    3. Fige le snapshot des travaux interrompus servi par `GET /api/agents?state=interrupted`.
    4. Balaie les `.tmp` d'écriture d'index abandonnés par un arrêt brutal précédent.

    Les étapes 2 à 4 sont best-effort : un échec est loggué, jamais fatal au boot.
    """
    from .runtime.runner import agent_registre
    crashed_ids = agent_registre.reconcile_dead_agents()
    if crashed_ids:
        print(f"web_v2: {len(crashed_ids)} agent(s) mort(s) réconcilié(s) au démarrage", flush=True)
    # Le boot est le seul moment MONO-THREAD : aucun tmp ne peut appartenir à une écriture en
    # cours de ce process. Un serveur tué entre l'écriture et le replace en laisse un derrière
    # lui à vie (70 relevés sur le poste, datés de trois semaines).
    from .services.sessions import meta_index, store
    orphelins = meta_index.sweep_orphan_tmp(store.CACHE_PATH)
    if orphelins:
        print(f"web_v2: {len(orphelins)} fichier(s) .tmp d'index abandonné(s) supprimé(s)",
              flush=True)
    try:
        from .services.work import interruptions_boot
        signales = interruptions_boot.signaler_les_interruptions()
        if signales:
            print(f"web_v2: {len(signales)} sous-agent(s) interrompu(s) signalé(s) à leur "
                  f"parent ou à l'humain (aucune relance d'office)", flush=True)
    except Exception:  # noqa: BLE001 — signalement best-effort, ne bloque pas le boot
        logging.getLogger(__name__).exception("signaler_les_interruptions a échoué au boot")
    try:
        from .services.work import interrupted_report
        report = interrupted_report.build_boot_report(crashed_ids)
        if report["items"]:
            print(f"web_v2: {len(report['items'])} travail(aux) interrompu(s) à relancer "
                  f"(voir bandeau /conversations / GET /api/agents?state=interrupted)", flush=True)
    except Exception:  # noqa: BLE001 — rapport best-effort, ne bloque pas le boot
        logging.getLogger(__name__).exception("build_boot_report a échoué au boot")
