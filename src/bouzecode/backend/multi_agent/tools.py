# [desc] Registers multi-agent tools (spawn, message, check, list) into the central tool registry. [/desc]
"""Multi-agent tool registrations.

Registers the following tools into the central tool_registry:
  Agent            — spawn a sub-agent (outil_agent)
  MessageAgent     — re-instruct a governed web child (outils_enfants)
  SendMessage      — send a message to a named background agent (outils_enfants)
  CheckAgentResult — check status/result of a child, wait for it or stop it (outils_enfants)
  ListAgentTasks   — list my children (outils_enfants)
  ListAgentTypes   — list available agent type definitions (outils_flotte)
  Fleet            — list / kill governed web agents (outils_flotte)
Schemas live in `schema_agent` and `schemas`.
"""
from __future__ import annotations

from ..core.tool_registry import ToolDef, register_tool
from .outil_agent import _agent_tool
from .outils_enfants import _check_agent_result, _list_agent_tasks, _message_agent, _send_message
from .outils_flotte import _fleet_tool, _list_agent_types
from .schema_agent import SCHEMA_AGENT
from .schemas import (SCHEMA_CHECK_AGENT_RESULT, SCHEMA_FLEET, SCHEMA_LIST_AGENT_TASKS,
                      SCHEMA_LIST_AGENT_TYPES, SCHEMA_MESSAGE_AGENT, SCHEMA_SEND_MESSAGE)


register_tool(ToolDef(
    name="Agent",
    schema=SCHEMA_AGENT,
    func=_agent_tool,
    read_only=False,
    # Pas concurrent_safe : Agent lit l'état git du parent (travail non commité) et doit donc
    # partir APRÈS un `git commit` du même lot. Mais N Agent consécutifs partent ENSEMBLE.
    concurrent_safe=False,
    lot_simultane=True,
))

register_tool(ToolDef(
    name="MessageAgent",
    schema=SCHEMA_MESSAGE_AGENT,
    func=_message_agent,
    read_only=False,
    concurrent_safe=False,
    web_seulement=True,
))

register_tool(ToolDef(
    name="SendMessage",
    schema=SCHEMA_SEND_MESSAGE,
    func=_send_message,
    read_only=False,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="CheckAgentResult",
    schema=SCHEMA_CHECK_AGENT_RESULT,
    func=_check_agent_result,
    read_only=True,
    concurrent_safe=True,
    etat_externe=True,  # l'état des enfants change sans que j'écrive rien
))

register_tool(ToolDef(
    name="ListAgentTasks",
    schema=SCHEMA_LIST_AGENT_TASKS,
    func=_list_agent_tasks,
    read_only=True,
    concurrent_safe=True,
    etat_externe=True,  # l'état des enfants change sans que j'écrive rien
))

register_tool(ToolDef(
    name="ListAgentTypes",
    schema=SCHEMA_LIST_AGENT_TYPES,
    func=_list_agent_types,
    read_only=True,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="Fleet",
    schema=SCHEMA_FLEET,
    func=_fleet_tool,
    read_only=False,
    concurrent_safe=False,
    web_seulement=True,
))
