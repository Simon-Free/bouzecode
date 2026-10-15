// [desc] Mémorisation locale des préférences de la page Agents (dépôt, profil, environnement choisis, onglets ouverts, groupes repliés). Le stockage peut être refusé (navigation privée) : on le dit en console et la page continue. [/desc]

export function recallText(key, fallback = "") {
  try { return localStorage.getItem(key) ?? fallback; } catch (err) { console.warn("préférence illisible", key, err); return fallback; }
}

export function rememberText(key, value) {
  try { localStorage.setItem(key, value); } catch (err) { console.warn("préférence non mémorisée", key, err); }
}

export function recallJson(key, fallback) {
  const raw = recallText(key, "");
  if (!raw) return fallback;
  try { return JSON.parse(raw); } catch (err) { console.warn("préférence illisible", key, err); return fallback; }
}

export function rememberJson(key, value) {
  rememberText(key, JSON.stringify(value));
}
