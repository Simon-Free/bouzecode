# [desc] Text-to-speech generation with Gemini, ElevenLabs, and Edge TTS backends for a video pipeline. [/desc]
"""
Text-to-speech backends for the video pipeline.

Priority:
  1. Gemini TTS  — if GEMINI_API_KEY is set (good quality, free tier)
  2. ElevenLabs  — if ELEVENLABS_API_KEY is set (premium)
  3. Edge TTS    — always free, no API key needed (fallback)
"""

import os
import re
import wave
import struct
import subprocess
import urllib.request
import json


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_chunks(text: str, max_words: int = 350) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for sent in sentences:
        wc = len(sent.split())
        if count + wc > max_words and current:
            chunks.append(' '.join(current))
            current, count = [], 0
        current.append(sent)
        count += wc
    if current:
        chunks.append(' '.join(current))
    return chunks


def _crossfade_pcm(pcm_a: bytes, pcm_b: bytes, fade_ms: int = 80) -> bytes:
    """Crossfade two raw 16-bit LE mono PCM streams."""
    sample_rate = 24000
    fade_samples = int(sample_rate * fade_ms / 1000)
    min_bytes = min(len(pcm_a), len(pcm_b), fade_samples * 2)
    if min_bytes < 2:
        return pcm_a + pcm_b
    fade_samples = min_bytes // 2
    tail = struct.unpack(f'<{fade_samples}h', pcm_a[-min_bytes:])
    head = struct.unpack(f'<{fade_samples}h', pcm_b[:min_bytes])
    mixed = []
    for i in range(fade_samples):
        t = i / fade_samples
        s = int(tail[i] * (1.0 - t) + head[i] * t)
        mixed.append(max(-32768, min(32767, s)))
    return pcm_a[:-min_bytes] + struct.pack(f'<{fade_samples}h', *mixed) + pcm_b[min_bytes:]


# ── Gemini TTS ────────────────────────────────────────────────────────────────

_GEMINI_TTS_MODEL = "gemini-2.5-pro-preview-tts"
_GEMINI_TTS_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_TTS_MODEL}:generateContent"


def _gemini_chunk_to_pcm(text: str, api_key: str, voice: str = "Charon") -> bytes | None:
    import base64
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    try:
        req = urllib.request.Request(
            f"{_GEMINI_TTS_URL}?key={api_key}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        return base64.b64decode(b64)
    except Exception as exc:
        print(f"    Gemini TTS chunk error: {exc}")
        return None


def generate_audio_gemini(text: str, output_path: str, voice: str = "Charon") -> bool:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return False
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False

    chunks = _split_chunks(text)
    print(f"  Gemini TTS: {len(chunks)} chunk(s), voice={voice}")
    all_pcm = b""
    for i, chunk in enumerate(chunks, 1):
        print(f"  chunk {i}/{len(chunks)}...")
        pcm = _gemini_chunk_to_pcm(chunk, api_key, voice)
        if pcm:
            all_pcm = _crossfade_pcm(all_pcm, pcm) if all_pcm else pcm

    if not all_pcm:
        return False

    wav_path = output_path.replace('.mp3', '_raw.wav')
    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(all_pcm)

    result = subprocess.run(
        [ffmpeg, "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "2", output_path],
        capture_output=True, timeout=60
    )
    try:
        os.remove(wav_path)
    except OSError:
        pass
    return result.returncode == 0 and os.path.exists(output_path)


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

def generate_audio_elevenlabs(text: str, output_path: str) -> bool:
    api_key  = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", os.getenv("ELEVEN_VOICE_ID", "qEWvRpD5bptlI1hEomR7"))
    if not api_key:
        return False

    url     = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True},
    }
    headers = {"Content-Type": "application/json", "xi-api-key": api_key, "Accept": "audio/mpeg"}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=300) as resp:
            audio_data = resp.read()
        if len(audio_data) > 1000:
            with open(output_path, 'wb') as f:
                f.write(audio_data)
            print(f"  ElevenLabs TTS: {len(audio_data) // 1024} KB")
            return True
        return False
    except Exception as exc:
        print(f"  ElevenLabs error: {exc}")
        return False


# ── Edge TTS (free) ───────────────────────────────────────────────────────────

def generate_audio_edge(text: str, output_path: str, voice: str = "en-US-GuyNeural") -> bool:
    try:
        import edge_tts
        import asyncio

        async def _run():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)

        asyncio.run(_run())
        print(f"  Edge TTS: done, voice={voice}")
        return True
    except ImportError:
        print("  Edge TTS not installed. Run: pip install edge-tts")
        return False
    except Exception as exc:
        print(f"  Edge TTS error: {exc}")
        return False


# ── Unified entry point ───────────────────────────────────────────────────────

def generate_audio(text: str, output_path: str,
                   engine: str = "auto",
                   voice: str = "Charon",
                   edge_voice: str = "en-US-GuyNeural") -> bool:
    """
    Generate audio for story_text and save to output_path.

    engine: "auto" | "gemini" | "elevenlabs" | "edge"
    - "auto": try gemini → elevenlabs → edge in order
    """
    clean_text = re.sub(r'[\[\]*"]', '', text)

    if engine in ("gemini", "auto"):
        if generate_audio_gemini(clean_text, output_path, voice=voice):
            return True
        if engine == "gemini":
            return False

    if engine in ("elevenlabs", "auto"):
        if generate_audio_elevenlabs(clean_text, output_path):
            return True
        if engine == "elevenlabs":
            return False

    # Edge TTS is always the final fallback
    return generate_audio_edge(clean_text, output_path, voice=edge_voice)


# ── Utility ───────────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str | None:
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except ImportError:
        return None
