// [desc] Tiroir Assistant du Bureau (SPEC §4.10) : ouverture / fermeture (bouton, Ctrl+J, Échap), câblage de l'historique, du formulaire d'envoi et du contexte perso. [/desc]
//
// La conversation elle-même vit dans assistant_fil.js, l'envoi dans assistant_envoi.js,
// le réglage « Contexte perso » dans assistant_contexte.js.

import { n, conv, statut, chargerHistorique, reprendre, nouvelle, restaurer } from "./assistant_fil.js";
import { envoyer, interrompre } from "./assistant_envoi.js";
import { wireContexte } from "./assistant_contexte.js";

function ouvert() { return n.drawer.dataset.open === "true"; }

export function ouvrirTiroir(open) {
  n.drawer.dataset.open = open ? "true" : "false";
  n.drawer.setAttribute("aria-hidden", open ? "false" : "true");
  if ("inert" in n.drawer) n.drawer.inert = !open;
  n.bulle.setAttribute("aria-expanded", open ? "true" : "false");
  document.body.classList.toggle("bz-drawer-open", open);
  if (open) {
    n.input.focus();
    chargerHistorique();
  } else if (n.drawer.contains(document.activeElement)) {
    n.bulle.focus();
  }
}

/** Échap interrompt l'assistant qui travaille (comme dans Claude Code), sinon ferme le tiroir —
 *  sauf si un dialogue ou un menu est ouvert (c'est lui qui se ferme). */
function surTouche(e) {
  if ((e.ctrlKey || e.metaKey) && (e.key === "j" || e.key === "J")) { e.preventDefault(); ouvrirTiroir(!ouvert()); return; }
  const autreCouche = document.querySelector("dialog[open]") || document.querySelector(".menu__list");
  if (e.key !== "Escape" || !ouvert() || autreCouche) return;
  if (n.stop && !n.stop.hidden) { e.preventDefault(); interrompre(); return; }
  ouvrirTiroir(false);
}

function choisirDansHistorique() {
  if (!n.hist.value) { if (conv.key) nouvelle(); return; }
  const opt = n.hist.selectedOptions[0];
  reprendre(n.hist.value, opt ? opt.dataset.ticket || "" : "");
  statut("Conversation reprise : ton prochain message la continue.");
}

export function wireAssistant() {
  Object.assign(n, {
    drawer: document.getElementById("assistant-drawer"),
    bulle: document.getElementById("assistant-bulle"),
    fermer: document.getElementById("assistant-fermer"),
    hist: document.getElementById("assistant-historique"),
    nouvelle: document.getElementById("assistant-nouvelle"),
    fil: document.getElementById("assistant-messages"),
    statut: document.getElementById("assistant-status"),
    form: document.getElementById("assistant-form"),
    input: document.getElementById("assistant-input"),
    send: document.getElementById("assistant-send"),
    stop: document.getElementById("assistant-stop"),
  });
  if (!n.drawer) return;
  if ("inert" in n.drawer) n.drawer.inert = true;
  n.bulle.addEventListener("click", () => ouvrirTiroir(!ouvert()));
  n.fermer.addEventListener("click", () => ouvrirTiroir(false));
  document.addEventListener("keydown", surTouche);
  n.nouvelle.addEventListener("click", () => nouvelle());
  n.hist.addEventListener("change", choisirDansHistorique);
  n.form.addEventListener("submit", (e) => { e.preventDefault(); envoyer(n.input.value.trim()); });
  if (n.stop) n.stop.addEventListener("click", () => interrompre());
  n.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); envoyer(n.input.value.trim()); }
  });
  wireContexte();
  restaurer();
}
