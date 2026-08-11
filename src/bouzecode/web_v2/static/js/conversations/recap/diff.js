// Rendu des diffs du récap : side-by-side maison (100% offline, aucun CDN/Monaco →
// immunisé aux proxys restrictifs) + repli <pre> unifié pour les sessions
// historiques sans snapshots. Module PUR : aucune dépendance à l'état de la page.

import { node } from "../dom.js";
import { t } from "../../i18n/index.js";

function diffStats(patch) {
  let added = 0, removed = 0;
  for (const line of patch.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) added++;
    else if (line.startsWith("-") && !line.startsWith("---")) removed++;
  }
  return { added, removed };
}

// Fallback historique : rend le patch unifié en <pre> coloré à la main dans `container`.
// Utilisé quand Monaco ne charge pas (vendor manquant, offline) → jamais de récap sans diffs.
const PRE_DIFF_MAX_LINES = 400; // au-delà : tronque + indicateur (gros diffs)

// ── Rendu side-by-side maison (100% offline, aucun CDN/Monaco). Le récap reçoit
// `original`/`modified` (contenus complets) : on aligne les lignes par un LCS
// simple, on rend deux colonnes (ancien | nouveau) avec surlignage add/del et une
// coloration syntaxique légère (regex) selon le langage du fichier. ────────────

// Mots-clés par langage (grossier mais suffisant pour teinter le code du diff).
const SXS_KEYWORDS = {
  python: new Set(["def","class","return","if","elif","else","for","while","import","from","as","with","try","except","finally","raise","yield","lambda","pass","break","continue","and","or","not","in","is","None","True","False","async","await","global","nonlocal","assert","del"]),
  javascript: new Set(["function","return","if","else","for","while","const","let","var","import","from","export","default","class","extends","new","try","catch","finally","throw","await","async","yield","typeof","instanceof","in","of","null","undefined","true","false","this","super","break","continue","switch","case","do","delete","void"]),
  typescript: new Set(["function","return","if","else","for","while","const","let","var","import","from","export","default","class","extends","implements","interface","type","enum","new","try","catch","finally","throw","await","async","yield","typeof","instanceof","in","of","null","undefined","true","false","this","super","break","continue","switch","case","do","public","private","protected","readonly","as","namespace"]),
};
const SXS_LANG = {
  py: "python", js: "javascript", jsx: "javascript", mjs: "javascript",
  ts: "typescript", tsx: "typescript",
};
function langOf(path) {
  const ext = (String(path || "").split(".").pop() || "").toLowerCase();
  return SXS_LANG[ext] || "plaintext";
}

// Découpe UNE ligne en tokens {cls,text} : commentaires, chaînes, nombres,
// mots-clés. Tout le reste est du texte brut (cls=""). Ordre des règles = priorité.
function tokenizeLine(line, lang) {
  const kw = SXS_KEYWORDS[lang];
  const tokens = [];
  const commentStart = lang === "python" ? "#" : "//";
  let i = 0;
  const n = line.length;
  while (i < n) {
    const ch = line[i];
    // Commentaire jusqu'à la fin de ligne.
    if (line.startsWith(commentStart, i)) {
      tokens.push({ cls: "tok-com", text: line.slice(i) });
      break;
    }
    // Chaîne " ' ou ` (sans gestion multi-ligne : suffisant par ligne).
    if (ch === '"' || ch === "'" || ch === "`") {
      let j = i + 1;
      while (j < n && line[j] !== ch) { if (line[j] === "\\") j++; j++; }
      tokens.push({ cls: "tok-str", text: line.slice(i, Math.min(j + 1, n)) });
      i = j + 1;
      continue;
    }
    // Nombre.
    if (/[0-9]/.test(ch)) {
      let j = i;
      while (j < n && /[0-9._eExXa-fA-F]/.test(line[j])) j++;
      tokens.push({ cls: "tok-num", text: line.slice(i, j) });
      i = j;
      continue;
    }
    // Identifiant / mot-clé.
    if (/[A-Za-z_$]/.test(ch)) {
      let j = i;
      while (j < n && /[A-Za-z0-9_$]/.test(line[j])) j++;
      const word = line.slice(i, j);
      tokens.push({ cls: kw && kw.has(word) ? "tok-kw" : "", text: word });
      i = j;
      continue;
    }
    // Ponctuation / espaces : accumulés en texte brut jusqu'au prochain déclencheur.
    let j = i + 1;
    while (j < n) {
      const c = line[j];
      if (c === '"' || c === "'" || c === "`" || /[0-9A-Za-z_$]/.test(c)) break;
      if (line.startsWith(commentStart, j)) break;
      j++;
    }
    tokens.push({ cls: "", text: line.slice(i, j) });
    i = j;
  }
  return tokens;
}

