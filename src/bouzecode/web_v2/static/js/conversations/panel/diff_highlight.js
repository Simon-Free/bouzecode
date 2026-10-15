// [desc] Coloration syntaxique légère d'une ligne de code pour les diffs (commentaires, chaînes, nombres, mots-clés Python / JavaScript / TypeScript), sans dépendance. [/desc]

const PY = ["def", "class", "return", "if", "elif", "else", "for", "while", "import", "from", "as", "with", "try", "except",
  "finally", "raise", "yield", "lambda", "pass", "break", "continue", "and", "or", "not", "in", "is", "None", "True", "False",
  "async", "await", "global", "nonlocal", "assert", "del"];
const JS = ["function", "return", "if", "else", "for", "while", "const", "let", "var", "import", "from", "export", "default",
  "class", "extends", "new", "try", "catch", "finally", "throw", "await", "async", "yield", "typeof", "instanceof", "in", "of",
  "null", "undefined", "true", "false", "this", "super", "break", "continue", "switch", "case", "do"];
const KEYWORDS = {
  python: new Set(PY),
  javascript: new Set([...JS, "delete", "void"]),
  typescript: new Set([...JS, "implements", "interface", "type", "enum", "public", "private", "protected", "readonly", "as", "namespace"]),
};
const LANG_BY_EXT = { py: "python", js: "javascript", jsx: "javascript", mjs: "javascript", ts: "typescript", tsx: "typescript" };

export function langOf(path) {
  const ext = (String(path || "").split(".").pop() || "").toLowerCase();
  return LANG_BY_EXT[ext] || "plaintext";
}

const QUOTES = new Set(['"', "'", "`"]);
const isDigit = (c) => /[0-9]/.test(c);
const isWordStart = (c) => /[A-Za-z_$]/.test(c);

/** Fin (exclue) d'une chaîne ouverte en `i` ; les échappements sont sautés. */
function stringEnd(line, i) {
  let j = i + 1;
  while (j < line.length && line[j] !== line[i]) j += line[j] === "\\" ? 2 : 1;
  return Math.min(j + 1, line.length);
}

function runEnd(line, i, re) {
  let j = i;
  while (j < line.length && re.test(line[j])) j++;
  return j;
}

/** Ponctuation / espaces : jusqu'au prochain début de chaîne, de mot, de nombre ou de commentaire. */
function plainEnd(line, i, comment) {
  let j = i + 1;
  while (j < line.length && !QUOTES.has(line[j]) && !/[0-9A-Za-z_$]/.test(line[j]) && !line.startsWith(comment, j)) j++;
  return j;
}

/** Classe CSS et fin du jeton qui commence en `i`. */
function nextToken(line, i, lang, comment) {
  const ch = line[i];
  if (line.startsWith(comment, i)) return { cls: "tok-com", end: line.length };
  if (QUOTES.has(ch)) return { cls: "tok-str", end: stringEnd(line, i) };
  if (isDigit(ch)) return { cls: "tok-num", end: runEnd(line, i, /[0-9._eExXa-fA-F]/) };
  if (!isWordStart(ch)) return { cls: "", end: plainEnd(line, i, comment) };
  const end = runEnd(line, i, /[A-Za-z0-9_$]/);
  const kw = KEYWORDS[lang];
  return { cls: kw && kw.has(line.slice(i, end)) ? "tok-kw" : "", end };
}

/** Découpe UNE ligne en jetons {cls, text} ; tout ce qui n'est pas reconnu est du texte brut (cls ""). */
export function tokenizeLine(line, lang) {
  const comment = lang === "python" ? "#" : "//";
  const tokens = [];
  for (let i = 0; i < line.length;) {
    const { cls, end } = nextToken(line, i, lang, comment);
    tokens.push({ cls, text: line.slice(i, end) });
    i = end;
  }
  return tokens;
}
