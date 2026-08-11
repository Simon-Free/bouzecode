# i18n/en/

## Purpose
The English message dictionary — the default language, and the fallback for any key
another language leaves out. Each file calls `window.i18n.register("en", { ... })` with
a flat map of stable keys to words; the split is by area, not by page, so one key has
exactly one home.

## Usage
- `common.js` — chrome shared by every page: navigation labels, alert banners, time formats
- `state.js` — the state vocabulary: status pills, launch phases served by the server as keys, and the activity line of a live agent
- `pages.js` — the session page and the agent builder, templates and classic scripts alike

## Subfolders
| Folder | Description |
|--------|-------------|
| `conv/` | The Conversations page, split by area |
