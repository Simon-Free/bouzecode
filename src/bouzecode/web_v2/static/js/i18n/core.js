// [desc] Noyau i18n : une table de messages par langue, un `t()`, et l'application aux
// attributs `data-i18n` du DOM. Anglais par défaut, français au choix. [/desc]
//
// POURQUOI CE FICHIER EST UN SCRIPT CLASSIQUE. Trois des quatre gabarits chargent leur
// JavaScript en `<script src>` non-module (agent_builder, session) : un module ES ne leur
// serait pas visible, et les scripts classiques s'exécutent AVANT les modules différés.
// Le noyau s'installe donc sur `window.i18n`, visible de tout le monde ; `index.js` en
// donne une façade ES pour les modules (et pour vitest).
//
// IDEMPOTENT. Le même fichier est chargé deux fois sur la page Conversations — une fois
// par la balise `<script>` du gabarit, une fois par le graphe d'imports ES. Sans la garde
// ci-dessous, la seconde exécution repartirait d'une table vide et effacerait les
// dictionnaires déjà enregistrés.
(function (global) {
  "use strict";
  if (global.i18n) return;

  var STORAGE_KEY = "bouzecode.lang";
  var DEFAULT_LANG = "en";
  var SUPPORTED = ["en", "fr"];
  var CHANGE_EVENT = "i18n:change";

  var messages = { en: {}, fr: {} };
  var current = null;

  function isSupported(lang) { return SUPPORTED.indexOf(lang) !== -1; }

  // Le choix survit à la visite. `localStorage` peut lever (navigation privée, iframe
  // cloisonnée) : on retombe alors sur la langue par défaut plutôt que de casser la page.
  function readStored() {
    try {
      var stored = global.localStorage && global.localStorage.getItem(STORAGE_KEY);
      return isSupported(stored) ? stored : DEFAULT_LANG;
    } catch (e) {
      return DEFAULT_LANG;
    }
  }

  function writeStored(lang) {
    try {
      if (global.localStorage) global.localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) { /* stockage refusé : la langue vaut pour cette page seulement */ }
  }

  function getLang() {
    if (current === null) current = readStored();
    return current;
  }

  // Une clé absente ne doit JAMAIS se traduire par du vide : un libellé disparu passerait
  // inaperçu en développement et sortirait en production. On rend la clé encadrée, donc
  // visible à l'œil nu, et on la signale une fois en console.
  var warned = {};
  function missing(key) {
    if (!warned[key]) {
      warned[key] = true;
      if (global.console && global.console.warn) global.console.warn("[i18n] clé absente : " + key);
    }
    return "⟦" + key + "⟧";
  }

  // `{name}` dans un message est remplacé par `params.name`. Un paramètre absent laisse le
  // marqueur en place : mieux vaut voir `{count}` que d'annoncer « undefined agents ».
  function interpolate(text, params) {
    if (!params) return text;
    return text.replace(/\{(\w+)\}/g, function (whole, name) {
      return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : whole;
    });
  }

  function t(key, params) {
    var value = messages[getLang()][key];
    // Repli sur l'anglais : une clé traduite en anglais mais pas encore en français doit
    // rendre l'anglais, pas un marqueur d'erreur — la page reste lisible.
    if (value === undefined) value = messages[DEFAULT_LANG][key];
    if (value === undefined) return missing(key);
    return interpolate(value, params);
  }

  // Le serveur sert des mots de code (phase, outil, typologie) qui n'ont pas tous une
  // traduction : `has` laisse l'appelant retomber sur le libellé du serveur plutôt que
  // d'afficher un marqueur de clé absente pour une donnée qui n'en est pas une.
  function has(key) { return messages[DEFAULT_LANG][key] !== undefined; }

  function register(lang, dict) {
    if (!messages[lang]) messages[lang] = {};
    for (var key in dict) {
      if (Object.prototype.hasOwnProperty.call(dict, key)) messages[lang][key] = dict[key];
    }
  }

  function setLang(lang) {
    if (!isSupported(lang) || lang === getLang()) return;
    current = lang;
    writeStored(lang);
    if (global.document) {
      global.document.documentElement.lang = lang;
      applyDom(global.document);
      global.document.dispatchEvent(new global.CustomEvent(CHANGE_EVENT, { detail: { lang: lang } }));
    }
  }

  // Paramètres portés par le DOM : `data-i18n-arg-count="3"` alimente `{count}`. C'est ce
  // qui permet au serveur de rendre un fragment traduisible sans connaître la langue —
  // il émet la clé et ses arguments, le client compose la phrase.
  function domParams(el) {
    var params = null;
    var attrs = el.attributes;
    for (var i = 0; i < attrs.length; i++) {
      var name = attrs[i].name;
      if (name.indexOf("data-i18n-arg-") !== 0) continue;
      if (!params) params = {};
      params[name.slice("data-i18n-arg-".length)] = attrs[i].value;
    }
    return params;
  }

  var ATTR_KEYS = ["placeholder", "title", "aria-label", "value"];

  function applyOne(el) {
    var params = domParams(el);
    var textKey = el.getAttribute("data-i18n");
    if (textKey) el.textContent = t(textKey, params);
    for (var i = 0; i < ATTR_KEYS.length; i++) {
      var attr = ATTR_KEYS[i];
      var key = el.getAttribute("data-i18n-" + attr);
      if (key) el.setAttribute(attr, t(key, params));
    }
  }

  // Retraduit `root` et tous ses descendants annotés. Idempotent : les clés restent dans le
  // DOM, donc une bascule de langue suffit à tout réécrire — y compris les fragments HTML
  // rendus par le serveur et insérés en cours de route.
  function applyDom(root) {
    if (!root || !root.querySelectorAll) return;
    var selector = "[data-i18n]";
    for (var i = 0; i < ATTR_KEYS.length; i++) selector += ",[data-i18n-" + ATTR_KEYS[i] + "]";
    if (root.nodeType === 1 && root.matches && root.matches(selector)) applyOne(root);
    var found = root.querySelectorAll(selector);
    for (var j = 0; j < found.length; j++) applyOne(found[j]);
  }

  function onChange(fn) {
    if (global.document) global.document.addEventListener(CHANGE_EVENT, fn);
  }

  global.i18n = {
    DEFAULT_LANG: DEFAULT_LANG,
    SUPPORTED: SUPPORTED,
    STORAGE_KEY: STORAGE_KEY,
    CHANGE_EVENT: CHANGE_EVENT,
    messages: messages,
    getLang: getLang,
    setLang: setLang,
    register: register,
    t: t,
    has: has,
    applyDom: applyDom,
    onChange: onChange,
  };

  if (global.document) {
    global.document.documentElement.lang = getLang();
    global.document.addEventListener("DOMContentLoaded", function () { applyDom(global.document); });
  }
})(typeof window !== "undefined" ? window : globalThis);
