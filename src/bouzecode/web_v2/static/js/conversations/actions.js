// [desc] Gestes sur un agent partagés par la liste et le panneau : archiver (arrêt préalable si l'agent travaille, effet immédiat, toast « Annuler »), restaurer, copier dans le presse-papier. [/desc]
//
// Ce module ne connaît pas la liste : il masque des clés dans `state.hiding`, puis demande un
// rendu et un rechargement par le bus (`render`, `reload-tree`, `archives-changed`).

import { api, toast, confirm as askConfirm } from "../lib/ui.js";
import { state, emit, emitAndWait, countsChanged } from "./store.js";
import { agentIdOf, buildTree, descendantsOf, nodeState } from "./model.js";

/** Copie `text` et le dit ; en cas de refus du presse-papier, le texte est affiché. */
export async function copyText(text, what) {
  if (!text) { toast.err(`${what} indisponible.`); return; }
  try {
    await navigator.clipboard.writeText(text);
    toast.ok(`${what} copié : ${text}`);
  } catch (err) {
    toast.err(`Copie impossible (${(err && err.message) || "presse-papier refusé"}) : ${text}`);
  }
}

/** L'agent et tous ses sous-agents : archiver un agent principal range tout son arbre. */
function keysToArchive(node) {
  const tree = buildTree(state.nodes);
  const id = node.agent_id || agentIdOf(node.key);
  return [node.key, ...descendantsOf(tree, id).map((d) => d.key)]
    .filter((k) => String(k).startsWith("agent/"));
}

function setHidden(keys, hidden) {
  for (const k of keys) {
    if (hidden) state.hiding.add(k); else state.hiding.delete(k);
  }
  emit("render");
}

/** Un agent qui travaille est d'abord arrêté (avec confirmation). Renvoie false si l'on s'arrête là. */
async function stopBeforeArchive(node) {
  const ok = await askConfirm({
    title: "Archiver un agent qui travaille ?",
    text: "Il sera d'abord arrêté, puis rangé dans « Archivés ». Tu pourras le restaurer.",
    confirmLabel: "Arrêter et archiver", danger: true,
  });
  if (!ok) return false;
  try {
    await api("POST", `/api/agents/${encodeURIComponent(agentIdOf(node.key))}/stop`, undefined, { okField: true });
    return true;
  } catch (err) {
    toast.err(`Arrêt impossible, l'agent n'est pas archivé : ${err.message}`);
    return false;
  }
}

/** POST d'archivage ; renvoie le message d'erreur à afficher, ou "" si l'archivage a eu lieu. */
async function postArchive(keys, title) {
  try {
    const res = await api("POST", "/api/conversations/archive", { keys });
    const skipped = (res && res.skipped) || [];
    if (skipped.length && !((res && res.archived) || []).length) {
      return `« ${title} » n'a pas été archivé : ${skipped.map((s) => s.reason).join(" ; ")}`;
    }
    return "";
  } catch (err) {
    return `Archivage impossible : ${err.message}`;
  }
}

export async function archiveNode(node) {
  if (!String(node.key).startsWith("agent/")) {
    toast.info("Un lancement en cours ou échoué ne s'archive pas : il disparaît de lui-même.");
    return;
  }
  // Seul un agent qui travaille attend une confirmation : sinon la carte disparaît sur-le-champ (R3).
  if (nodeState(node).group === "en_cours" && !(await stopBeforeArchive(node))) return;
  const keys = keysToArchive(node);
  const title = node.title || "Agent";
  setHidden(keys, true);
  const problem = await postArchive(keys, title);
  if (problem) {
    setHidden(keys, false);
    toast.err(problem);
    return;
  }
  toast.ok(`« ${title} » archivé.`, { action: { label: "Annuler", fn: () => restoreKeys(keys, title) } });
  emit("archived", keys);
  await emitAndWait("reload-tree");
  emit("archives-changed");
  setHidden(keys, false);
  countsChanged();
}

export async function restoreKeys(keys, title) {
  const errors = [];
  for (const k of keys) {
    try { await api("POST", `/api/sessions/${k}/restore`); } catch (err) { if (err.status !== 404) errors.push(err.message); }
  }
  if (errors.length) toast.err(`Restauration incomplète : ${errors[0]}`);
  else toast.ok(`« ${title || "Agent"} » restauré.`);
  emit("restored", keys);
  await emitAndWait("reload-tree");
  emit("archives-changed");
  countsChanged();
}

/** Lien vers la tâche liée sur le Bureau. */
export function openTaskOnBureau(microId) {
  location.href = `/bureau?tache=${encodeURIComponent(microId)}`;
}
