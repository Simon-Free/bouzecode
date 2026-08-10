// Ce que le front LIT sur un node de /api/agents/tree, isolé en un seul endroit :
// une évolution du backend se répercute ici et nulle part ailleurs.

// --- CONTRAT avec le backend, isolé ici ------------------------------------
// Champs lus sur un node de /api/agents/tree :
//   - category: "test" | "subagent" | "user" | "meta"   (nature de la conversation)
//     SERVI par le backend (services/work/fleet.py, même classifieur que /api/sessions).
//     L'heuristique de repli qui devinait la nature via le titre et le flag `isolated`
//     a été retirée : elle classait tout dispatch manuel en « méta ».
//   - archived: PAS un champ du tree. Une conversation archivée est soft-deleted
//     côté serveur et disparaît de l'arbre ; seuls les nodes optimistes locaux
//     portent `archived:false`. isArchived reste donc une garde purement locale.
// Tri need_input : DÉJÀ fait côté backend (agent_tree floate les awaiting_* en tête) ;
//   on ne trie donc pas ici, on le REFLÈTE visuellement (section dédiée en tête).
export const CONTRACT = {
  categoryOf(n) { return n.category || ""; },
  isArchived(n) { return n.archived === true; },
  // Un agent planté (crash/restart sans FinalAnswer, n.interrupted) est traité comme un
  // « input à await » : décider de son sort EST un input attendu. Il remonte donc en
  // section needinput (tête de liste, cadre orange) avec le formatage awaiting.
  needsInput(n) { return n.state === "awaiting_input" || n.state === "awaiting_plan_validation" || n.interrupted === true; },
  // Endpoint réel du backend (routes/sessions.py) : POST /api/conversations/archive
  // avec body {keys:["agent/<id>", ...]}. Réversible via /api/sessions/<key>/restore.
  archiveUrl() { return `/api/conversations/archive`; },
};
// "subagent" retiré : les vrais sous-agents sont imbriqués sous leur racine,
// jamais des racines de premier niveau → la catégorie restait toujours vide.
const CATEGORY_ORDER = ["user", "meta", "test"];
const CATEGORY_LABEL = { user: "Conversations", meta: "Méta-agent", subagent: "Sous-agents", test: "Tests" };
