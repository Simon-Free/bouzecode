# video/

## Purpose
A narrated-video factory: a topic becomes a story script, then voice-over, subtitles and images, then a finished MP4. Every stage has several backends tried in order, ending on one that needs no API key.

## Usage
- `pipeline.py` — `create_video_story()` orchestrates story, TTS, subtitles, images and assembly into an output directory; `_extract_video_frames()` and `_safe_filename()` support it
- `niches.py` — `CONTENT_NICHES`, `select_niche()`, `parse_timestamp()` — per-niche tone, narrative style and hooks used to steer story generation
- `story.py` — `generate_story()` — prompts the active model for a script with image prompts and SFX cues, with `_retry_simple()` / `_retry_freeform()` fallbacks and `_parse_story_response()`
- `tts.py` — `generate_audio()` dispatches to `generate_audio_gemini()`, `generate_audio_elevenlabs()` or `generate_audio_edge()`; long text is split by `_split_chunks()` and rejoined with `_crossfade_pcm()`
- `subtitles.py` — `generate_subtitles()` (faster-whisper) and `text_to_srt()` (proportional timing from the audio duration), with `_split_subtitle_chunks()`
- `images.py` — `generate_images()` dispatches to `generate_images_gemini_web()`, `generate_images_web_search()` (stock-photo lookup) or `generate_images_placeholder()` (gradient slides)
- `source.py` — `scan_source_dir()`, `summarise_source_for_story()`, `select_relevant_images()`, `copy_source_images()`, `extract_audio_from_video()` — reuse of user-supplied media instead of generating it
- `assembly.py` — `create_video()` builds zoompan clips per image, concatenates them and attaches audio; `mix_sfx()` layers sound cues and `_burn_subtitles_pil()` renders subtitles as images over the video; `QUALITY_PRESETS` holds the encoding profiles
- `__init__.py` exposes `check_video_deps()`
