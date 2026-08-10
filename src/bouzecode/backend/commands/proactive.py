# [desc] Proactive background polling that sends wake-up prompts after user inactivity. [/desc]
"""Proactive background polling — fires wake-up prompts after inactivity."""

import time
import traceback

try:
    from bouzecode.ui.ansi import info, err
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "red": "\033[31m", "reset": "\033[0m"}
    def info(msg):  print(C["cyan"] + msg + C["reset"])
    def err(msg):   print(C["red"] + f"Error: {msg}" + C["reset"], file=sys.stderr)


def _proactive_watcher_loop(config):
    """Background daemon that fires a wake-up prompt after a period of inactivity."""
    while True:
        time.sleep(1)
        if not config.get("_proactive_enabled"):
            continue
        try:
            now = time.time()
            interval = config.get("_proactive_interval", 300)
            last = config.get("_last_interaction_time", now)
            if now - last >= interval:
                config["_last_interaction_time"] = now
                cb = config.get("_run_query_callback")
                if cb:
                    cb(f"(System Automated Event) You have been inactive for {interval} seconds. "
                       "Before doing anything else, review your previous messages in this conversation. "
                       "If you said you would implement, fix, or do something and didn't finish it, "
                       "continue and complete that work now. "
                       "Otherwise, check if you have any pending tasks to execute or simply say 'No pending tasks'.")
        except Exception as e:
            traceback.print_exc()
            print(f"\n[proactive watcher error]: {e}", flush=True)


def cmd_proactive(args: str, state, config) -> bool:
    """Manage proactive background polling.

    /proactive            — show current status
    /proactive 5m         — enable, trigger after 5 min of inactivity
    /proactive 30s / 1h   — enable with custom interval
    /proactive off        — disable
    """
    args = args.strip().lower()

    if not args:
        if config.get("_proactive_enabled"):
            interval = config.get("_proactive_interval", 300)
            info(f"Proactive background polling: ON  (triggering every {interval}s of inactivity)")
        else:
            info("Proactive background polling: OFF  (use /proactive 5m to enable)")
        return True

    if args == "off":
        config["_proactive_enabled"] = False
        info("Proactive background polling: OFF")
        return True

    multiplier = 1
    val_str = args
    if args.endswith("m"):
        multiplier = 60
        val_str = args[:-1]
    elif args.endswith("h"):
        multiplier = 3600
        val_str = args[:-1]
    elif args.endswith("s"):
        val_str = args[:-1]

    try:
        val = int(val_str)
        config["_proactive_interval"] = val * multiplier
    except ValueError:
        err(f"Invalid duration: '{args}'. Use '5m', '30s', '1h', or 'off'.")
        return True

    config["_proactive_enabled"] = True
    config["_last_interaction_time"] = time.time()
    info(f"Proactive background polling: ON  (triggering every {config['_proactive_interval']}s of inactivity)")
    return True