// Alignement de lignes par LCS (programmation dynamique). Retourne une liste
// d'opérations {type, a, b} : 'eq' (a==b), 'del' (seulement à gauche),
// 'add' (seulement à droite). a/b = index de ligne (ou null).
function diffLines(aLines, bLines) {
  const m = aLines.length, k = bLines.length;
  // Table LCS. Bornée : au-delà de ~4000 lignes on tombe en séquentiel simple.
  const CAP = 4000;
  if (m > CAP || k > CAP) {
    const ops = [];
    const min = Math.min(m, k);
    for (let i = 0; i < min; i++) {
      if (aLines[i] === bLines[i]) ops.push({ type: "eq", a: i, b: i });
      else { ops.push({ type: "del", a: i, b: null }); ops.push({ type: "add", a: null, b: i }); }
    }
    for (let i = min; i < m; i++) ops.push({ type: "del", a: i, b: null });
    for (let j = min; j < k; j++) ops.push({ type: "add", a: null, b: j });
    return ops;
  }
  const dp = Array.from({ length: m + 1 }, () => new Int32Array(k + 1));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = k - 1; j >= 0; j--) {
      dp[i][j] = aLines[i] === bLines[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops = [];
  let i = 0, j = 0;
  while (i < m && j < k) {
    if (aLines[i] === bLines[j]) { ops.push({ type: "eq", a: i, b: j }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ type: "del", a: i, b: null }); i++; }
    else { ops.push({ type: "add", a: null, b: j }); j++; }
  }
  while (i < m) { ops.push({ type: "del", a: i, b: null }); i++; }
  while (j < k) { ops.push({ type: "add", a: null, b: j }); j++; }
  return ops;
}

// Rend une cellule de code colorée (ou vide) dans un conteneur ligne.
function sxsCell(row, sideCls, numText, lineText, lang, filler) {
  const gutter = node(row, "span", "sxs-num", numText);
  gutter.setAttribute("aria-hidden", "true");
  const code = node(row, "span", "sxs-code" + (filler ? " sxs-empty" : ""));
  if (!filler && lineText !== null) {
    for (const t of tokenizeLine(lineText, lang)) {
      node(code, "span", t.cls, t.text);
    }
    // Ligne vide → garder une hauteur de ligne.
    if (lineText.length === 0) code.appendChild(document.createTextNode("\u200b"));
  }
  return code;
}

