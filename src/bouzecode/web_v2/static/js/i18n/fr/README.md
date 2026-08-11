# i18n/fr/

## Purpose
The French message dictionary, selected when the reader switches language. It mirrors
`en/` key for key — same files, same keys, French words — so a key present in one and
absent from the other is visible as a missing file rather than a silent gap. Each file
calls `window.i18n.register("fr", { ... })`.

## Usage
- `common.js` — chrome shared by every page: navigation labels, alert banners, time formats
- `state.js` — the state vocabulary: status pills, launch phases served by the server as keys, and the activity line of a live agent
- `pages.js` — the session page and the agent builder, templates and classic scripts alike

## Subfolders
| Folder | Description |
|--------|-------------|
| `conv/` | The Conversations page, split by area |
