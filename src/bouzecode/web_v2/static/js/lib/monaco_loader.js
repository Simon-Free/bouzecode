// [desc] Chargement lazy de Monaco depuis jsdelivr (comme la v1) + détection de langage. Fallback: null. [/desc]
"use strict";

const MONACO_CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min";
const MONACO_LANGS = {
  py: "python", js: "javascript", ts: "typescript", json: "json", md: "markdown",
  html: "html", htm: "html", css: "css", ps1: "powershell", psm1: "powershell",
  sh: "shell", bash: "shell", yml: "yaml", yaml: "yaml", toml: "ini", ini: "ini",
  sql: "sql", xml: "xml", csv: "plaintext", txt: "plaintext",
};

let monacoPromise = null;

function monacoLanguage(path) {
  const ext = (path.split(".").pop() || "").toLowerCase();
  return MONACO_LANGS[ext] || "plaintext";
}

// Résout monaco, ou null si le CDN est injoignable (offline) → l'appelant garde son fallback.
function loadMonaco() {
  if (monacoPromise) return monacoPromise;
  monacoPromise = new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = `${MONACO_CDN}/vs/loader.js`;
    script.onerror = () => resolve(null);
    script.onload = () => {
      window.require.config({ paths: { vs: `${MONACO_CDN}/vs` } });
      window.require(["vs/editor/editor.main"], () => resolve(window.monaco), () => resolve(null));
    };
    document.head.appendChild(script);
    setTimeout(() => resolve(window.monaco || null), 8000);
  });
  return monacoPromise;
}
