// [desc] Gestes d'une tâche (SPEC §4.2, §4.6) : ceux de la bande « ce qui t'attend » par motif (répondre, noter une décision, corriger et relancer, continuer, valider et clore, renvoyer, intégrer) et ceux du détail par statut (lancer, arrêter, consigne, rouvrir), plus le menu ⋯. [/desc]

import { h, busy, toast, confirm as demander, api, menu } from "../lib/ui.js";
import { ouvrirLancement } from "./lancer.js";
import { deplacerVers } from "./deplacer.js";
import * as act from "./actions.js";
import { marquerReprise } from "./store.js";
import { ouvrirZoneMessage } from "./zone_message.js";
import { entreesClassement } from "./classer.js";

const AIDE_CONTINUER = "Même agent, même conversation : il reprend là où il s'est arrêté.";
const AIDE_RELANCER = "Nouvel agent, environnement préparé à neuf (≈ 30 à 60 s), avec le récap des passages précédents.";

/** Bouton de geste : occupé pendant l'appel (sauf s'il ouvre un dialogue), erreur en toast. */
export function geste(label, cls, fn, attrs = {}, { dialogue = false } = {}) {
  const b = h("button", { type: "button", class: `btn btn--sm ${cls || ""}`, ...attrs }, label);
  const agir = async () => {
    try { await fn(b); } catch (e) { if (e && e.message !== "titre vide") toast.err(`${label} : ${e.message}`); }
  };
  // Un geste qui OUVRE un dialogue n'est pas « en cours » : c'est le dialogue qui porte le signal.
  b.addEventListener("click", () => (dialogue ? agir() : busy(b, null, agir)));
  return b;
}

async function classer(rec, etat, msg) {
  await act.classerTache(rec.id, etat, msg.replace(/\.$/, ""));
}

async function abandonner(rec) {
  if (rec.t.agent_actif) {
    const ok = await demander({ title: "Abandonner la tâche ?", danger: true, confirmLabel: "Arrêter et abandonner",
      text: "Un agent travaille encore dessus : il sera arrêté. L'historique est conservé ; tu pourras rouvrir la tâche." });
    if (!ok) return;
  }
  await classer(rec, "abandonnee", "Tâche abandonnée.");
}

async function arreter(rec) {
  const ok = await demander({ title: "Arrêter l'agent ?", danger: true, confirmLabel: "Arrêter",
    text: "Il s'arrête tout de suite, sans finir son tour. Tu pourras le faire continuer ou relancer la tâche." });
  if (!ok) return;
  await act.arreterTache(rec.id);
  toast.ok("Agent arrêté.");
  await act.rafraichir();
}

/** « Continuer » : même agent, même conversation, avec un message optionnel joint à la reprise. */
function continuer(rec) {
  const dernier = (rec.t.passages || [])[0];
  ouvrirZoneMessage(rec.el, rec.zoneGestes, {
    aria: "Message pour l'agent (optionnel)", bouton: "Continuer", occupe: "Reprise…",
    placeholder: "Message pour l'agent (optionnel) — ex. « le test X échoue encore, regarde Y »…",
    envoyer: async (text) => {
      let r;
      try { r = await act.relancerTache(rec.id, { mode: "continuer", retour: text }); } catch (e) {
        throw new Error(`Reprise impossible : ${e.message}`);
      }
      act.toastAgent(r.queued ? "L'agent travaille encore : ton message est en file."
        : "L'agent reprend là où il s'était arrêté.", r.agent_id || (dernier && dernier.agent_id));
      marquerReprise(rec.id);
      await act.rafraichir();
    },
  });
}

/** Ce que devient une consigne, dit en une ligne (R2). */
function annonceConsigne(r) {
  const t = ((r && r.transmis) || [])[0];
  if (!t) return "Consigne ajoutée au brief (aucun agent en cours à qui la transmettre).";
  if (!t.ok) return `Consigne ajoutée au brief, mais pas transmise : ${t.error || "agent injoignable"}.`;
  return t.en_tour ? "Consigne ajoutée au brief — l'agent la lira à sa prochaine étape."
    : "Consigne ajoutée au brief et envoyée à l'agent.";
}

/** Champ « consigne » sous les gestes : ajoutée au brief (Précisions ajoutées) ET transmise à
 *  l'agent, qui la lit à sa prochaine étape ; la ligne montre ensuite si elle a été lue. */
