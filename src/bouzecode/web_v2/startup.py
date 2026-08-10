# [desc] Tout ce qui se joue AVANT app.run : garde d'instance unique + réconciliation au boot. [/desc]
"""Extrait d'`app.py` (seuil ~200 lignes). `main()` enchaîne ces deux étapes :
refuser un second serveur sur le port, puis remettre d'aplomb l'état laissé par
l'arrêt précédent (agents morts, sous-agents interrompus, bandeau « travaux interrompus »).
"""
from __future__ import annotations

import logging
import os
import socket


def fail_if_sibling_server(port: int) -> None:
    """Garde DÉTERMINISTE (pas de course) : un autre process `bouzecode.web_v2 --port {port}`
    tourne-t-il déjà ? Le bind SO_EXCLUSIVEADDRUSE de `fail_if_port_taken` a une fenêtre TOCTOU
    (socket test fermé avant le vrai bind de Werkzeug, qui pose SO_REUSEADDR) → deux instances
    pouvaient coexister silencieusement sur 5056 (double tick wake → courses fichiers
    WinError 5/32 → crash). On refuse au niveau PROCESS avant même de toucher au socket."""
    import psutil
    me = os.getpid()
    # Le python.exe d'un venv (launcher uv/Windows) ré-exécute l'interpréteur RÉEL comme
    # process ENFANT avec le MÊME cmdline : le vrai process (nous) verrait son propre lanceur
    # parent comme un « sibling » web_v2 et refuserait à tort. On exclut donc TOUTE notre
    # ascendance (powershell → shim → python), pas seulement getpid().
    lineage = {me}
    try:
        cursor = psutil.Process(me).ppid()
        for _ in range(20):
            if not cursor or cursor in lineage:
                break
            lineage.add(cursor)
            cursor = psutil.Process(cursor).ppid()
    except Exception:  # noqa: BLE001 — ascendance best-effort ; au pire on garde {me}
        pass
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
    try:
        sock.bind((host, port))
    except OSError as exc:
        raise SystemExit(
            f"web_v2: le port {port} est déjà servi par une autre instance — "
            f"arrête-la d'abord (Get-NetTCPConnection -LocalPort {port})."
        ) from exc
    finally:
        sock.close()


def reconcile_boot_state() -> None:
    """Remet d'aplomb, mono-thread, ce que le dernier arrêt du serveur a laissé en plan.

    1. Réconcilie les agents morts non clôturés — sinon ces zombies se font réconcilier
       LAZY dans le chemin chaud `list_agents` et wedgent `/api/projects` + `/tree`.
    2. Reprend les sous-agents (validate/merge/work dispatché) morts sur ticket OUVERT.
       Doit tourner AVANT le rapport : un sous-agent repris (ou dont l'échec est stampé
       `auto_resume_error`) est ensuite classé correctement par le bandeau.
    3. Fige le snapshot des travaux interrompus servi par `GET /api/interrupted`.
    4. Balaie les `.tmp` d'écriture d'index abandonnés par un arrêt brutal précédent.

    Les étapes 2 à 4 sont best-effort : un échec est loggué, jamais fatal au boot.
    """
    from .runtime import runner
    crashed_ids = runner.reconcile_dead_agents()
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
        from .services.work import auto_resume
        resumed = auto_resume.resume_subagents()
        if resumed:
            oks = sum(1 for r in resumed if r.get("ok"))
            print(f"web_v2: reprise auto de {oks}/{len(resumed)} sous-agent(s) "
                  f"interrompu(s)", flush=True)
    except Exception:  # noqa: BLE001 — reprise best-effort, ne bloque pas le boot
        logging.getLogger(__name__).exception("resume_subagents a échoué au boot")
    try:
        from .services.work import interrupted_report
        report = interrupted_report.build_boot_report(crashed_ids)
        if report["items"]:
            print(f"web_v2: {len(report['items'])} travail(aux) interrompu(s) à relancer "
                  f"(voir bandeau /conversations / GET /api/interrupted)", flush=True)
    except Exception:  # noqa: BLE001 — rapport best-effort, ne bloque pas le boot
        logging.getLogger(__name__).exception("build_boot_report a échoué au boot")
