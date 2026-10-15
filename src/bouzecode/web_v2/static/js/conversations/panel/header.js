// [desc] En-tête du panneau d'un agent : état (libellé + icône), titre, dépôt / branche / modèle / tâche liée, boutons adaptés à l'état (Arrêter, Continuer, Relancer, Réessayer, Restaurer) avec leur explication, et menu ⋯. Les gestes vivent dans header_actions.js. [/desc]

import { busy, menu, h } from "../../lib/ui.js";
import { badge } from "../../lib/states.js";
import { findNode } from "../store.js";
import { agentIdOf, nodeState, isolationLabel } from "../model.js";
import { archiveNode, restoreKeys, copyText, openTaskOnBureau } from "../actions.js";
import { relaunch, resume, stop, kill, retryLaunch } from "./header_actions.js";

const CRASH_HELP = "« Continuer » reprend le même agent dans cette conversation. « Relancer » crée un nouvel agent qui repart de la demande d'origine (≈ 30-60 s).";
const MISSING_HELP = "La fiche de cet agent a disparu : seul un nouvel agent peut reprendre ce travail.";

function isAgent(entry) { return entry.key.startsWith("agent/"); }
function isLaunching(entry) { return entry.key.startsWith("launching/"); }

function buildButtons(entry, hooks) {
  const btn = {
    stop: h("button", { type: "button", class: "btn btn--danger btn--sm", title: "Interrompt le tour en cours ; l'agent attend ensuite ton message." }, "Arrêter"),
    resume: h("button", { type: "button", class: "btn btn--primary btn--sm", title: "Même agent, même conversation : il reprend là où il s’est arrêté. Le message tapé dans le champ du bas (optionnel) lui est joint." }, "Continuer"),
    relaunch: h("button", { type: "button", class: "btn btn--sm", title: "Nouvel agent, repart de la demande d'origine (≈ 30-60 s de préparation)." }, "Relancer"),
    retry: h("button", { type: "button", class: "btn btn--primary btn--sm" }, "Réessayer le lancement"),
    restore: h("button", { type: "button", class: "btn btn--primary btn--sm" }, "Restaurer"),
  };
  btn.stop.addEventListener("click", () => stop(entry, btn.stop));
  btn.resume.addEventListener("click", () => resume(entry, btn.resume));
  btn.relaunch.addEventListener("click", () => relaunch(entry, findNode(entry.key), btn.relaunch));
  btn.retry.addEventListener("click", () => retryLaunch(entry, findNode(entry.key), btn.retry, hooks));
  btn.restore.addEventListener("click", () => busy(btn.restore, "Restauration…", async () => {
    await restoreKeys([entry.key], entry.title);
    entry.thread.restart();
  }));
  return btn;
}

/** Boutons visibles et explication, selon l'état de l'agent. */
function actionsFor(st, entry, btn) {
  if (st.key === "archived") return { shown: [btn.restore], help: "" };
  if (st.key === "launch_failed") return { shown: [btn.retry], help: "" };
  if (st.key === "crashed") return { shown: [btn.resume, btn.relaunch], help: CRASH_HELP };
  if (st.key === "missing") return { shown: [btn.relaunch], help: MISSING_HELP };
  if (st.group === "en_cours" && isAgent(entry)) return { shown: [btn.stop], help: "" };
  return { shown: [], help: "" };
}

function sessionItems(entry, node) {
  const path = node && node.session_path;
  return [
    { label: "Copier l'identifiant", fn: () => copyText(agentIdOf(entry.key), "Identifiant") },
    { label: "Copier le chemin de la session", disabled: !path, fn: () => copyText(path, "Chemin"), hint: path || "Chemin indisponible" },
    { label: "Télécharger la session (JSON)", fn: () => { location.href = `/api/sessions/${entry.key}/download`; } },
  ];
}

function lifecycleItems(entry, node) {
  const st = entry.stateInfo;
  const items = ["sep"];
  if (st && st.key === "archived") items.push({ label: "Restaurer", fn: () => restoreKeys([entry.key], entry.title) });
  else if (node) items.push({ label: "Archiver", fn: () => archiveNode(node) });
  if (st && st.group === "en_cours") items.push({ label: "Forcer l'arrêt (tuer le processus)", danger: true, fn: () => kill(entry) });
  return items;
}

function menuItems(entry, hooks) {
  const node = findNode(entry.key);
  const items = isAgent(entry) ? sessionItems(entry, node) : [];
  if (node && node.micro_id) items.push({ label: "Voir la tâche sur le Bureau", fn: () => openTaskOnBureau(node.micro_id) });
  items.push({ label: "Fermer l'onglet", fn: () => hooks.close() });
  return isAgent(entry) ? items.concat(lifecycleItems(entry, node)) : items;
}