function consigne(rec) {
  const p = (rec.t.passages || [])[0];
  if (!p || !p.agent_id) { toast.info("L'agent démarre encore : réessaie dans quelques secondes."); return; }
  ouvrirZoneMessage(rec.corps, rec.zoneActions, {
    aria: "Consigne pour l'agent", bouton: "Envoyer", occupe: "Envoi…", obligatoire: "Écris la consigne.",
    placeholder: "Une consigne pour l'agent (ajoutée au brief, lue à sa prochaine étape)…",
    envoyer: async (texte) => {
      let r;
      try {
        r = await api("POST", `/api/micros/${encodeURIComponent(rec.t.id)}/precisions`, { texte, transmettre: true });
      } catch (e) { throw new Error(`Consigne non transmise : ${e.message}`); }
      const t = ((r && r.transmis) || [])[0];
      (t && !t.ok ? toast.err : toast.ok)(annonceConsigne(r));
      await act.rafraichir();
    },
  });
}

/** Tant que l'agent n'a pas démarré (lancement en fond), il n'a pas d'adresse : le geste est
 *  visible mais désactivé, et le dit — jamais un bouton qui ne fait rien. */
function gesteConsigne(rec) {
  const pret = Boolean(((rec.t.passages || [])[0] || {}).agent_id);
  return geste("Ajouter une consigne…", "", async () => consigne(rec),
    pret ? {} : { disabled: true, title: "Disponible dès que l'agent a démarré (quelques secondes)." });
}

const relancerAvecRetour = (rec) => ouvrirLancement(rec.t, { mode: "relancer", avant: rec.sauver });
const relancerNeuf = (rec) => ouvrirLancement(rec.t, { mode: "lancer", avant: rec.sauver });
const gesteAbandonner = (rec) => geste("Abandonner", "btn--ghost", () => abandonner(rec));

/** Une décision laissée par un agent : on NOTE ce qu'on a décidé (précision du brief) et la
 *  tâche est close ; « Annuler » la rouvre. */
function noterDecision(rec) {
  ouvrirZoneMessage(rec.el, rec.zoneGestes, {
    aria: "Ta décision", bouton: "Noter et clore", occupe: "Enregistrement…", obligatoire: "Écris ta décision.",
    placeholder: "Ta décision (elle est ajoutée au brief de la tâche, qui est close)…",
    envoyer: async (text) => {
      try { await act.classerTache(rec.id, "faite", "Décision notée — tâche close", `Décision : ${text}`); } catch (e) {
        throw new Error(`Décision non enregistrée : ${e.message}`);
      }
    },
  });
}

function gesteIntegrer(rec) {
  const p = (rec.t.passages || [])[0];
  if (!p || !p.integrable || p.integre !== false) return null;
  return geste("Intégrer", "", async () => {
    const res = await act.integrerPassage(rec.id, p.ticket_id);
    toast.ok(act.messageIntegration(res));
    await act.rafraichir();
  }, { title: `Fusionne ${p.branche || "la branche de l'agent"} dans la branche de base du dépôt.` });
}

const verifier = (rec, lien) => [
  geste("Valider et clore", "btn--primary", () => classer(rec, "faite", "Tâche validée et close."),
    { title: "Le travail te convient : la tâche est classée faite (Annuler possible)." }),
  geste("Renvoyer avec un retour…", "", () => relancerAvecRetour(rec), { title: "Dis ce qui ne va pas : l'agent (ou un nouvel agent) refait un passage." },
    { dialogue: true }),
  gesteIntegrer(rec),
  geste("Voir le travail", "btn--ghost", async () => rec.deplier(".bz-passage"), {}, { dialogue: true }),
  lien,
];

const reprendre = (rec, lien) => [
  rec.t.joignable ? geste("Continuer…", "btn--primary", () => continuer(rec), { title: AIDE_CONTINUER }, { dialogue: true }) : null,
  geste("Relancer", rec.t.joignable ? "" : "btn--primary", () => relancerNeuf(rec), { title: AIDE_RELANCER },
    { dialogue: true }),
  lien, gesteAbandonner(rec),
];

