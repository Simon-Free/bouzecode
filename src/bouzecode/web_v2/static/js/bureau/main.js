// [desc] Point d'entrée du Bureau : chargement initial (squelette), poll /api/lignes + /api/inbox (5 s si un agent tourne ou qu'une question attend, 15 s sinon), câblage des modules. [/desc]

import { api, toast, skeleton, highlight } from "../lib/ui.js";
import { poller } from "../lib/poll.js";
import { state, agentsActifs, poserLignes } from "./store.js";
import { rendreListe, wireListe } from "./liste.js";
import { wireNouveauChantier } from "./chantier.js";
import { wireAssistant } from "./assistant.js";
import { majLivraison, wireLivraison } from "./bandeaux.js";
import { setRefresh } from "./actions.js";
import { horloge } from "./autosave.js";

let premier = true;

function toutRendre(erreurs = {}) {
  rendreListe(erreurs.lignes);
}

/** Une lecture en échec alors qu'on a déjà des données : on garde l'écran et on le dit (sauf réseau : bandeau global). */
function signalerEchec(erreurs) {
  const e = erreurs.lignes || erreurs.inbox;
  if (!e || !state.lignes || e.status === 0) return;
  // Au premier chargement, un échec de /api/lignes a déjà son état d'erreur dans la liste ;
  // un échec de /api/inbox seul ne se verrait pas (points d'attente absents) : on le dit.
  if (!premier) toast.err(`Rafraîchissement du Bureau impossible : ${e.message}`);
  else if (!erreurs.lignes) toast.err(`Ce qui t'attend n'a pas pu être chargé : ${e.message}`);
}

//  Les tâches DÉPLIÉES sont servies COMPLÈTES (`?detail=`) : sans ça, ce qu'on est en train
//  de lire (passages, récap) se figerait au premier dépli, puisque /api/lignes ne sert plus
//  que la liste. Bornées à 12 : au-delà, le détail se recharge au dépli (/api/lignes/<id>)
//  plutôt que d'alourdir CHAQUE poll (toutes les 5-15 s).
function paramDetail() {
  const ids = [...(state.deplies || [])].slice(0, 12);
  return ids.length ? `?detail=${encodeURIComponent(ids.join(","))}` : "";
}

async function charger() {
  //  Numéro pris AU DÉPART : le poll et le rafraîchissement direct après un geste se croisent ;
  //  une réponse plus ancienne que celle déjà posée est ignorée, et l'éditeur de brief sait si la
  //  lecture a pu voir son dernier enregistrement (autosave.depuisServeur).
  const no = horloge();
  const [lignes, inbox] = await Promise.allSettled([
    api("GET", `/api/lignes${paramDetail()}`, undefined, { timeout: 30000 }),
    api("GET", "/api/inbox", undefined, { timeout: 30000 }),
  ]);
  if (state.lueNo && no < state.lueNo) return state;
  state.lueNo = no;
  const erreurs = {};
  if (lignes.status === "fulfilled") poserLignes(lignes.value); else erreurs.lignes = lignes.reason;
  if (inbox.status === "fulfilled") state.inbox = inbox.value; else erreurs.inbox = inbox.reason;
  toutRendre(erreurs);
  signalerEchec(erreurs);
  premier = false;
  if (erreurs.lignes && erreurs.inbox) throw erreurs.lignes;
  return state;
}

async function chargerReferentiels() {
  const [p, t] = await Promise.allSettled([
    api("GET", "/api/projects", undefined, { timeout: 15000 }),
    api("GET", "/api/typologies", undefined, { timeout: 15000 }),
  ]);
  if (p.status === "fulfilled") state.projets = (p.value && p.value.projects) || [];
  else toast.err(`Liste des dépôts indisponible : ${p.reason.message}`);
  if (t.status === "fulfilled") state.profils = (t.value && t.value.typologies) || [];
}

/** Cadence rapide tant qu'un agent tourne ou qu'une question attend. */
function rapide() {
  return agentsActifs() || ((state.inbox && state.inbox.items) || []).some((x) => x.type === "question" || x.type === "plan");
}

/** Un chantier créé (mode Chantier) : surligné, prêt à recevoir sa 1re tâche. */
function montrerChantierCree(id) {
  const el = document.querySelector(`.bz-ch[data-chantier="${CSS.escape(id)}"]`);
  if (!el) return;
  highlight(el);
  const champ = el.querySelector(".bz-add__input");
  if (champ) champ.focus();
}

async function demarrer() {
  skeleton(document.getElementById("lignes-liste"), 6);
  const p = poller(charger, { interval: 15000, fastInterval: 5000, isFast: rapide });
  // Rafraîchissement DIRECT après un geste (pas via le poller) : l'appelant attend que les
  // nouvelles données soient rendues avant de surligner / focaliser le résultat (R3).
  setRefresh(() => charger().catch(() => {}));
  window.addEventListener("bz:render", () => toutRendre());
  wireListe();
  wireNouveauChantier(montrerChantierCree);
  wireAssistant();
  wireLivraison();
  await chargerReferentiels();
  p.start();
  //  Bandeau des décisions en échec : même poller que le reste, donc en pause onglet caché et
  //  rattrapé au retour — un setInterval le sondait sans fin en arrière-plan.
  poller(() => majLivraison(), { interval: 60000, fastInterval: 60000 }).start();
}

demarrer();

// Accroche de test / débogage : état courant du Bureau.
if (typeof window !== "undefined") window.__bureau = { state };
