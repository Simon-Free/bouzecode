// [desc] Envoi d'un message à l'assistant du Bureau : écho immédiat, ouverture de la conversation (dépôt d'ancrage demandé si besoin), message « en attente » lu à sa prochaine étape s'il travaille (avec Annuler), et Interrompre (bouton, Échap). [/desc]
//
// Contrats serveur :
//   démarrer : POST /api/projects/<slug>/tickets {title, prompt, typology:"bureau-assistant",
//              isolation:"shared", launch:true, defer:false}  (renvoie key + ticket_id)
//   parler   : POST /api/agents/<id>/messages {text, mode:"queue"}
//              → 202 {queued, queue_id, en_tour} si l'assistant est en plein tour : le message
//                est déposé dans sa boîte et lu à sa prochaine étape (après ses outils en cours),
//              → 200 sinon ; DELETE /api/agents/<id>/queue/<qid> annule un message pas encore lu.
//   interrompre : POST /api/agents/<id>/interruptions → {ok, escalated} ; il repart avec ce qui attend.

import { h, api, busy, toast } from "../lib/ui.js";
import { state } from "./store.js";
import { n, conv, agentId, statut, lireMemoire, ecrireMemoire, reprendre, chargerHistorique, reveillerFil } from "./assistant_fil.js";

const MEMOIRE_PROJET = "bureau.assistant.projet";
const TYPOLOGIE = "bureau-assistant";

/** Bulle du message envoyé, affichée tout de suite (« envoi… »), mise à jour selon le résultat. */
function echo(texte) {
  const etat = h("span", { class: "bz-echo__etat" }, "envoi…");
  const el = h("div", { class: "bz-echo", role: "status" }, h("div", { class: "bz-echo__txt" }, texte), etat);
  n.fil.querySelector(".bz-assist__intro")?.remove();
  n.fil.appendChild(el);
  n.fil.scrollTop = n.fil.scrollHeight;
  return { el, etat };
}

function marquerEnvoye(e) {
  e.etat.textContent = "envoyé";
  e.el.classList.add("optimistic-echo");
}

// ---------------------------------------------------------------- dépôt d'ancrage

function projetParDefaut() {
  const memo = lireMemoire(MEMOIRE_PROJET);
  if (memo && state.projets.some((p) => p.slug === memo)) return memo;
  if (state.projets.some((p) => p.slug === "bouzecode")) return "bouzecode";
  return state.projets.length === 1 ? state.projets[0].slug : "";
}

/** L'assistant a besoin d'un dépôt pour démarrer : on le fait choisir, puis on renvoie le message. */
function demanderProjet(texte, suggestions) {
  const liste = suggestions && suggestions.length ? suggestions : state.projets;
  const bloc = h("div", { class: "bz-assist__projets", role: "group", "aria-label": "Choisir un dépôt" },
    h("p", null, liste.length ? "Sur quel dépôt l'assistant doit-il s'ancrer ? (il en a besoin pour démarrer)"
      : "Aucun dépôt enregistré : ajoute-en un depuis la page Agents (Gérer les dépôts), puis réessaie."));
  for (const p of liste) {
    const b = h("button", { type: "button", class: "btn btn--sm" }, p.name || p.slug);
    b.addEventListener("click", () => {
      ecrireMemoire(MEMOIRE_PROJET, p.slug);
      bloc.remove();
      envoyer(texte, p.slug);
    });
    bloc.appendChild(b);
  }
  //  Une seule question à la fois : réappuyer sur Entrée la REMPLACE au lieu d'en empiler une autre.
  n.fil.querySelectorAll(".bz-assist__projets").forEach((el) => el.remove());
  n.fil.appendChild(bloc);
  n.fil.scrollTop = n.fil.scrollHeight;
  (bloc.querySelector("button") || n.input).focus();
}

function redemanderProjet(e, texte, suggestions) {
  e.el.remove();
  demanderProjet(texte, suggestions);
  n.input.value = texte;
  statut("");
}

// ---------------------------------------------------------------- envoi

/** Titre du ticket (obligatoire, ≤ 200) : la première ligne non vide du message. */
function titreDe(texte) {
  return ((texte || "").split(/\r?\n/).map((l) => l.trim()).find(Boolean) || "Assistant du Bureau").slice(0, 80);
}