/** Gestes de la bande « ce qui t'attend », par motif (attention.js) : l'action attendue en tête. */
const PAR_MOTIF = {
  // Question et plan : le bloc de réponse est dans la bande ; restent les gestes secondaires.
  question: (rec, lien) => [lien, geste("Arrêter", "btn--ghost", () => arreter(rec))],
  plan: (rec, lien) => [lien, geste("Arrêter", "btn--ghost", () => arreter(rec))],
  point: (rec) => [
    geste("Noter ma décision…", "btn--primary", async () => noterDecision(rec), {}, { dialogue: true }),
    geste("Confier à un agent…", "", () => rec.lancer(), { title: "Lance un agent sur ce point, avec son brief." }, { dialogue: true }),
    gesteAbandonner(rec),
  ],
  lancement: (rec, lien) => [
    geste("Corriger et relancer…", "btn--primary", () => relancerNeuf(rec),
      { title: "Choisis un autre dépôt ou un autre environnement, puis relance." }, { dialogue: true }),
    lien, gesteAbandonner(rec),
  ],
  plante: reprendre,
  arrete: reprendre,
  introuvable: reprendre,
  livraison: verifier,
};

/** Gestes d'une tâche qui n'attend rien de toi, par statut. */
const PAR_STATUT = {
  brouillon: (rec) => [
    geste("Lancer", "btn--primary", (b) => rec.lancer(b), {}, { dialogue: true }),
    gesteAbandonner(rec),
  ],
  en_cours: (rec, lien) => [lien, geste("Arrêter", "btn--danger", () => arreter(rec)), gesteConsigne(rec)],
  faite: (rec) => [geste("Rouvrir", "", () => act.rouvrirTache(rec.id))],
  abandonnee: (rec) => [geste("Rouvrir", "", () => act.rouvrirTache(rec.id))],
};

/** Menu ⋯ de la tâche : ce qui sert rarement, invisible tant qu'on ne l'ouvre pas.
 *  « Déplacer vers… » est l'alternative clavier au glisser-déposer ; « Marquer faite… »,
 *  « Doublon de… », « Caduque… » classent une tâche ouverte sans la lancer (SPEC §4.6). */
function menuTache(rec) {
  const b = h("button", { type: "button", class: "btn btn--ghost btn--sm btn--icon bz-task__menu",
    "aria-label": "Autres actions sur la tâche" }, "⋯");
  const wrap = h("span", { class: "menu bz-task__plus" }, b);
  menu(b, () => [{ label: "Déplacer vers…", fn: () => deplacerVers(rec) }, ...entreesClassement(rec.t),
    ...entreesSignalement(rec)], { align: "right" });
  return wrap;
}

/** Les signalements qu'un humain émet sur une tâche, comme l'outil Signaler d'un agent :
 *  la 1re ligne est le titre, le reste le détail ; il apparaît dans « Ce qui t'attend ». */
const GRAVITES_SIGNALEMENT = [
  ["info", "Signaler une info…"], ["alerte", "Signaler une alerte…"], ["bloquant", "Signaler un blocage…"],
];

function entreesSignalement(rec) {
  return GRAVITES_SIGNALEMENT.map(([gravite, label]) => ({ label, fn: () => signaler(rec, gravite) }));
}

function signaler(rec, gravite) {
  const p = (rec.t.passages || [])[0];
  ouvrirZoneMessage(rec.corps, rec.zoneActions, {
    aria: "Signalement", bouton: "Signaler", occupe: "Envoi…", obligatoire: "Écris le signalement.",
    placeholder: "Titre du signalement (1re ligne), puis le détail…",
    envoyer: async (texte) => {
      const [titre, ...reste] = texte.split("\n");
      await act.creerSignalement({
        gravite, titre: titre.trim(), detail: reste.join("\n").trim(), micro_id: rec.t.id,
        ticket_slug: (p && p.slug) || rec.t.projet_slug || "", ticket_id: (p && p.ticket_id) || "",
      });
      toast.ok("Signalement émis : il apparaît dans « Ce qui t'attend ».");
      await act.rafraichir();
    },
  });
}

function lienAgent(rec) {
  const dernier = (rec.t.passages || [])[0];
  return dernier && dernier.agent_id
    ? h("a", { class: "btn btn--sm btn--ghost", href: act.lienAgent(dernier.agent_id) }, "Voir l'agent") : null;
}

/** Les gestes de la bande « ce qui t'attend » d'une tâche (motif non vide). */
export function gestesAttente(rec, motif) {
  const fabrique = PAR_MOTIF[motif];
  return fabrique ? fabrique(rec, lienAgent(rec)).filter(Boolean) : [];
}

/** La barre d'actions du détail : les gestes du statut — sauf si la tâche t'attend (ils sont
 *  alors dans la bande, en tête de la tâche) — puis le menu ⋯. */
export function gestes(rec, motif) {
  const fabrique = motif ? null : PAR_STATUT[rec.t.statut_ui];
  return [...(fabrique ? fabrique(rec, lienAgent(rec)).filter(Boolean) : []), menuTache(rec)];
}
