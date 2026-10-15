// Helper de formatage temporel UNIQUE de la page Conversations (et lecteur de dates
// UNIQUE de tout le front : `parseInstant`). Toute heure affichée (sidebar, chips,
// onglets, marqueurs inline, recap, Bureau) passe par ici → une seule vérité.
//
// Le serveur émet deux formes d'instant (cf. services/horodatage.py) :
//   - la forme écrite désormais : ISO UTC à décalage explicite
//     ("2026-10-06T08:12:34+00:00", ou "…Z" chez l'ancien runner) ;
//   - l'héritage du store : ISO NAÏF = heure LOCALE de la machine serveur
//     ("2026-10-06T10:12:34", ou "2026-10-06 10:12:34" pour `saved_at`).
// `parseInstant` lit les deux ; une forme naïve est lue en heure locale du navigateur
// (le serveur et le navigateur sont la même machine). On affiche en heure LOCALE :
//   - aujourd'hui        → "HH:MM"
//   - hier               → "hier HH:MM"
//   - autre jour         → "JJ/MM HH:MM"
// Le tooltip garde l'instant complet (formatEventTimeTooltip).

// "AAAA-MM-JJ HH:MM[:SS[.fff…]]" + décalage facultatif. Séparateur espace → "T" (forme
// non normalisée par ECMAScript, rejetée par certains moteurs) ; fractions au-delà de la
// milliseconde tronquées (Python écrit des microsecondes) ; "+0200" → "+02:00".
const ISO_SERVEUR = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$/i;

function _normaliser(texte) {
  const m = ISO_SERVEUR.exec(texte);
  if (!m) return texte;
  const fraction = m[3] ? `.${m[3].slice(0, 3).padEnd(3, "0")}` : "";
  const decalage = (m[4] || "").toUpperCase().replace(/^([+-]\d{2})(\d{2})$/, "$1:$2");
  // Sans décalage, ECMAScript lit "AAAA-MM-JJTHH:MM:SS" en heure LOCALE : c'est voulu.
  return `${m[1]}T${m[2]}${fraction}${decalage}`;
}

export function parseInstant(iso) {
  if (!iso) return null;
  if (iso instanceof Date) return isNaN(iso.getTime()) ? null : iso;
  const d = new Date(_normaliser(String(iso).trim()));
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
  const d = parseInstant(iso);
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
  const d = parseInstant(iso);
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