function plain(value, title, tag = "span") {
  return h(tag, { title }, value);
}

function repoOf(entry, node) {
  if (node && (node.project_name || node.project_slug)) return node.project_name || node.project_slug;
  return entry.launch ? entry.launch.project_slug : "";
}

/** Environnement demandé, affiché seulement pendant le lancement (ensuite c'est la branche qui parle). */
function launchEnv(entry) {
  return isLaunching(entry) && entry.launch && entry.launch.isolation ? isolationLabel(entry.launch.isolation) : "";
}

function taskLink(node) {
  if (!node || !node.micro_id) return null;
  return h("a", { href: `/bureau?tache=${encodeURIComponent(node.micro_id)}` }, "↗ tâche sur le Bureau");
}

/** Agent démarré sur un commit antérieur au HEAD du dépôt (meta de /blocks) : son process
 *  exécute l'ancien code, des bugs « déjà corrigés » peuvent y reparaître. */
function staleCode(meta) {
  if (!meta || !meta.code_stale) return null;
  const boot = String(meta.code_boot_sha || "").slice(0, 8);
  const head = String(meta.code_head_sha || "").slice(0, 8);
  return h("span", {
    class: "badge ag-head__stale", "data-tone": "warn",
    title: `Cet agent a démarré sur le commit ${boot} ; le dépôt est maintenant sur ${head}. `
      + "Il exécute l'ancien code : relance-le pour avoir les derniers correctifs.",
  }, "⚠ code antérieur");
}

/** Ligne dépôt · branche · environnement · modèle · tâche liée · code antérieur. */
function metaItems(entry, node, model) {
  const repo = repoOf(entry, node);
  const env = launchEnv(entry);
  return [
    repo ? plain(repo, "Dépôt") : null,
    node && node.branch ? plain(node.branch, "Branche", "code") : null,
    env ? h("span", {}, env) : null,
    model ? h("span", {}, model) : null,
    taskLink(node),
    staleCode(entry.meta),
  ].filter(Boolean);
}

function withSeparators(items) {
  return items.flatMap((m, i) => (i ? [h("span", { class: "ag-head__sep", "aria-hidden": "true" }, "·"), m] : [m]));
}

function headerTitle(entry, node) {
  return (node && (node.title || node.tache_titre)) || entry.title || "Agent";
}

function modelOf(entry, node) {
  return (entry.meta && entry.meta.model) || (node && node.model) || "";
}

function currentState(entry, node) {
  if (entry.stateInfo) return entry.stateInfo;
  return nodeState(node || { etat: isLaunching(entry) ? "preparing" : "unknown" });
}

export function createHeader(entry, el, hooks) {
  const badgeSlot = h("span", { class: "ag-head__badge" });
  const titleEl = h("h2", { class: "ag-head__title" });
  const metaEl = h("div", { class: "ag-head__meta" });
  const actions = h("div", { class: "ag-head__actions" });
  const more = h("button", { type: "button", class: "btn btn--ghost btn--sm btn--icon", "aria-label": "Plus d'actions" }, "⋯");
  const moreWrap = h("span", { class: "menu" }, more);
  el.append(h("div", { class: "ag-head__main" }, h("div", { class: "ag-head__line" }, badgeSlot, titleEl), metaEl), actions);
  const btn = buildButtons(entry, hooks);
  menu(more, () => menuItems(entry, hooks));

  let lastSig = "";
  function update() {
    const node = findNode(entry.key);
    const st = currentState(entry, node);
    const title = headerTitle(entry, node);
    if (title !== entry.title && !isLaunching(entry)) { entry.title = title; hooks.repaintTab(); }
    const model = modelOf(entry, node);
    const sig = JSON.stringify([st.key, title, node && [node.project_name, node.branch, node.micro_id, node.tache_titre, node.launch_error, node.isolated], model, !!entry.launch, entry.meta && [entry.meta.code_stale, entry.meta.code_boot_sha, entry.meta.code_head_sha]]);
    if (sig === lastSig) return;
    lastSig = sig;
    badgeSlot.replaceChildren(badge(st, { text: true }));
    titleEl.textContent = title;
    titleEl.title = (node && node.title_full) || title;
    metaEl.replaceChildren(...withSeparators(metaItems(entry, node, model)));
    const { shown, help: helpText } = actionsFor(st, entry, btn);
    actions.replaceChildren(...shown, moreWrap);
    //  L'explication passe en infobulle du bouton au lieu d'un paragraphe permanent. Avec deux
    //  boutons (Continuer / Relancer), chacun porte déjà sa propre explication.
    if (helpText && shown.length === 1 && !shown[0].title) shown[0].title = helpText;
  }
  return { update };
}
