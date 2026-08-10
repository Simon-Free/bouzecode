# [desc] Telegram bot bridge: long-polling loop, message/photo handling, and /telegram CLI command. [/desc]
"""Telegram bot bridge — /telegram command and supporting helpers."""
from __future__ import annotations

import json
import threading

try:
    from ui.ansi import clr, ok, warn, err, info
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
         "red": "\033[31m", "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m"}
    def clr(text, *keys): return "".join(C[k] for k in keys) + str(text) + C["reset"]
    def info(msg):  print(clr(msg, "cyan"))
    def ok(msg):    print(clr(msg, "green"))
    def warn(msg):  print(clr(f"Warning: {msg}", "yellow"))
    def err(msg):   print(clr(f"Error: {msg}", "red"), file=sys.stderr)

from tools import ask_input_interactive, _tg_thread_local

# ── Globals ───────────────────────────────────────────────────────────────
_telegram_thread = None
_telegram_stop = threading.Event()


def _tg_api(token: str, method: str, params: dict = None):
    """Call Telegram Bot API. Returns parsed JSON or None on error."""
    import urllib.request, urllib.parse
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _tg_send(token: str, chat_id: int, text: str):
    """Send a message to a Telegram chat, splitting if too long."""
    MAX = 4000
    chunks = [text[i:i+MAX] for i in range(0, len(text), MAX)]
    for chunk in chunks:
        result = _tg_api(token, "sendMessage", {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"})
        if not result or not result.get("ok"):
            _tg_api(token, "sendMessage", {"chat_id": chat_id, "text": chunk})


def _tg_typing_loop(token: str, chat_id: int, stop_event: threading.Event):
    """Send 'typing...' indicator every 4 seconds until stop_event is set."""
    while not stop_event.is_set():
        _tg_api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
        stop_event.wait(4)


def _tg_poll_loop(token: str, chat_id: int, config: dict):
    """Long-polling loop that reads Telegram messages and feeds them to run_query."""
    run_query_cb = config.get("_run_query_callback")
    flush = _tg_api(token, "getUpdates", {"offset": -1, "timeout": 0})
    if flush and flush.get("ok") and flush.get("result"):
        offset = flush["result"][-1]["update_id"] + 1
    else:
        offset = 0
    _tg_send(token, chat_id, "\U0001f7e2 bouzecode is online.\nSend me a message and I'll process it.")

    while not _telegram_stop.is_set():
        try:
            result = _tg_api(token, "getUpdates", {
                "offset": offset, "timeout": 30, "allowed_updates": ["message"],
            })
            if not result or not result.get("ok"):
                _telegram_stop.wait(5); continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                msg_chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")

                if msg_chat_id != chat_id:
                    _tg_api(token, "sendMessage", {"chat_id": msg_chat_id, "text": "\u26d4 Unauthorized."})
                    continue

                # ── Handle photo messages ──
                photo_list = msg.get("photo")
                if photo_list:
                    caption = msg.get("caption", "").strip() or "What do you see in this image? Describe it in detail."
                    file_id = photo_list[-1]["file_id"]
                    try:
                        file_info = _tg_api(token, "getFile", {"file_id": file_id})
                        if file_info and file_info.get("ok"):
                            file_path = file_info["result"]["file_path"]
                            import urllib.request, base64
                            url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                            with urllib.request.urlopen(url, timeout=30) as resp:
                                img_bytes = resp.read()
                            b64 = base64.b64encode(img_bytes).decode("utf-8")
                            size_kb = len(img_bytes) / 1024
                            config["_pending_image"] = b64
                            text = caption
                            print(clr(f"\n  \U0001f4e9 Telegram: \U0001f4f7 image ({size_kb:.0f} KB) + \"{caption[:50]}\"", "cyan"))
                        else:
                            _tg_send(token, chat_id, "\u26a0 Could not download image."); continue
                    except Exception as e:
                        _tg_send(token, chat_id, f"\u26a0 Image error: {e}"); continue

                # ── Handle voice messages ──
                voice_msg = msg.get("voice") or msg.get("audio")
                if voice_msg and not text:
                    file_id = voice_msg["file_id"]
                    duration = voice_msg.get("duration", 0)
                    try:
                        file_info = _tg_api(token, "getFile", {"file_id": file_id})
                        if file_info and file_info.get("ok"):
                            file_path = file_info["result"]["file_path"]
                            import urllib.request
                            url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                            with urllib.request.urlopen(url, timeout=30) as resp:
                                audio_bytes = resp.read()
                            size_kb = len(audio_bytes) / 1024
                            _tg_send(token, chat_id, f"\U0001f399 Voice received ({duration}s, {size_kb:.0f} KB) -- transcribing...")
                            print(clr(f"\n  \U0001f4e9 Telegram: \U0001f399 voice ({duration}s, {size_kb:.0f} KB)", "cyan"))
                            from voice import transcribe_audio_file
                            suffix = ".ogg" if msg.get("voice") else ".mp3"
                            transcribed = transcribe_audio_file(audio_bytes, suffix=suffix)
                            if transcribed:
                                _tg_send(token, chat_id, f"\U0001f4dd Transcribed: \"{transcribed}\"")
                                text = transcribed
                            else:
                                _tg_send(token, chat_id, "\u26a0 No speech detected in voice message."); continue
                        else:
                            _tg_send(token, chat_id, "\u26a0 Could not download voice message."); continue
                    except Exception as e:
                        _tg_send(token, chat_id, f"\u26a0 Voice error: {e}"); continue

                if not text:
                    continue

                # Intercept text if a permission prompt is waiting
                evt = config.get("_tg_input_event")
                if evt:
                    config["_tg_input_value"] = text
                    evt.set(); continue

                # Handle Telegram bot commands
                if text.strip().startswith("/"):
                    tg_cmd = text.strip().lower()
                    if tg_cmd in ("/stop", "/off"):
                        _tg_send(token, chat_id, "\U0001f534 Telegram bridge stopped.")
                        _telegram_stop.set(); break
                    elif tg_cmd == "/start":
                        _tg_send(token, chat_id, "\U0001f7e2 bouzecode bridge is active. Send me anything.")
                        continue
                    slash_cb = config.get("_handle_slash_callback")
                    if slash_cb:
                        def _slash_runner(_slash_text, _token, _chat_id):
                            _tg_thread_local.active = True
                            try:
                                cmd_type = slash_cb(_slash_text)
                            except Exception as e:
                                _tg_send(_token, _chat_id, f"\u26a0 Error: {e}"); return
                            finally:
                                _tg_thread_local.active = False
                            if cmd_type == "simple":
                                cmd_name = _slash_text.strip().split()[0]
                                _tg_send(_token, _chat_id, f"\u2705 {cmd_name} executed."); return
                            tg_state = config.get("_state")
                            if tg_state and tg_state.messages:
                                for m in reversed(tg_state.messages):
                                    if m.get("role") == "assistant":
                                        content = m.get("content", "")
                                        if isinstance(content, list):
                                            parts = [b["text"] if isinstance(b, dict) and b.get("type") == "text"
                                                      else b for b in content if isinstance(b, (str, dict))]
                                            content = "\n".join(str(p) for p in parts)
                                        if content:
                                            _tg_send(_token, _chat_id, content)
                                        break
                        threading.Thread(target=_slash_runner, args=(text, token, chat_id), daemon=True).start()
                    continue

                print(clr(f"\n  \U0001f4e9 Telegram: {text}", "cyan"))

                def _bg_runner(q_text, chat_token, chat_id):
                    _typing_stop = threading.Event()
                    _typing_t = threading.Thread(target=_tg_typing_loop, args=(chat_token, chat_id, _typing_stop), daemon=True)
                    _typing_t.start()
                    if run_query_cb:
                        try:
                            config["_telegram_incoming"] = True
                            run_query_cb(q_text)
                        except Exception as e:
                            _typing_stop.set()
                            _tg_send(chat_token, chat_id, f"\u26a0 Error: {e}"); return
                    _typing_stop.set()
                    state = config.get("_state")
                    if state and state.messages:
                        for m in reversed(state.messages):
                            if m.get("role") == "assistant":
                                content = m.get("content", "")
                                if isinstance(content, list):
                                    parts = [b["text"] if isinstance(b, dict) and b.get("type") == "text"
                                              else b for b in content if isinstance(b, (str, dict))]
                                    content = "\n".join(str(p) for p in parts)
                                if content:
                                    _tg_send(chat_token, chat_id, content)
                                break

                threading.Thread(target=_bg_runner, args=(text, token, chat_id), daemon=True).start()
        except Exception:
            _telegram_stop.wait(5)

    global _telegram_thread
    _telegram_thread = None


def cmd_telegram(args: str, _state, config) -> bool:
    """Telegram bot bridge -- receive and respond to messages via Telegram.

    Usage: /telegram <bot_token> <chat_id>   -- start the bridge
           /telegram stop                    -- stop the bridge
           /telegram status                  -- show current status
    """
    global _telegram_thread, _telegram_stop
    from config import save_config

    parts = args.strip().split()

    if parts and parts[0].lower() in ("stop", "off"):
        if _telegram_thread and _telegram_thread.is_alive():
            _telegram_stop.set()
            _telegram_thread.join(timeout=5)
            _telegram_thread = None
            ok("Telegram bridge stopped.")
        else:
            warn("Telegram bridge is not running.")
        return True

    if parts and parts[0].lower() == "status":
        running = _telegram_thread and _telegram_thread.is_alive()
        token = config.get("telegram_token", "")
        chat_id = config.get("telegram_chat_id", 0)
        if running:
            ok(f"Telegram bridge is running. Chat ID: {chat_id}")
        elif token:
            info("Configured but not running. Use /telegram to start.")
        else:
            info("Not configured. Use /telegram <bot_token> <chat_id>")
        return True

    if len(parts) >= 2:
        token = parts[0]
        try:
            chat_id = int(parts[1])
        except ValueError:
            err("Chat ID must be a number. Send a message to your bot, then check getUpdates.")
            return True
        config["telegram_token"] = token
        config["telegram_chat_id"] = chat_id
        save_config(config)
        ok("Telegram config saved.")
    else:
        token = config.get("telegram_token", "")
        chat_id = config.get("telegram_chat_id", 0)

    if not token or not chat_id:
        err("No config found. Usage: /telegram <bot_token> <chat_id>")
        return True

    if _telegram_thread and _telegram_thread.is_alive():
        warn("Telegram bridge is already running. Use /telegram stop first.")
        return True

    me = _tg_api(token, "getMe")
    if not me or not me.get("ok"):
        err("Invalid bot token. Check your token from @BotFather.")
        return True

    bot_name = me["result"].get("username", "unknown")
    ok(f"Connected to @{bot_name}. Starting bridge...")
    config["_state"] = _state

    _telegram_stop = threading.Event()
    _telegram_thread = threading.Thread(
        target=_tg_poll_loop, args=(token, chat_id, config), daemon=True,
    )
    _telegram_thread.start()
    ok(f"Telegram bridge active. Chat ID: {chat_id}")
    info("Send messages to your bot -- they'll be processed here.")
    info("Stop with /telegram stop or send /stop in Telegram.")
    return True
