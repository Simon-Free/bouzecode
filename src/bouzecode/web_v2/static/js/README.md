# static/js/

## Purpose
Browser scripts for the web UI, one file per page or per page tab. These are classic
scripts loaded by the Jinja templates (no bundler, no CDN); the Conversations page is
the exception and lives as ES modules under `conversations/`.

## Usage
- `session.js` — the session page: incremental polling of rendered HTML blocks, answering a question, killing an agent, the diffs tab
- `turns.js` — the Turns tab: table of LLM calls and the payload drill-down annotated by cache state
- `costs.js` — the costs tab: fetches the session cost endpoint and renders the table
- `conversations.js` — the Conversations page shell: manager sidebar built from the agent tree, plus the inner tabs, each polling the same blocks endpoint as `session.js`
- `conv_relaunch.js` — the Relaunch button of a conversation panel, the only affordance that restarts a ticket whose agent is dead
- `time_format.js` — the single time-formatting helper of the Conversations page; every displayed time goes through it
- `agent_builder.js` — the agent-builder page shell: tabs, the tools/skills/hooks catalogue, the collapsed capability summary
- `agent_builder_form.js` — loading an existing profile into the form, collecting the input, saving or deleting a global profile
- `agent_builder_catalog.js` — the Catalogue tab: installed versus remotely available agents, installing one, refreshing the remote catalogue
- `agent_builder_plugins.js` — the Plugins tab: installed plugins, installing from a git source, updating one
- `agent_builder_preview.js` — the computed full prompt: base prompt, preloaded skills and the custom part, as the agent actually receives it

## Subfolders
| Folder | Description |
|--------|-------------|
| `conversations/` | The Conversations page as ES modules: sidebar, panel, composer, recap |
| `i18n/` | Bilingual message dictionaries and the runtime that swaps them without a reload |
| `lib/` | Shared browser helpers with no page of their own |
