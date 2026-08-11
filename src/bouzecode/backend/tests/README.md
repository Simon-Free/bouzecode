# backend/tests/

## Purpose
Covers the image path through the Read tool: the sentinel a binary read returns, and its conversion into an image content block on the Anthropic wire. Pure unit tests, no LLM and no network — a valid 1x1 PNG is built byte by byte in the test itself (no image library), written to a temp file, and the temp file is removed afterwards.

## Usage
- `test_read_image.py` — asserts `_read` on a `.png` returns `__BOUZE_IMAGE__:<media_type>:<base64>`, and that `messages_to_anthropic` turns such a tool result into a single `image` block with a base64 source
