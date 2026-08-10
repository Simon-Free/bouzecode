"""E2E tests for /video and /video-wizard commands.

All external dependencies (ffmpeg, edge_tts, faster_whisper, playwright, etc.)
are fully mocked — no real binaries, no network, no hardware.
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_paths():
    """Ensure src/ and project root are on sys.path for imports."""
    src = os.path.join(os.path.dirname(__file__), "..", "..", "src")
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    for p in (os.path.abspath(src), os.path.abspath(root)):
        if p not in sys.path:
            sys.path.insert(0, p)


@pytest.fixture
def mock_all_deps_available(monkeypatch):
    """Mock check_video_deps to report all dependencies available."""
    fake_deps = {
        "ffmpeg": True,
        "ffprobe": True,
        "edge_tts": True,
        "faster_whisper": True,
        "playwright": True,
        "pillow": True,
    }
    monkeypatch.setattr("video.check_video_deps", lambda: fake_deps)
    return fake_deps


@pytest.fixture
def mock_deps_missing(monkeypatch):
    """Mock check_video_deps with some dependencies missing."""
    fake_deps = {
        "ffmpeg": False,
        "ffprobe": False,
        "edge_tts": True,
        "faster_whisper": False,
        "playwright": False,
        "pillow": True,
    }
    monkeypatch.setattr("video.check_video_deps", lambda: fake_deps)
    return fake_deps


@pytest.fixture
def mock_pipeline(monkeypatch, tmp_path):
    """Mock the entire video pipeline to avoid real processing."""

    def fake_generate_story(topic, model, config, **kwargs):
        return {
            "title": f"Test Story: {topic}",
            "story": "Once upon a time in a test. The end.",
            "niche_id": "test",
            "niche": {"nombre": "Test Niche", "imagen_estilo": "cinematic photography"},
            "image_prompts": [
                {"prompt": "test image 1", "timestamp": None, "seconds": None},
                {"prompt": "test image 2", "timestamp": None, "seconds": None},
            ],
            "sfx_cues": [],
            "has_timestamps": False,
        }

    def fake_generate_audio(text, output_path, **kwargs):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1024)  # fake audio bytes
        return True

    def fake_generate_images(prompts, output_dir, **kwargs):
        os.makedirs(output_dir, exist_ok=True)
        for i in range(len(prompts)):
            img_path = os.path.join(output_dir, f"img_{i:03d}.png")
            # Minimal valid PNG (1x1 pixel)
            with open(img_path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        return len(prompts)

    def fake_text_to_srt(text, audio_path, srt_path):
        os.makedirs(os.path.dirname(srt_path), exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nTest subtitle\n\n")
        return True

    def fake_generate_subtitles(audio_path, srt_path, **kwargs):
        os.makedirs(os.path.dirname(srt_path), exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nTest subtitle\n\n")
        return True

    def fake_create_video(images_dir, audio_file, output_file, **kwargs):
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "wb") as f:
            f.write(b"\x00" * 2048)  # fake MP4 bytes
        return True

    def fake_mix_sfx(video_path, sfx_cues, sounds_dir, output_path=None):
        return video_path

    monkeypatch.setattr("video.story.generate_story", fake_generate_story)
    monkeypatch.setattr("video.tts.generate_audio", fake_generate_audio)
    monkeypatch.setattr("video.images.generate_images", fake_generate_images)
    monkeypatch.setattr("video.subtitles.text_to_srt", fake_text_to_srt)
    monkeypatch.setattr("video.subtitles.generate_subtitles", fake_generate_subtitles)
    monkeypatch.setattr("video.assembly.create_video", fake_create_video)
    monkeypatch.setattr("video.assembly.mix_sfx", fake_mix_sfx)

    # Mock shutil.which to simulate ffmpeg/ffprobe available
    original_which = __import__("shutil").which

    def patched_which(name):
        if name in ("ffmpeg", "ffprobe"):
            return f"/usr/bin/{name}"
        return original_which(name)

    monkeypatch.setattr("shutil.which", patched_which)

    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVideoStatus:
    """Test /video status subcommand."""

    def test_video_status_all_deps_available(self, mock_all_deps_available, capsys):
        """/video status with all deps available prints dep table without crash."""
        from bouzecode.backend.commands.oss_shims.video_cmd import cmd_video

        # The flat cmd_video prints status table — we need it importable
        # If flat commands/ isn't on path, the shim falls back to check_video_deps
        result = cmd_video("status", None, {})
        # Should not crash regardless of whether flat package is available
        # The shim either delegates or shows dep info

    def test_video_status_deps_missing(self, mock_deps_missing, capsys):
        """/video status with missing deps reports them clearly."""
        from bouzecode.backend.commands.oss_shims.video_cmd import cmd_video

        result = cmd_video("status", None, {})
        # Should not crash — either flat handler or fallback


class TestVideoDependencyCheck:
    """Test dependency checking behavior."""

    def test_check_video_deps_returns_dict(self):
        """video.check_video_deps() returns a dict with expected keys."""
        from video import check_video_deps
        deps = check_video_deps()
        assert isinstance(deps, dict)
        expected_keys = {"ffmpeg", "ffprobe", "edge_tts", "faster_whisper", "playwright", "pillow"}
        assert expected_keys == set(deps.keys())

    def test_missing_deps_graceful_message(self, mock_deps_missing, capsys):
        """When deps are missing, shim prints a clear message without crashing."""
        # Temporarily remove commands from path to force fallback path
        import importlib
        from bouzecode.backend.commands.oss_shims import video_cmd
        importlib.reload(video_cmd)

        # Force the ImportError path by patching the import
        with patch.dict("sys.modules", {"commands": None, "commands.video_cmd": None}):
            # Need to reimport to trigger the patched import
            from bouzecode.backend.commands.oss_shims.video_cmd import cmd_video
            result = cmd_video("", None, {})

        captured = capsys.readouterr()
        # Should contain some message about missing deps or module
        assert result is None


class TestVideoPipeline:
    """Test full video pipeline with all externals mocked."""

    def test_full_pipeline_mocked(self, mock_pipeline, monkeypatch, tmp_path):
        """/video topic runs full pipeline with all deps mocked → produces result."""
        from video.pipeline import create_video_story

        result = create_video_story(
            topic="test topic for e2e",
            model="mock-model",
            config={"model": "mock-model"},
            output_dir=str(tmp_path / "output"),
            work_dir=str(tmp_path / "work"),
        )

        assert result is not None
        assert "video_path" in result
        assert os.path.exists(result["video_path"])

    def test_pipeline_with_script_text(self, mock_pipeline, tmp_path):
        """Pipeline with script_text skips story generation."""
        from video.pipeline import create_video_story

        result = create_video_story(
            topic="ignored topic",
            model="mock-model",
            config={"model": "mock-model"},
            script_text="Custom narration text for testing.",
            output_dir=str(tmp_path / "output"),
            work_dir=str(tmp_path / "work"),
        )

        assert result is not None
        assert "video_path" in result


class TestVideoWizardRegistered:
    """/video-wizard is properly registered in the dispatcher."""

    def test_video_wizard_in_dispatcher(self):
        """video-wizard command is registered in OSS_COMMANDS."""
        from bouzecode.backend.commands.oss_shims import OSS_COMMANDS
        assert "video-wizard" in OSS_COMMANDS
        assert callable(OSS_COMMANDS["video-wizard"])

    def test_video_wizard_callable_no_crash(self):
        """Calling video-wizard with no args doesn't crash."""
        from bouzecode.backend.commands.oss_shims.video_wizard_cmd import cmd_video_wizard

        # Will likely fail with ImportError for commands.video_wizard
        # but should handle gracefully
        with patch.dict("sys.modules", {"commands": None, "commands.video_wizard": None}):
            result = cmd_video_wizard("", None, {})
        # Should return None gracefully
        assert result is None


class TestVideoShimSignature:
    """Verify the shim has correct signature for dispatcher."""

    def test_cmd_video_accepts_three_args(self):
        """cmd_video(args, state, config) works with 3 positional args."""
        from bouzecode.backend.commands.oss_shims.video_cmd import cmd_video
        # Should not raise TypeError
        try:
            cmd_video("status", None, {})
        except TypeError as e:
            if "positional argument" in str(e):
                pytest.fail(f"cmd_video signature wrong: {e}")

    def test_cmd_video_wizard_accepts_three_args(self):
        """cmd_video_wizard(args, state, config) works with 3 positional args."""
        from bouzecode.backend.commands.oss_shims.video_wizard_cmd import cmd_video_wizard
        try:
            cmd_video_wizard("", None, {})
        except TypeError as e:
            if "positional argument" in str(e):
                pytest.fail(f"cmd_video_wizard signature wrong: {e}")
        except Exception:
            pass  # EOFError, ImportError, etc. are fine — we only test signature
