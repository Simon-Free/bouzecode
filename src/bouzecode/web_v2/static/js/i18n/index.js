// Façade ES du noyau i18n, pour les modules de `conversations/` et pour vitest.
//
// Les fichiers importés ci-dessous sont des scripts CLASSIQUES : ils ne s'exportent pas,
// ils s'installent sur `window` (cf. core.js). Les importer ici a donc pour seul effet de
// garantir que le noyau et les dictionnaires sont chargés, quel que soit le point d'entrée
// — la page (qui les charge en `<script src>`) ou un test unitaire (qui n'a pas de gabarit).
import "./core.js";
import "./en/common.js";
import "./en/state.js";
import "./en/pages.js";
import "./en/conv/sidebar.js";
import "./en/conv/panel.js";
import "./en/conv/composer.js";
import "./fr/common.js";
import "./fr/state.js";
import "./fr/pages.js";
import "./fr/conv/sidebar.js";
import "./fr/conv/panel.js";
import "./fr/conv/composer.js";

const core = (typeof window !== "undefined" ? window : globalThis).i18n;

export function t(key, params) { return core.t(key, params); }
export function has(key) { return core.has(key); }
export function getLang() { return core.getLang(); }
export function setLang(lang) { return core.setLang(lang); }
export function applyDom(root) { return core.applyDom(root); }
export function onLangChange(fn) { return core.onChange(fn); }
