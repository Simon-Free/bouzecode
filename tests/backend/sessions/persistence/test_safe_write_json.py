# [desc] Tests _safe_write_json retry logic on PermissionError, max-retry failure, and first-try success
# <tool_use name="FinalAnswer" id="x1"><param name="answer">Tests _safe_write_json retry logic on PermissionError, max-retry failure, and first-try success</param></tool_use> [/desc]
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bouzecode.backend.commands.session import _safe_write_json


def test_safe_write_json_retries_on_permission_error(tmp_path):
    target = tmp_path / "test.json"
    data = {"key": "value"}

    call_count = {"n": 0}
    original_replace = os.replace

    def flaky_replace(src, dst):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise PermissionError("[WinError 5] Accès refusé")
        return original_replace(src, dst)

    with patch("bouzecode.backend.commands.session.session.os.replace", side_effect=flaky_replace):
        _safe_write_json(target, data)

    assert target.exists()
    assert json.loads(target.read_text()) == data
    assert call_count["n"] == 3


def test_safe_write_json_raises_after_max_retries(tmp_path):
    target = tmp_path / "test.json"
    data = {"key": "value"}

    def always_fail(src, dst):
        raise PermissionError("[WinError 5] Accès refusé")

    with patch("bouzecode.backend.commands.session.session.os.replace", side_effect=always_fail):
        with pytest.raises(PermissionError):
            _safe_write_json(target, data)

    # tmp file should be cleaned up
    assert not (tmp_path / "test.tmp").exists()


def test_safe_write_json_succeeds_first_try(tmp_path):
    target = tmp_path / "test.json"
    data = {"hello": "world"}
    _safe_write_json(target, data)
    assert json.loads(target.read_text()) == data
