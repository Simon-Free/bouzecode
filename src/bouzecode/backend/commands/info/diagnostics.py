# [desc] Implements /doctor command combining session status summary with environment health checks. [/desc]
"""Diagnostic command: /doctor = session status + environment checks."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr, info, ok, warn, err
except ImportError:
    from bouzecode import clr, info, ok, warn, err


def cmd_doctor(args: str, state, config) -> bool:
    """Show session status and run installation health checks."""
    import subprocess as _sp
    import sys as _sys
    from ...agent.providers import PROVIDERS, detect_provider
    from ...agent.providers.registry import get_provider_key
    from bouzecode.backend.agent.compaction import estimate_tokens, get_context_limit
    from bouzecode import VERSION

    model = config.get("model", "unknown")
    provider = detect_provider(model)
    perm_mode = config.get("permission_mode", "auto")
    session_id = config.get("_session_id", "N/A")
    turn_count = getattr(state, "turn_count", 0)
    msg_count = len(getattr(state, "messages", []))
    tokens_in = getattr(state, "total_input_tokens", 0)
    tokens_out = getattr(state, "total_output_tokens", 0)
    est_ctx = estimate_tokens(getattr(state, "messages", []))
    ctx_limit = get_context_limit(model)
    ctx_pct = (est_ctx / ctx_limit * 100) if ctx_limit else 0

    # Session summary
    print()
    print(clr("  \u2500\u2500 Session \u2500\u2500", "bold"))
    print(f"  Version:     {VERSION}")
    print(f"  Model:       {model} ({provider})")
    print(f"  Permissions: {perm_mode}")
    print(f"  Session:     {session_id}")
    print(f"  Turns:       {turn_count}  |  Messages: {msg_count}")
    print(f"  Tokens:      {tokens_in:,} in / {tokens_out:,} out")
    print(f"  Context:     ~{est_ctx:,} / {ctx_limit:,} ({ctx_pct:.0f}%)")
    print()

    # Health checks
    ok_n = warn_n = fail_n = 0

    def _print_safe(s):
        try:
            print(s)
        except UnicodeEncodeError:
            print(s.encode("ascii", errors="replace").decode())

    def _ok(msg):
        nonlocal ok_n; ok_n += 1
        _print_safe(clr("  [PASS] ", "green") + msg)

    def _warn(msg):
        nonlocal warn_n; warn_n += 1
        _print_safe(clr("  [WARN] ", "yellow") + msg)

    def _fail(msg):
        nonlocal fail_n; fail_n += 1
        _print_safe(clr("  [FAIL] ", "red") + msg)

    print(clr("  \u2500\u2500 Environment \u2500\u2500", "bold"))

    v = _sys.version_info
    if v >= (3, 10):
        _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _fail(f"Python {v.major}.{v.minor}.{v.micro} (need >=3.10)")

    try:
        r = _sp.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            _ok(f"Git: {r.stdout.strip()}")
        else:
            _fail("Git: not working")
    except Exception:
        _fail("Git: not found")

    try:
        r = _sp.run(["git", "rev-parse", "--is-inside-work-tree"],
                     capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            _ok("Inside a git repository")
        else:
            _warn("Not inside a git repository")
    except Exception:
        _warn("Could not check git repo status")

    key = get_provider_key(provider, config)

    if key:
        _ok(f"API key for {provider}: set ({key[:4]}...{key[-4:]})")
    elif provider in ("ollama", "lmstudio"):
        _ok(f"Provider {provider}: no key needed (local)")
    else:
        _fail(f"API key for {provider}: NOT SET")

    if key or provider in ("ollama", "lmstudio"):
        print(f"  ... testing {provider} API connectivity...")
        try:
            import urllib.request, urllib.error
            prov = PROVIDERS.get(provider, {})
            ptype = prov.get("type", "openai")

            if ptype == "anthropic":
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=json.dumps({
                        "model": model,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    }).encode(),
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
                try:
                    urllib.request.urlopen(req, timeout=10)
                    _ok(f"Anthropic API: reachable, model {model} works")
                except urllib.error.HTTPError as e:
                    if e.code == 401:
                        _fail("Anthropic API: invalid API key (401)")
                    elif e.code == 404:
                        _fail(f"Anthropic API: model {model} not found (404)")
                    elif e.code == 429:
                        _warn("Anthropic API: rate limited (429) -- key is valid")
                    else:
                        _warn(f"Anthropic API: HTTP {e.code}")
                except Exception as e:
                    _fail(f"Anthropic API: connection error -- {e}")

            elif ptype == "ollama":
                base = prov.get("base_url", "http://localhost:11434")
                try:
                    urllib.request.urlopen(f"{base}/api/tags", timeout=5)
                    _ok(f"Ollama: reachable at {base}")
                except Exception:
                    _fail(f"Ollama: cannot reach {base} -- is Ollama running?")

            else:
                base = prov.get("base_url", "")
                if provider == "custom":
                    base = config.get("custom_base_url", base or "")
                if base:
                    models_url = base.rstrip("/") + "/models"
                    req = urllib.request.Request(
                        models_url,
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    try:
                        urllib.request.urlopen(req, timeout=10)
                        _ok(f"{provider} API: reachable")
                    except urllib.error.HTTPError as e:
                        if e.code == 401:
                            _fail(f"{provider} API: invalid API key (401)")
                        elif e.code == 429:
                            _warn(f"{provider} API: rate limited (429) -- key is valid")
                        else:
                            _warn(f"{provider} API: HTTP {e.code}")
                    except Exception as e:
                        _fail(f"{provider} API: connection error -- {e}")
                else:
                    _warn(f"{provider}: no base_url configured")
        except Exception as e:
            _warn(f"API test skipped: {e}")

    print()
    for pname, pdata in PROVIDERS.items():
        if pname == provider:
            continue
        env_var = pdata.get("api_key_env")
        if env_var and os.environ.get(env_var, ""):
            _ok(f"{pname} key ({env_var}): set")

    print()
    for mod, desc in [
        ("rich", "Rich (live markdown rendering)"),
        ("PIL", "Pillow (clipboard image)"),
        ("sounddevice", "sounddevice (voice recording)"),
        ("faster_whisper", "faster-whisper (local STT)"),
    ]:
        try:
            __import__(mod)
            _ok(desc)
        except ImportError:
            _warn(f"{desc}: not installed")

    print()
    claude_md = Path.cwd() / "CLAUDE.md"
    global_md = Path.home() / ".claude" / "CLAUDE.md"
    if claude_md.exists():
        _ok(f"Project CLAUDE.md: {claude_md}")
    else:
        _warn("No project CLAUDE.md in current directory")
    if global_md.exists():
        _ok(f"Global CLAUDE.md: {global_md}")

    ckpt_root = Path.home() / ".nano_claude" / "checkpoints"
    if ckpt_root.exists():
        total = sum(f.stat().st_size for f in ckpt_root.rglob("*") if f.is_file())
        mb = total / (1024 * 1024)
        sessions = sum(1 for d in ckpt_root.iterdir() if d.is_dir())
        if mb > 100:
            _warn(f"Checkpoints: {mb:.1f} MB ({sessions} sessions)")
        else:
            _ok(f"Checkpoints: {mb:.1f} MB ({sessions} sessions)")

    perm = config.get("permission_mode", "auto")
    if perm == "accept-all":
        _warn(f"Permission mode: {perm} (all operations auto-approved)")
    else:
        _ok(f"Permission mode: {perm}")

    print()
    total = ok_n + warn_n + fail_n
    summary = f"  {ok_n} passed, {warn_n} warnings, {fail_n} failures ({total} checks)"
    if fail_n:
        _print_safe(clr(summary, "red"))
    elif warn_n:
        _print_safe(clr(summary, "yellow"))
    else:
        _print_safe(clr(summary, "green"))

    return True
