# voice/

## Purpose
Voice input: capture microphone audio until silence, then transcribe it to text. Recording and speech-to-text each pick the first available backend, so the package degrades gracefully when optional dependencies are absent.

## Usage
- `recorder.py` — `record_until_silence()`, `check_recording_availability()`, `list_input_devices()` — RMS-based silence detection over `sounddevice`, `arecord` or `sox`; all backends emit 16 kHz mono int16 PCM
- `stt.py` — `transcribe()`, `transcribe_audio_file()`, `check_stt_availability()`, `get_stt_backend_name()` — faster-whisper, openai-whisper, or the hosted Whisper API; also `_pcm_to_wav()` / `_audio_file_to_pcm()` conversion helpers
- `keyterms.py` — `get_voice_keyterms()`, `split_identifier()`, `GLOBAL_KEYTERMS`, `MAX_KEYTERMS` — coding vocabulary passed as Whisper's `initial_prompt`, enriched with identifiers from the git branch and recent project files
- `__init__.py` re-exports the public surface and adds `check_voice_deps()` and `voice_input()` (record plus transcribe in one call)
