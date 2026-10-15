// [desc] Historique des passages d'une tâche (SPEC §4.6) : un bloc par agent lancé, état en direct, récap, retour donné, liens et « Intégrer ». [/desc]

import { h, toast, relTime } from "../lib/ui.js";
import { agentState, badge } from "../lib/states.js";
import { nomProjet } from "./store.js";
import { blocRecap } from "./recap.js";
import { revelerTache } from "./reveler.js";
import { geste } from "./tache_gestes.js";
import * as act from "./actions.js";
import { fichiersRefuses } from "./lancer_execution.js";

function metaPassage(p) {
  const debut = relTime(p.started_at);
  return [
    debut && `lancé ${debut}`,
    p.slug && nomProjet(p.slug),
    p.branche && `branche ${p.branche}`,
    p.fichiers_modifies ? `${p.fichiers_modifies} fichier(s) modifié(s)` : "",
    p.integre === true ? "intégré" : "",
  ].filter(Boolean).join(" · ");
}

function gestesPassage(tacheId, p) {
  const out = [];
  if (p.agent_id) out.push(h("a", { class: "btn btn--ghost btn--sm", href: act.lienAgent(p.agent_id) }, "Ouvrir la conversation"));
  if (p.integrable && p.integre === false) {
    out.push(geste("Intégrer", "", async () => {
      const res = await act.integrerPassage(tacheId, p.ticket_id);
      toast.ok(act.messageIntegration(res));
      await act.rafraichir();
    }, { title: `Fusionne ${p.branche || "la branche de l'agent"} dans la branche de base du dépôt.` }));
  }
  if (p.integre === true) {
    out.push(geste("Demander un rollback", "", async () => {
      const res = await act.demanderRollback(tacheId, p.ticket_id);
      toast.ok(res.deja ? "Le rollback de ce passage est déjà demandé." : "Tâche de rollback créée.");
      await act.rafraichir();
    }, { title: "Crée une tâche qui annule (git revert) l'intégration de ce passage dans la branche de base." }));
  }
  return out;
}

/** Ce que le récap d'un passage peut faire : montrer la tâche d'un point, créer celle qui manque. */
function gestesRecap(tacheId, p) {
  return {
    montrer: revelerTache,
    creer: async (libelle, decision) => {
      const res = await act.creerSuite(tacheId, p.ticket_id, libelle, decision);
      toast.ok(res.deja ? "Ce point avait déjà sa tâche." : "Tâche créée.");
      await act.rafraichir();
      if (res.micro) revelerTache(res.micro.id);
    },
  };
}

/** Exécution Rundeck du passage : lien vers l'exécution, et les fichiers qui ne sont PAS partis. */
function blocDistant(p) {
  const d = p.distant;
  if (!d) return null;
  const quoi = d.mode === "tests" ? "tests" : "agent";
  const lien = d.url ? h("a", { href: d.url, target: "_blank", rel: "noopener" }, `exécution ${d.execution_id || "?"}`)
    : `exécution ${d.execution_id || "?"}`;
  const refuses = fichiersRefuses(d);
  return h("div", { class: "bz-passage__distant", "data-role": "distant" },
    h("p", { class: "bz-passage__act" }, `Rundeck (${quoi}) : `, lien),
    refuses.length ? h("p", { class: "bz-card__raison" }, `Fichiers non transmis : ${refuses.join(", ")}`) : null);
}

function rendrePassage(tacheId, p) {
  const etat = agentState(p.etat);
  if (p.libelle_etat) etat.label = p.libelle_etat;
  const gestes = gestesPassage(tacheId, p);
  return h("section", { class: "bz-passage", "data-ticket": p.ticket_id },
    h("header", { class: "bz-passage__head" }, h("span", { class: "bz-passage__num" }, `#${p.numero || ""}`), badge(etat),
      h("span", { class: "bz-muted" }, metaPassage(p))),
    p.retour ? h("p", { class: "bz-passage__retour" }, h("b", null, "Ton retour : "), p.retour) : null,
    p.distant ? blocDistant(p) : (p.activite ? h("p", { class: "bz-passage__act" }, p.activite) : null),
    p.raison_echec ? h("p", { class: "bz-card__raison" }, p.raison_echec) : null,
    blocRecap(p.recap, gestesRecap(tacheId, p)),
    gestes.length ? h("div", { class: "btn-row" }, gestes) : null);
}

/** Les éléments de la zone « passages » d'une tâche. */
export function rendrePassages(t) {
  const ps = t.passages || [];
  if (!ps.length) return [h("p", { class: "bz-muted bz-passages__vide" }, "Aucun agent lancé sur cette tâche pour l'instant.")];
  return [h("h3", { class: "bz-h3" }, ps.length > 1 ? `${ps.length} passages` : "Passage"),
    ...ps.map((p) => rendrePassage(t.id, p))];
}

/** Ce qui, s'il change, justifie de redessiner les passages. */
export function signaturePassages(t) {
  return JSON.stringify((t.passages || []).map((p) => [p.ticket_id, p.agent_id, p.etat, p.activite, p.recap, p.integre,
    p.integrable, p.fichiers_modifies, p.raison_echec, p.retour, p.finished_at, p.distant]));
}
