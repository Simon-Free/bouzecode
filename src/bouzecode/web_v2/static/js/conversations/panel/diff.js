// [desc] Rendu des diffs (récap et fichiers modifiés) : côte à côte maison, hors ligne (aucun CDN, fonctionne derrière le proxy), avec repli en diff unifié pour les sessions sans instantanés ; corps rendu au dépliage seulement. [/desc]

import { h } from "../../lib/ui.js";
import { langOf, tokenizeLine } from "./diff_highlight.js";

const PRE_DIFF_MAX_LINES = 400;
const SXS_MAX_LINES = 4000;
// Au-delà, alignement séquentiel : un LCS O(n·m) figerait l'onglet.
const LCS_CAP = 1500;
const OPEN_BY_DEFAULT_MAX_LINES = 200;

function add(el, tag, cls, text) {
  const n = h(tag, cls ? { class: cls } : {}, text === undefined ? null : text);
  el.appendChild(n);
  return n;
}

function diffStats(patch) {
  const lines = patch.split("\n");
  return {
    added: lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length,
    removed: lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length,
  };
}

// ---------------------------------------------------------------- alignement

/** Alignement ligne à ligne (fichiers trop gros pour un LCS). */
function sequentialOps(m, k, same) {
  const ops = [];
  const min = Math.min(m, k);
  for (let i = 0; i < min; i++) {
    if (same(i, i)) ops.push({ type: "eq", a: i, b: i });
    else ops.push({ type: "del", a: i, b: null }, { type: "add", a: null, b: i });
  }
  for (let i = min; i < m; i++) ops.push({ type: "del", a: i, b: null });
  for (let j = min; j < k; j++) ops.push({ type: "add", a: null, b: j });
  return ops;
}

function lcsTable(aLines, bLines) {
  const m = aLines.length, k = bLines.length;
  const dp = Array.from({ length: m + 1 }, () => new Int32Array(k + 1));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = k - 1; j >= 0; j--) {
      dp[i][j] = aLines[i] === bLines[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  return dp;
}

function lcsOps(aLines, bLines) {
  const dp = lcsTable(aLines, bLines);
  const m = aLines.length, k = bLines.length;
  const ops = [];
  let i = 0, j = 0;
  while (i < m && j < k) {
    if (aLines[i] === bLines[j]) ops.push({ type: "eq", a: i++, b: j++ });
    else if (dp[i + 1][j] >= dp[i][j + 1]) ops.push({ type: "del", a: i++, b: null });
    else ops.push({ type: "add", a: null, b: j++ });
  }
  while (i < m) ops.push({ type: "del", a: i++, b: null });
  while (j < k) ops.push({ type: "add", a: null, b: j++ });
  return ops;
}

/** Opérations {type: eq|del|add, a, b} (index de ligne à gauche / à droite, ou null). */
function diffLines(aLines, bLines) {
  if (aLines.length > LCS_CAP || bLines.length > LCS_CAP) {
    return sequentialOps(aLines.length, bLines.length, (i, j) => aLines[i] === bLines[j]);
  }
  return lcsOps(aLines, bLines);
}

// ---------------------------------------------------------------- rendu

/** Une cellule : numéro de ligne + code coloré, ou case vide en face d'un ajout / d'une suppression. */
function cell(row, num, text, lang) {
  add(row, "span", "sxs-num", num).setAttribute("aria-hidden", "true");
  const code = add(row, "span", text === null ? "sxs-code sxs-empty" : "sxs-code");
  if (text === null) return;
  for (const t of tokenizeLine(text, lang)) add(code, "span", t.cls, t.text);
  // Ligne vide : garder une hauteur de ligne.
  if (!text.length) code.appendChild(document.createTextNode("​"));
}

const ROW_CLASS = { eq: "sxs-row sxs-eq", del: "sxs-row sxs-del", add: "sxs-row sxs-add" };

function sxsRow(grid, op, aLines, bLines, lang) {
  const row = add(grid, "div", ROW_CLASS[op.type]);
  cell(row, op.a === null ? "" : String(op.a + 1), op.a === null ? null : aLines[op.a], lang);
  cell(row, op.b === null ? "" : String(op.b + 1), op.b === null ? null : bLines[op.b], lang);
}

function splitLines(text) {
  const lines = String(text || "").split(/\r?\n/);
  // Un fichier terminé par un \n produit une dernière ligne vide parasite.
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

function renderSideBySideDiff(container, original, modified, lang) {
  const aLines = splitLines(original);
  const bLines = splitLines(modified);
  const ops = diffLines(aLines, bLines);
  const grid = add(container, "div", "recap-sxs");
  for (const op of ops.slice(0, SXS_MAX_LINES)) sxsRow(grid, op, aLines, bLines, lang);
  if (ops.length > SXS_MAX_LINES) add(grid, "div", "sxs-truncated", `… (${ops.length - SXS_MAX_LINES} lignes supplémentaires masquées)`);
}

function unifiedClass(line) {
  if (line.startsWith("+") && !line.startsWith("+++")) return "diff-add";
  if (line.startsWith("-") && !line.startsWith("---")) return "diff-del";
  return line.startsWith("@@") ? "diff-hunk" : "diff-ctx";
}

/** Repli pour les sessions historiques sans instantanés : le patch unifié, coloré. */
function renderPreDiff(container, patch) {
  const pre = add(container, "pre", "recap-diff-body");
  const lines = (patch || "").split("\n");
  for (const line of lines.slice(0, PRE_DIFF_MAX_LINES)) add(pre, "span", unifiedClass(line), `${line}\n`);
  if (lines.length > PRE_DIFF_MAX_LINES) add(pre, "span", "diff-truncated", `… (${lines.length - PRE_DIFF_MAX_LINES} lignes supplémentaires masquées)\n`);
}

function diffSummary(details, d, patch) {
  const summary = add(details, "summary", "recap-diff-head");
  // Chevron visible : le triangle natif du <details> est masqué en CSS.
  const caret = add(summary, "span", "recap-diff-caret", "");
  caret.setAttribute("aria-hidden", "true");
  add(summary, "code", "recap-diff-file", d.file || "");
  if (d.is_new) add(summary, "span", "recap-diff-new", "nouveau");
  const stats = d.stats || diffStats(patch);
  add(summary, "span", "recap-diff-add", `+${stats.added ?? 0}`);
  if (stats.removed !== undefined) add(summary, "span", "recap-diff-del", `−${stats.removed}`);
  return caret;
}

/** Un fichier : en-tête repliable ; le corps est rendu au dépliage et vidé au repliage. */
export function renderDiffBlock(root, d) {
  const patch = d.patch || "";
  const details = add(root, "details", "recap-diff");
  details.open = patch.split("\n").length <= OPEN_BY_DEFAULT_MAX_LINES;
  const caret = diffSummary(details, d, patch);
  const body = add(details, "div", "recap-diff-content");
  let mounted = false;

  function sync() {
    caret.textContent = details.open ? "▾" : "▸";
    if (!details.open) { mounted = false; body.replaceChildren(); return; }
    if (mounted) return;
    mounted = true;
    if (!d.original && !d.modified) renderPreDiff(body, patch);
    else renderSideBySideDiff(body, d.original || "", d.modified || "", langOf(d.file || ""));
  }
  details.addEventListener("toggle", sync);
  // L'événement « toggle » ne part pas pour l'état initial ouvert : on monte tout de suite.
  sync();
}
