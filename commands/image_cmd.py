# [desc] Captures a clipboard image, encodes it as base64 PNG, and queues it for a vision model prompt. [/desc]
"""Grab image from clipboard and send to vision model with optional prompt."""

from typing import Union

try:
    from ui.ansi import err, info
except ImportError:
    import sys
    C = {"cyan": "\033[36m", "red": "\033[31m", "reset": "\033[0m"}
    def info(msg):  print(C["cyan"] + msg + C["reset"])
    def err(msg):   print(C["red"] + f"Error: {msg}" + C["reset"], file=sys.stderr)


def cmd_image(args: str, state, config) -> Union[bool, tuple]:
    """Grab image from clipboard and send to vision model with optional prompt."""
    import sys as _sys
    try:
        from PIL import ImageGrab
        import io, base64
    except ImportError:
        err("Pillow is required for /image. Install with: pip install bouzecode[vision]")
        if _sys.platform == "linux":
            err("On Linux, clipboard support also requires xclip: sudo apt install xclip")
        return True

    img = ImageGrab.grabclipboard()
    if img is None:
        if _sys.platform == "linux":
            err("No image found in clipboard. On Linux, xclip is required (sudo apt install xclip). "
                "Copy an image with Flameshot, GNOME Screenshot, or: xclip -selection clipboard -t image/png -i file.png")
        elif _sys.platform == "darwin":
            err("No image found in clipboard. Copy an image first "
                "(Cmd+Ctrl+Shift+4 captures a screenshot region to clipboard).")
        else:
            err("No image found in clipboard. Copy an image first "
                "(Win+Shift+S captures a screenshot region to clipboard).")
        return True

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    size_kb = len(buf.getvalue()) / 1024

    info(f"📷 Clipboard image captured ({size_kb:.0f} KB, {img.size[0]}x{img.size[1]})")

    config["_pending_image"] = b64

    prompt = args.strip() if args.strip() else "What do you see in this image? Describe it in detail."
    return ("__image__", prompt)
