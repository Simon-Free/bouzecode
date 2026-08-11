# i18n

## Purpose
Bilingual UI (English by default, French on demand). One dictionary per language, no page
reload on switch, choice persisted in `localStorage` under `bouzecode.lang`.

The server stays monolingual: it emits **stable keys** (`status.phase`, `node.activity`) and
the client picks the words. Templates ship the English text inline, so the default language
never repaints.

## Usage
Classic scripts (`session.js`, `agent_builder*.js`, inline template scripts):

```js
window.i18n.t("state.running");
window.i18n.t("activity.tool_live_since", { tool: "Bash", age: "12 s" });
window.i18n.onChange(() => redraw());
```

ES modules (`conversations/**`) and vitest:

```js
import { t, applyDom, onLangChange } from "../i18n/index.js";
```

Static markup carries the key and its English text; `applyDom(root)` rewrites it. Works on
server-rendered HTML inserted at runtime too — the keys stay in the DOM.

```html
<button data-i18n="conv.archive" data-i18n-title="conv.archive_tip">Archive</button>
<span data-i18n="panel.tool_result" data-i18n-arg-name="Bash">Bash result</span>
```

Translatable attributes: `placeholder`, `title`, `aria-label`, `value` (`data-i18n-<attr>`).
Arguments: `data-i18n-arg-<name>` feeds `{name}` in the message.

A missing key renders `⟦the.key⟧` and warns once in the console — never silently empty.

## Subfolders
| Folder | Description |
|--------|-------------|
| `en/` | English messages (the default language, also the fallback for any key missing elsewhere) |
| `fr/` | French messages — verbatim the labels the UI shipped before it was bilingual |
| `en/conv/`, `fr/conv/` | Conversations page, split by area (sidebar, panel, composer) |