const SXS_MAX_LINES = 4000;
function renderSideBySideDiff(container, original, modified, lang) {
  const aLines = String(original || "").split(/\r?\n/);
  const bLines = String(modified || "").split(/\r?\n/);
  // Un fichier terminé par un \n produit une dernière ligne vide parasite.
  if (aLines.length && aLines[aLines.length - 1] === "") aLines.pop();
  if (bLines.length && bLines[bLines.length - 1] === "") bLines.pop();
  const ops = diffLines(aLines, bLines);

  const grid = node(container, "div", "recap-sxs");
  let shown = 0;
  for (const op of ops) {
    if (shown >= SXS_MAX_LINES) break;
    shown++;
    if (op.type === "eq") {
      const row = node(grid, "div", "sxs-row sxs-eq");
      sxsCell(row, "old", String(op.a + 1), aLines[op.a], lang, false);
      sxsCell(row, "new", String(op.b + 1), bLines[op.b], lang, false);
    } else if (op.type === "del") {
      const row = node(grid, "div", "sxs-row sxs-del");
      sxsCell(row, "old", String(op.a + 1), aLines[op.a], lang, false);
      sxsCell(row, "new", "", null, lang, true);
    } else { // add
      const row = node(grid, "div", "sxs-row sxs-add");
      sxsCell(row, "old", "", null, lang, true);
      sxsCell(row, "new", String(op.b + 1), bLines[op.b], lang, false);
    }
  }
  const hidden = ops.length - shown;
  if (hidden > 0) {
    node(grid, "div", "sxs-truncated", t("panel.diff_truncated", { n: hidden }));
  }
  return grid;
}

function renderPreDiff(container, patch) {
  const pre = node(container, "pre", "recap-diff-body");
  const allLines = (patch || "").split("\n");
  const lines = allLines.slice(0, PRE_DIFF_MAX_LINES);
  for (const line of lines) {
    let cls = "diff-ctx";
    if (line.startsWith("+") && !line.startsWith("+++")) cls = "diff-add";
    else if (line.startsWith("-") && !line.startsWith("---")) cls = "diff-del";
    else if (line.startsWith("@@")) cls = "diff-hunk";
    node(pre, "span", cls, line + "\n");
  }
  const hidden = allLines.length - lines.length;
  if (hidden > 0) {
    node(pre, "span", "diff-truncated", t("panel.diff_truncated", { n: hidden }) + "\n");
  }
}

export function renderDiffBlock(root, d) {
  const patch = d.patch || "";
  const lines = patch.split("\n");
  const details = node(root, "details", "recap-diff");
  details.open = lines.length <= 200; // replié par défaut au-delà de 200 lignes
  const summary = node(details, "summary", "recap-diff-head");
  // Chevron d'affordance : le triangle natif du <details> est masqué en CSS
  // (::-webkit-details-marker display:none). Sans ce caret custom, un fichier
  // replié n'affiche que « fichier +n −n » sans aucun signal qu'on peut déplier.
  const caret = node(summary, "span", "recap-diff-caret", "");
  caret.setAttribute("aria-hidden", "true");
  node(summary, "code", "recap-diff-file", d.file || "");
  const stats = diffStats(patch);
  node(summary, "span", "recap-diff-add", "+" + stats.added);
  node(summary, "span", "recap-diff-del", "−" + stats.removed);
  const updateCaret = () => { caret.textContent = details.open ? "▾" : "▸"; };
  updateCaret();

  // Conteneur du corps : rendu side-by-side maison au DÉPLIAGE, vidé au REPLIAGE.
  const body = node(details, "div", "recap-diff-content");

  let mounted = false;    // garde anti-réentrance

  function mount() {
    if (mounted) return;
    if (!details.open) return;
    mounted = true;
    // Rendu side-by-side maison à partir des contenus complets original/modified
    // (100% offline, aucun CDN/Monaco → immunisé aux proxys restrictifs).
    // Fallback <pre> unifié uniquement si le payload ne porte NI original NI
    // modified (sessions historiques sans snapshots).
    if (!d.original && !d.modified) {
      renderPreDiff(body, patch);
      return;
    }
    renderSideBySideDiff(body, d.original || "", d.modified || "", langOf(d.file || ""));
  }

  function unmount() {
    mounted = false;
    body.replaceChildren();
  }

  details.addEventListener("toggle", () => {
    updateCaret();
    if (details.open) mount();
    else unmount();
  });
  // Petit diff ouvert par défaut → instancier immédiatement (event 'toggle' ne
  // se déclenche pas pour l'état initial open=true).
  if (details.open) mount();
}
