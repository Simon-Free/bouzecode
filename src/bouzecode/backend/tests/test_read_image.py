import base64
import struct
import tempfile
import zlib
from pathlib import Path

from bouzecode.backend.tools.ops.file_ops import _read
from bouzecode.backend.agent.providers.conversion import messages_to_anthropic


def _make_png_1x1() -> bytes:
    """Build a minimal valid 1x1 PNG (no external deps)."""
    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\x00\x00"  # one scanline: filter 0 + RGB pixel
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def test__read_image_returns_sentinel():
    png = _make_png_1x1()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png)
        path = f.name
    try:
        out = _read(path)
        assert out.startswith("__BOUZE_IMAGE__:image/png:"), out[:60]
        _, media_type, b64 = out.split(":", 2)
        assert media_type == "image/png"
        assert base64.b64decode(b64) == png
    finally:
        Path(path).unlink(missing_ok=True)


def test_messages_to_anthropic_builds_image_block():
    b64 = base64.b64encode(_make_png_1x1()).decode()
    sentinel = f"__BOUZE_IMAGE__:image/png:{b64}"
    messages = [
        {"role": "user", "content": "look"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"name": "Read", "id": "t1", "inputs": {"file_path": "x.png"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": sentinel},
    ]
    out = messages_to_anthropic(messages, cache_last=False)
    last = out[-1]
    assert last["role"] == "user"
    assert isinstance(last["content"], list)
    image_blocks = [b for b in last["content"] if b.get("type") == "image"]
    assert len(image_blocks) == 1
    src = image_blocks[0]["source"]
    assert src == {"type": "base64", "media_type": "image/png", "data": b64}
