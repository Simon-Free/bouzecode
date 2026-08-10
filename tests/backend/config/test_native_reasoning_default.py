from bouzecode.backend.core.config import load_config


def test_native_reasoning_off_by_default():
    """The API's native reasoning channel is opt-in only: by default the model
    reasons via manual <thinking> text (routed into thinking_parts by loop_turn),
    never via the provider's native reasoning payload."""
    cfg = load_config()
    assert cfg["native_reasoning"] is False
