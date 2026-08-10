# [desc] Dataclass defining AgentProfile with composable skills, tools, hooks, plugins, model, and prompt fields. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentProfile:
    """A composable agent profile declaring capabilities.

    `kind` marks the role in the unified agent model:
      - "user"     : a normal switchable agent (user/project/catalog profile) — default.
      - "system"   : a builtin switchable agent shipped with bouzecode (general-purpose,
                     meta-agent, manager). Always present, listed under "Agents système".
      - "fragment" : a composable-only capability fragment (e.g. `deferred`) merged onto
                     every agent — never listed or switched to on its own.
      - "app"      : a standalone end-user agent owned by a host app (e.g. a chatbot
                     embedded in a web app). Its host loads it DIRECTLY by path and routes
                     to it as a single agent (no manager, no sub-agents). It shares the
                     unified profile FORMAT but is NOT a bouzecode dev typology: it must
                     never appear as a dispatchable typology or a switchable/spawnable agent.
    `description` is the when-to-use line shown in listings and used by the Agent() spawn
    catalog; it is identity metadata and is NOT propagated by merge_profiles."""

    name: str = ""
    description: str = ""
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    requires_plugins: list[str] = field(default_factory=list)
    model: str = ""
    system_prompt_extra: str = ""
    kind: str = "user"
    # `plan_mode: false` opts a profile OUT of the WritePlan auto-validation /
    # plan-validation pause (dispatcher/manager: it plans by delegating, never
    # writes a validated plan nor blocks on awaiting_plan_validation). Default on.
    plan_mode: bool = True
    # `require_recap: true` forces the close validator to reject a FinalAnswer that
    # does not carry the 6 mandatory recap sections (`## 1.` .. `## 6.`). Off by
    # default; enabled on the coder profile.
    require_recap: bool = False
    # `inherit_default: false` opts a profile OUT of the shared `default` PROSE layer
    # (code-discovery ladder, batching / depends_on rules, TDD). ON by default: a named
    # profile EXTENDS the default layer, it does not replace it. Only a profile whose
    # role CONTRADICTS that layer sets it to false (e.g. the read-only `manager`, which
    # has no Edit/Write/Bash and must never be told to write tests).
    # This flag governs PROSE ONLY — tool allowlists are never composed (see
    # profiles/AGENTS.md § "Précédence de composition").
    inherit_default: bool = True
