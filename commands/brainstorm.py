# [desc] Implements a multi-persona AI brainstorming command with configurable agent count and iterative debate. [/desc]
"""Brainstorm command — extracted from bouzecode.py."""
from __future__ import annotations

from ui.ansi import clr, info, ok, err
from ._personas import _TECH_PERSONAS, generate_personas

# Re-export for backward compat
_generate_personas = generate_personas


def cmd_brainstorm(args: str, state, config) -> bool:
    """Run a multi-persona iterative brainstorming session on the project.

    Usage: /brainstorm [topic]
    """
    from providers import stream
    import time
    from pathlib import Path
    from tools import ask_input_interactive
    from ui.spinner import _start_tool_spinner, _stop_tool_spinner

    readme_path = Path("README.md")
    readme_content = readme_path.read_text("utf-8", errors="replace") if readme_path.exists() else ""
    claude_md = Path("CLAUDE.md")
    claude_content = claude_md.read_text("utf-8", errors="replace") if claude_md.exists() else ""
    project_files = "\n".join([f.name for f in Path(".").glob("*") if f.is_file() and not f.name.startswith(".")])
    user_topic = args.strip() or "general project improvement and architectural evolution"

    if config.get("_telegram_incoming"):
        agent_count = 5
    else:
        try:
            ans = ask_input_interactive(clr(f"  How many agents? (2-100, default 5) > ", "cyan"), config).strip()
            agent_count = int(ans) if ans else 5
            agent_count = max(2, min(agent_count, 100))
        except (ValueError, KeyboardInterrupt, EOFError):
            agent_count = 5

    snapshot = f"""PROJECT CONTEXT:
README:
{readme_content[:3000]}

CLAUDE.MD:
{claude_content[:1000]}

ROOT FILES:
{project_files}

USER FOCUS: {user_topic}
"""
    curr_model = config["model"]

    info(clr(f"Generating {agent_count} topic-appropriate expert personas...", "dim"))
    personas = generate_personas(user_topic, curr_model, config, count=agent_count)
    if not personas:
        info(clr("(persona generation failed, using default tech personas)", "dim"))
        personas = dict(list(_TECH_PERSONAS.items())[:agent_count])

    def get_identity(letter):
        try:
            from faker import Faker
            fake = Faker()
            return f"{letter}", fake.name()
        except Exception:
            first = ["Alex", "Sam", "Taylor", "Jordan", "Casey", "Riley", "Drew", "Avery"]
            last = ["Garcia", "Martinez", "Lopez", "Hernandez", "Gonzalez", "Sanchez", "Ramirez", "Torres"]
            import random
            return f"{letter}", f"{random.choice(first)} {random.choice(last)}"

    outputs_dir = Path("brainstorm_outputs")
    outputs_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_file = outputs_dir / f"brainstorm_{ts}.md"
    brainstorm_history = []

    ok(f"Starting {agent_count}-Agent Brainstorming Session on: {clr(user_topic, 'bold')}")
    info(clr("Generating diverse perspectives...", "dim"))

    def call_persona(persona_name, p_data, history):
        letter, name = get_identity(persona_name[0].upper())
        system_prompt = f"""You are {name}, the {p_data['role']}. Identity: Agent {letter}.
{p_data['desc']}

TOPIC UNDER DISCUSSION: {user_topic}

PROJECT CONTEXT (if relevant to the topic):
{snapshot}

INSTRUCTIONS:
1. Provide 3-5 concrete, actionable insights or ideas from your expert perspective on the topic.
2. If there are prior ideas from other agents, briefly acknowledge them and build upon or challenge them.
3. Be specific, well-reasoned, and professional. Stay in character as your role.
4. Prefix each of your points with: [Agent {letter} — {name}]
5. Output your response in clean Markdown.
"""
        user_msg = f"TOPIC: {user_topic}\n\nPRIOR IDEAS FROM DEBATE:\n{history or 'No previous ideas yet. You are the first to speak.'}"
        full_response = []
        internal_config = config.copy()
        internal_config["no_tools"] = True
        try:
            from providers import TextChunk
            for event in stream(curr_model, system_prompt, [{"role": "user", "content": user_msg}], [], internal_config):
                if isinstance(event, TextChunk):
                    full_response.append(event.text)
        except Exception as e:
            return f"Error from Agent {letter}: {e}"
        return "".join(full_response).strip()

    full_log = [f"# Brainstorming Session: {user_topic}", f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}", f"**Model:** {curr_model}", "---"]

    for p_name, p_data in personas.items():
        icon = p_data.get("icon", "\U0001f916")
        info(f"{icon} {clr(p_data['role'], 'yellow')} is thinking...")
        _start_tool_spinner()
        hist_text = "\n\n".join(brainstorm_history) if brainstorm_history else ""
        content = call_persona(p_name, p_data, hist_text)
        _stop_tool_spinner()
        if content:
            brainstorm_history.append(content)
            full_log.append(f"## {icon} {p_data['role']}\n{content}")
            print(clr("  └─ Perspective captured.", "dim"))
        else:
            err(f"  └─ Failed to capture {p_name} perspective.")

    final_output = "\n\n".join(full_log)
    out_file.write_text(final_output, encoding="utf-8")
    ok(f"Brainstorming complete! Results saved to {clr(str(out_file), 'bold')}")

    info(clr("Injecting debate results into current session for final analysis...", "dim"))
    synthesis_prompt = f"""I have just completed a multi-agent brainstorming session regarding: '{user_topic}'.
The full debate results have been saved to the file: {out_file}

Please read that file, then analyze the diverse perspectives. Identify the strongest ideas, potential conflicts, and provide a synthesized 'Master Plan' with concrete phases. Be concise and actionable."""

    return ("__brainstorm__", synthesis_prompt, str(out_file))


def _save_synthesis(state, out_file: str) -> None:
    """Append the last assistant response as the synthesis section of the brainstorm file."""
    from pathlib import Path
    for msg in reversed(state.messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            return
        text = text.strip()
        if not text:
            return
        try:
            with Path(out_file).open("a", encoding="utf-8") as f:
                f.write("\n\n---\n\n## \U0001f9e0 Synthesis — Master Plan\n\n")
                f.write(text)
                f.write("\n")
            ok(f"Synthesis appended to {clr(out_file, 'bold')}")
        except Exception as e:
            err(f"Failed to save synthesis: {e}")
        return
