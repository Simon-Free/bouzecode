# [desc] Package init exposing extension commands: agents, agent switch, skills, and tasks. [/desc]
"""Extension commands: skills, agents, agent switch, tasks."""
from .agents_cmd import cmd_agents, _print_background_notifications
from .agent_switch import cmd_agent
from .skills_mcp import cmd_skills
from .tasks_cmd import cmd_tasks

__all__ = [
    "cmd_agents", "_print_background_notifications",
    "cmd_agent", "cmd_skills", "cmd_tasks",
]
