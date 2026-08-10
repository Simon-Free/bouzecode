// Helpers sans état ni dépendance, partagés par tous les modules de la page
// Conversations. Feuille du graphe d'imports : ne dépend de RIEN, donc importable
// depuis n'importe quel module sans jamais créer de cycle.

// Crée <tag class=cls>text</tag>, l'appende à `el` et le retourne.
export function node(el, tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  el.appendChild(n);
  return n;
}

// "agent/<id>" -> "<id>" ; toute autre clé est rendue telle quelle.
export function agentId(key) {
  return key && key.startsWith("agent/") ? key.slice("agent/".length) : key;
}
