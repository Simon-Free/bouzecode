// [desc] Gestes de l'en-tête d'un agent : Continuer (même agent), Relancer (nouvel agent, par sa tâche ou son ticket), Arrêter (fin du tour), Forcer l'arrêt (tuer le processus), Réessayer un lancement échoué. Chacun : confirmation si nécessaire, bouton occupé, toast de résultat. [/desc]

import { api, busy, toast, confirm as askConfirm } from "../../lib/ui.js";
import { emit } from "../store.js";
import { agentIdOf, ticketBody } from "../model.js";

const RELAUNCH_TEXT = "Un NOUVEL agent repart de la demande d'origine (et du récap des passages précédents s'il s'agit d'une tâche). "
  + "Sa préparation prend en général 30 à 60 s. L'agent arrêté n'est pas repris : utilise « Continuer » pour cela.";

function agentUrl(entry, action) {
  return `/api/agents/${encodeURIComponent(agentIdOf(entry.key))}/${action}`;
}

/** Après un geste : le fil se rafraîchit vite et la liste suit. */
function afterGesture(entry) {
  entry.thread.kick();
  emit("refresh-tree");
}

/** Retrouve le dépôt du ticket d'un agent dont l'arbre ne le donne pas : on le cherche dans chaque dépôt. */
async function findTicketSlug(ticketId) {
  for (const p of (await api("GET", "/api/projects")).projects || []) {
    const list = await api("GET", `/api/projects/${encodeURIComponent(p.slug)}/tickets?archived=all`);
    if ((list.tickets || []).some((t) => t.id === ticketId)) return p.slug;
  }
  throw new Error("impossible de retrouver le ticket de cet agent dans les dépôts enregistrés.");
}

/** Relance par le ticket : un agent NEUF (`POST …/runs`), avec l'isolation DU TICKET — le front ne
 *  l'envoie plus, le serveur la garde (C8). */
async function relaunchTicket(node) {
  const tid = node && node.ticket_id;
  if (!tid) throw new Error("cet agent n'est rattaché à aucun ticket : lance une nouvelle conversation à la place.");
  const slug = node.project_slug || await findTicketSlug(tid);
  return api("POST", `/api/projects/${encodeURIComponent(slug)}/tickets/${encodeURIComponent(tid)}/runs`, {},
    { timeout: 180000 });
}

/** Relance un agent arrêté sans finir : par sa tâche si elle existe, sinon par son ticket. */
export async function relaunch(entry, node, btn) {
  const title = entry.title || "cet agent";
  if (!(await askConfirm({ title: "Relancer avec un nouvel agent ?", text: RELAUNCH_TEXT, confirmLabel: "Relancer" }))) return;
  await busy(btn, "Relance… (≈ 30-60 s)", async () => {
    try {
      const res = node && node.micro_id
        ? await api("POST", `/api/micros/${encodeURIComponent(node.micro_id)}/relancer`, { mode: "nouvel_agent" }, { timeout: 120000 })
        : await relaunchTicket(node);
      const key = res.key || (res.agent_id ? `agent/${res.agent_id}` : "") || res.launch_key;
      toast.ok(`« ${title} » relancé.`, key ? { action: { label: "Ouvrir", fn: () => emit("open", { key }) } } : {});
      if (key) emit("open", { key, title });
      emit("refresh-tree");
    } catch (err) {
      toast.err(`Relance impossible : ${err.message}`);
    }
  });
}

/** « Continuer » : même agent ; le message tapé dans le champ du bas, s'il y en a un, est joint
 *  à la reprise (et le champ vidé) — sinon la reprise part avec la consigne par défaut. */
export async function resume(entry, btn) {
  const champ = entry.panelEl && entry.panelEl.querySelector(".ag-composer__input");
  const text = champ ? champ.value.trim() : "";
  await busy(btn, "Reprise…", async () => {
    try {
      await api("POST", agentUrl(entry, "messages"), { text, mode: "refuse" }, { timeout: 60000 });
      if (champ && text) champ.value = "";
      toast.ok(text ? "L'agent reprend avec ton message." : "L'agent reprend là où il s'était arrêté.");
      afterGesture(entry);
    } catch (err) {
      toast.err(`Reprise impossible : ${err.message}${text ? " — ton message est resté dans le champ." : ""}`);
    }
  });
}

export async function stop(entry, btn) {
  const ok = await askConfirm({
    title: "Arrêter l'agent ?",
    text: "Son tour en cours est interrompu. Tu pourras lui écrire ensuite pour qu'il continue.",
    confirmLabel: "Arrêter", danger: true,
  });
  if (!ok) return;
  await busy(btn, "Arrêt…", async () => {
    try {
      const res = await api("POST", agentUrl(entry, "interruptions"), undefined, { timeout: 30000, okField: true });
      toast.ok(res && res.escalated ? "Agent arrêté (il ne répondait plus : son processus a été arrêté)." : "Agent arrêté : il attend ton prochain message.");
      afterGesture(entry);
    } catch (err) {
      toast.err(`Arrêt impossible : ${err.message}`);
    }
  });
}

export async function kill(entry) {
  const ok = await askConfirm({
    title: "Forcer l'arrêt du processus ?",
    text: "Le processus de l'agent est tué immédiatement, sans sauvegarde du tour en cours. À réserver à un agent bloqué.",
    confirmLabel: "Forcer l'arrêt", danger: true,
  });
  if (!ok) return;
  try {
    await api("POST", agentUrl(entry, "stop"), undefined, { okField: true });
    toast.ok("Processus arrêté.");
    afterGesture(entry);
  } catch (err) {
    toast.err(`Arrêt forcé impossible : ${err.message}`);
  }
}

/** Demande d'origine d'un lancement : celle de l'onglet, sinon reconstituée depuis le nœud. */
function originalLaunch(entry, node) {
  if (entry.launch) return entry.launch;
  if (!node) return null;
  return { prompt: node.title_full || node.title, project_slug: node.project_slug, typology: "", isolation: "" };
}

/** Relance un lancement échoué avec les mêmes paramètres (même prompt, même dépôt). */
export async function retryLaunch(entry, node, btn, hooks) {
  const launch = originalLaunch(entry, node);
  if (!launch || !launch.prompt) { toast.err("Impossible de retrouver la demande d'origine : relance-la depuis la barre de lancement."); return; }
  await busy(btn, "Nouvel essai…", async () => {
    try {
      const res = node && node.ticket_id && launch.project_slug
        ? await api("POST", `/api/projects/${encodeURIComponent(launch.project_slug)}/tickets/${encodeURIComponent(node.ticket_id)}/runs`, {}, { timeout: 60000 })
        : await api("POST", `/api/projects/${encodeURIComponent(launch.project_slug)}/tickets`, ticketBody(launch), { timeout: 60000 });
      const tid = res.ticket_id || (res.ticket && res.ticket.id) || "";
      const key = res.launch_key || (tid ? `launching/${tid}` : "");
      toast.ok("Nouveau lancement parti.");
      if (key) { entry.launch = launch; hooks.retarget(key); entry.thread.restart(); }
      emit("refresh-tree");
    } catch (err) {
      toast.err(`Le lancement échoue encore : ${err.message}`);
    }
  });
}
