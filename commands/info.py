# [desc] CLI commands for displaying conversation history, context size, token cost, and timing stats. [/desc]
"""Information commands: history, context, cost, timing."""
from __future__ import annotations

try:
    from ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode import clr, info, ok, warn, err


def _fmt_duration(seconds: float) -> str:
    if seconds < 1.0:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}m{remaining:.0f}s"


def cmd_history(_args: str, state, config) -> bool:
    from ui.replay import replay_messages
    replay_messages(state.messages)
    return True


def cmd_context(_args: str, state, config) -> bool:
    msg_chars = sum(
        len(str(m.get("content", ""))) for m in state.messages
    )
    est_tokens = msg_chars // 4
    info(f"Messages:         {len(state.messages)}")
    info(f"Estimated tokens: ~{est_tokens:,}")
    info(f"Model:            {config['model']}")
    info(f"Max tokens:       {config['max_tokens']:,}")
    return True


def cmd_cost(_args: str, state, config) -> bool:
    from config import calc_cost
    cost = calc_cost(config["model"],
                     state.total_input_tokens,
                     state.total_output_tokens,
                     state.total_cache_read_tokens,
                     state.total_cache_creation_tokens)
    cache_read = getattr(state, "total_cache_read_tokens", 0)
    cache_create = getattr(state, "total_cache_creation_tokens", 0)
    cumulated_in = state.total_input_tokens + cache_read + cache_create
    info(f"Input tokens (distinct):   {state.total_input_tokens:,}")
    info(f"  cache read:              {cache_read:,}")
    info(f"  cache write:             {cache_create:,}")
    info(f"Input tokens (cumulated):  {cumulated_in:,}")
    info(f"Output tokens:             {state.total_output_tokens:,}")
    info(f"Est. cost:                 ${cost:.4f} USD")
    return True


def cmd_timing(_args: str, state, config) -> bool:
    import time as _time
    entries = state.timing_entries
    if not entries:
        info("No timing data yet.")
        return True
    wall = _time.monotonic() - state.conversation_start if state.conversation_start else 0.0
    totals_by_phase: dict[str, float] = {}
    counts_by_phase: dict[str, int] = {}
    ttft_sum = 0.0
    streaming_sum = 0.0
    out_tokens_sum = 0
    in_tokens_sum = 0
    cache_read_sum = 0
    cache_create_sum = 0
    for entry in entries:
        phase = entry["phase"]
        totals_by_phase[phase] = totals_by_phase.get(phase, 0.0) + entry["duration"]
        counts_by_phase[phase] = counts_by_phase.get(phase, 0) + 1
        if phase == "llm":
            ttft_sum += entry.get("ttft", 0.0)
            streaming_sum += entry.get("streaming", 0.0)
            out_tokens_sum += entry.get("out_tokens", 0)
            in_tokens_sum += entry.get("in_tokens", 0)
            cache_read_sum += entry.get("cache_read_tokens", 0)
            cache_create_sum += entry.get("cache_creation_tokens", 0)
    tracked_total = sum(totals_by_phase.values())
    reference = wall if wall > 0 else tracked_total

    def sort_key(item):
        phase, total = item
        return (0 if phase == "llm" else 1, -total)

    label_map = {"llm": "LLM (thinking + streaming)"}
    info(f"Conversation wall time: {_fmt_duration(wall)}")
    info(f"Tracked time:           {_fmt_duration(tracked_total)}")
    print()
    header = f"  {'Phase':<32} {'Count':>6} {'Time':>10} {'% conv':>8} {'Avg TTFT':>10} {'Avg tok/s':>11}"
    print(clr(header, "bold"))
    print(clr("  " + "-" * (len(header) - 2), "dim"))
    for phase, total in sorted(totals_by_phase.items(), key=sort_key):
        label = label_map.get(phase, phase)
        pct = (total / reference * 100.0) if reference > 0 else 0.0
        count = counts_by_phase[phase]
        if phase == "llm":
            avg_ttft = _fmt_duration(ttft_sum / count) if count else "-"
            avg_tps = f"{(out_tokens_sum / streaming_sum):.0f}" if streaming_sum > 0 else "-"
        else:
            avg_ttft = "-"
            avg_tps = "-"
        row = (f"  {label:<32} {count:>6} {_fmt_duration(total):>10} "
               f"{pct:>7.1f}% {avg_ttft:>10} {avg_tps:>11}")
        print(row)
    cumulated_in = in_tokens_sum + cache_read_sum + cache_create_sum
    print()
    info(f"  Tokens: {in_tokens_sum:,} distinct in | {cumulated_in:,} cumulated in "
         f"({cache_read_sum:,} cache read + {cache_create_sum:,} cache write) | "
         f"{out_tokens_sum:,} out")
    return True
