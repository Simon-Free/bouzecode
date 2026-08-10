// Helper de formatage temporel UNIQUE de la page Conversations.
// Toute heure affichée (sidebar, chips, onglets, marqueurs inline, recap) passe
// par ici → une seule vérité, plus d'incohérence UTC vs local.
//
// L'entrée est TOUJOURS un instant ISO UTC (ex. "2026-07-06T23:41:00Z") émis par
// le serveur. On le convertit en heure LOCALE du navigateur :
//   - aujourd'hui        → "HH:MM"
//   - hier               → "hier HH:MM"
//   - autre jour         → "JJ/MM HH:MM"
// Le tooltip garde l'ISO complet (formatEventTimeTooltip).

function _parse(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

function _pad(n) {
  return String(n).padStart(2, "0");
}

// Nombre de jours calendaires (heure LOCALE) entre `then` et `now`.
// 0 = même jour, 1 = la veille, etc. Indépendant de l'heure de la journée.
function _dayDiff(then, now) {
  const a = new Date(then.getFullYear(), then.getMonth(), then.getDate());
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((b - a) / 86400000);
}

export function formatEventTime(iso, now = new Date()) {
  const d = _parse(iso);
  if (!d) return "";
  const hhmm = `${_pad(d.getHours())}:${_pad(d.getMinutes())}`;
  const diff = _dayDiff(d, now);
  if (diff === 0) return hhmm;
  if (diff === 1) return `hier ${hhmm}`;
  return `${_pad(d.getDate())}/${_pad(d.getMonth() + 1)} ${hhmm}`;
}

// Tooltip = instant complet, non ambigu. On rend l'ISO local (avec fuseau) pour
// que l'utilisateur voie l'instant exact ; à défaut de Date valide, l'ISO brut.
export function formatEventTimeTooltip(iso) {
  const d = _parse(iso);
  if (!d) return iso || "";
  return d.toLocaleString();
}

// Hydrate tous les <span class="event-time" data-iso="..."> d'un sous-arbre DOM :
// remplit le texte (heure locale) + le tooltip (instant complet). Idempotent.
export function hydrateEventTimes(root, now = new Date()) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll(".event-time[data-iso]").forEach((el) => {
    const iso = el.getAttribute("data-iso") || "";
    el.textContent = formatEventTime(iso, now);
    el.title = formatEventTimeTooltip(iso);
  });
}
