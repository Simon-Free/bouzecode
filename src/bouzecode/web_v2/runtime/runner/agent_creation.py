# [desc] Premier lancement d'un agent (`create_agent`) et reprise sous un nouvel identifiant (`resume_agent`). [/desc]
"""Naissance d'un agent : premier spawn, ou reprise de la session d'un autre sous un NOUVEL
identifiant, inscrite au ticket de l'agent repris."""
from __future__ import annotations

import secrets
import subprocess
import uuid

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import agent_fiche
from . import agent_commande
from . import agent_vivacite
from . import agent_respawn
from .agent_fiche import Agent


def create_agent(prompt: str, model: str, cwd: str, profile: str = "",
                 parent: str = "",
                 ticket_slug: str = "", ticket_id: str = "",
                 run_kind: str = "work", worktree_root: str = "",
                 base_venv: str = "") -> Agent:
    agent_id = uuid.uuid4().hex[:12]
    stdout_path = agent_fiche.AGENTS_DIR / f"{agent_id}.out.log"
    session_path = agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"
    ipc_dir = agent_fiche.AGENTS_DIR / f"{agent_id}.ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        *agent_commande._agent_cmd(),
        "--session-file", str(session_path),
        "--web-agent-dir", str(ipc_dir),
    ]
    if model:
        cmd += ["-m", model]
    cmd += agent_commande._profile_launch_args(profile)
    cmd.append(prompt)

    # Env guard: fail fast if provider env is incomplete
    agent_commande.check_provider_env(model)

    agent = Agent(
        agent_id=agent_id,
        prompt=prompt,
        model=model,
        cwd=cwd,
        pid=0,
        started_at=maintenant_iso("auto"),
        stdout_path=str(stdout_path),
        session_path=str(session_path),
        ipc_dir=str(ipc_dir),
        parent=parent,
        ticket_slug=ticket_slug,
        ticket_id=ticket_id,
        run_kind=run_kind or "work",
        profile=profile,
        worktree_root=worktree_root,
        base_venv=base_venv,
        run_token=secrets.token_hex(16),
    )
    spawn_env = agent_commande._spawn_env(**agent_commande._ticket_env(agent))

    stdout_file = stdout_path.open("wb")
    process = subprocess.Popen(
        cmd,
        cwd=cwd or None,
        stdout=stdout_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=agent_commande.DRAPEAUX_DE_SPAWN,
        env=spawn_env,
    )
    agent.pid = process.pid
    agent.pid_create_time = agent_vivacite._instant_de_creation(process.pid)
    agent_fiche._save(agent)
    # Un agent VIENT DE NAÎTRE : la page d'arbre déjà calculée ne le contient pas, et le front
    # l'attendait jusqu'à expiration du TTL — 7,9 s mesurées le 2026-08-03 entre l'écriture sur
    # disque et son apparition dans /api/agents/tree, pour une information déjà écrite.
    # Import LOCAL : `services.work.fleet` importe ce module, l'importer en tête ferait un cycle.
    from ...services.work import fleet_cache
    fleet_cache.expire_all()
    return agent


def resume_agent(old_agent: Agent, prompt: str, model: str = "") -> Agent:
    """Spawn a new agent that resumes from an existing agent's session."""
    agent_id = uuid.uuid4().hex[:12]
    stdout_path = agent_fiche.AGENTS_DIR / f"{agent_id}.out.log"
    session_path = agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"
    ipc_dir = agent_fiche.AGENTS_DIR / f"{agent_id}.ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)

    use_model = model or old_agent.model
    cmd = agent_commande._agent_cmd()
    if use_model:
        cmd += ["-m", use_model]
    cmd += agent_commande._profile_launch_args(old_agent.profile)
    cmd += [
        "--session-file", str(session_path),
        "--resume-from", old_agent.session_path,
        "--web-agent-dir", str(ipc_dir),
        prompt,
    ]

    # La reprise HÉRITE de l'identité de ticket et de l'environnement de travail de l'agent
    # repris. Sans ça (constat du 2026-09-29, 3eb942805a2c), elle naissait sans ticket ni
    # `run_kind` et sans l'env du hook : sa clôture ne notifiait plus son ticket, son parent
    # n'était pas réveillé, et le Bureau ne la rattachait à rien.
    agent = Agent(
        agent_id=agent_id,
        prompt=prompt,
        model=use_model,
        cwd=old_agent.cwd,
        pid=0,
        started_at=maintenant_iso("auto"),
        stdout_path=str(stdout_path),
        session_path=str(session_path),
        ipc_dir=str(ipc_dir),
        parent=old_agent.parent,
        ticket_slug=old_agent.ticket_slug,
        ticket_id=old_agent.ticket_id,
        run_kind=old_agent.run_kind,
        profile=old_agent.profile,
        worktree_root=old_agent.worktree_root,
        base_venv=old_agent.base_venv,
        reprise_de=old_agent.agent_id,
        titre=_titre_de(old_agent),
        run_token=secrets.token_hex(16),
    )
    stdout_file = stdout_path.open("wb")
    process = subprocess.Popen(
        cmd,
        cwd=agent_respawn._safe_cwd(old_agent.cwd),
        stdout=stdout_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=agent_commande.DRAPEAUX_DE_SPAWN,
        env=agent_commande._spawn_env(**agent_commande._ticket_env(agent)),
    )
    agent.pid = process.pid
    agent.pid_create_time = agent_vivacite._instant_de_creation(process.pid)
    agent_fiche._save(agent)
    ancien = agent_fiche.load_agent(old_agent.agent_id)
    if ancien is not None:
        ancien.reprise_par = agent_id
        agent_fiche._save(ancien)
    _inscrire_la_reprise_au_ticket(agent)
    return agent


def _inscrire_la_reprise_au_ticket(agent: Agent) -> None:
    """La reprise devient le run le plus récent de son ticket : c'est elle que la vivacité, le
    réveil du parent doivent voir."""
    if not (agent.ticket_slug and agent.ticket_id):
        return
    from ...services.work import tickets  # local : `tickets` tire les services
    ticket = tickets.get_ticket(agent.ticket_slug, agent.ticket_id)
    if ticket is not None:
        tickets.add_run(agent.ticket_slug, ticket, agent.agent_id, agent.run_kind, agent.model)


def _titre_de(agent: Agent) -> str:
    """Le titre lisible d'un agent : celui qu'il a hérité s'il est lui-même une reprise."""
    from ...services.work.titres import titre_lisible
    return getattr(agent, "titre", "") or titre_lisible(agent.prompt or "")
