# lib/

## Purpose
Browser helpers shared by several pages, with no page of their own.

## Usage
- `monaco_loader.js` — `loadMonaco()` lazily loads the code editor from the local
  vendored copy under `static/vendor/`, never from a CDN, and resolves to `null` when
  that copy is absent so the caller keeps its plain `<pre>` fallback;
  `monacoLanguage(path)` maps a file extension to an editor language id via
  `MONACO_LANGS`, defaulting to plain text.