/** Premier message : ouvre la conversation (le message EST le prompt de l'assistant). */
async function ouvrirConversation(e, texte, projetChoisi) {
  const slug = projetChoisi || projetParDefaut();
  if (!slug) { redemanderProjet(e, texte); return; }
  statut("Ouverture de la conversation…");
  let r;
  try {
    r = await api("POST", `/api/projects/${encodeURIComponent(slug)}/tickets`, { title: titreDe(texte),
      prompt: texte, typology: TYPOLOGIE, isolation: "shared", launch: true, defer: false }, { timeout: 90000 });
  } catch (err) {
    if (!["depot_requis", "depot_inconnu", "projet_inconnu"].includes(err.code)) throw err;
    ecrireMemoire(MEMOIRE_PROJET, null);
    const details = err.data && err.data.error && err.data.error.details;
    redemanderProjet(e, texte, details && details.suggestions);
    return;
  }
  if (!r || !r.key) throw new Error("le serveur n'a pas renvoyé de conversation.");
  marquerEnvoye(e);
  reprendre(r.key, r.ticket_id || "");
  n.fil.prepend(e.el);
  chargerHistorique();
}

/** L'assistant travaille : le message attend, lu à sa prochaine étape ; « Annuler » le remet dans le champ. */
function mettreEnFile(e, texte, queueId) {
  e.etat.textContent = "en attente — l'assistant le lira à sa prochaine étape ";
  e.el.classList.add("bz-echo--attente");
  e.el.dataset.queueId = queueId;
  const annuler = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, "Annuler");
  annuler.addEventListener("click", () => busy(annuler, "Annulation…", async () => {
    try {
      await api("DELETE", `/api/agents/${encodeURIComponent(agentId())}/queue/${encodeURIComponent(queueId)}`);
      e.el.remove();
      n.input.value = n.input.value || texte;
      toast.info("Message retiré (remis dans le champ).");
    } catch (err) { toast.err(`Annulation impossible (déjà lu par l'assistant ?) : ${err.message}`); }
  }));
  e.etat.appendChild(annuler);
}

async function parler(e, texte) {
  const r = await api("POST", `/api/agents/${encodeURIComponent(agentId())}/messages`, { text: texte, mode: "queue" }, { okField: true });
  if (r && r.queued) mettreEnFile(e, texte, r.queue_id);
  else marquerEnvoye(e);
  reveillerFil();
}

/** Coupe le tour en cours (bouton « Interrompre », Échap) : l'assistant garde ce qu'il a déjà
 *  obtenu et repart aussitôt avec les messages en attente, s'il y en a. */
export async function interrompre() {
  if (!conv.key || !n.stop || n.stop.getAttribute("aria-busy") === "true") return;
  const attente = n.fil.querySelectorAll(".bz-echo[data-queue-id]").length;
  await busy(n.stop, "Interruption…", async () => {
    try {
      const r = await api("POST", `/api/agents/${encodeURIComponent(agentId())}/interruptions`, {}, { okField: true, timeout: 20000 });
      statut(attente ? "Interrompu : l'assistant repart avec ton message." : "Interrompu.");
      toast.info(r && r.escalated ? "Assistant arrêté net (il ne répondait pas) : ta prochaine demande le relance."
        : (attente ? "Assistant interrompu : il repart avec ton message." : "Assistant interrompu."));
    } catch (err) { toast.err(`Interruption impossible : ${err.message}`); }
  });
  reveillerFil();
}

/** Envoie `texte` : écho immédiat et champ vidé AU MÊME INSTANT (verrouillé le temps de l'envoi) ;
 *  en échec, l'écho le dit et le texte revient. Vider au retour du serveur laissait le texte dans
 *  le champ pendant toute l'ouverture / la relance de l'assistant (TODO 2026-09-25 §1). */
export async function envoyer(texte, projetChoisi) {
  if (!texte || conv.envoiEnCours) return;
  conv.envoiEnCours = true;
  n.input.readOnly = true;
  const e = echo(texte);
  n.input.value = "";
  try {
    await busy(n.send, "Envoi…", () => (conv.key ? parler(e, texte) : ouvrirConversation(e, texte, projetChoisi)));
  } catch (err) {
    e.el.classList.add("bz-echo--ko");
    e.etat.textContent = `non envoyé : ${err.message}`;
    n.input.value = texte;
    statut("");
  } finally {
    conv.envoiEnCours = false;
    n.input.readOnly = false;
    // Prêt pour le message suivant — sauf si le choix d'un dépôt vient de prendre le focus.
    if (!n.fil.querySelector(".bz-assist__projets")) n.input.focus();
  }
}
