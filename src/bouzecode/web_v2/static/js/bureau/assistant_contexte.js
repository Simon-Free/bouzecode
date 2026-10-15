// [desc] Réglage « Contexte perso » de l'assistant (⚙) : texte libre ajouté au début de chaque nouvelle conversation, chargé à la première ouverture, enregistré explicitement. [/desc]

import { api, busy, toast, dirty } from "../lib/ui.js";

const PLACEHOLDER = "Ce que l'assistant ne peut pas deviner : ton équipe, tes projets, tes habitudes…";

async function charger(zone, d) {
  zone.disabled = true;
  zone.placeholder = "Chargement…";
  try {
    const r = await api("GET", "/api/bureau/assistant/contexte");
    zone.value = (r && r.contenu) || "";
    d.markClean();
    return true;
  } catch (e) {
    toast.err(`Contexte perso illisible : ${e.message}`);
    return false;
  } finally {
    zone.disabled = false;
    zone.placeholder = PLACEHOLDER;
  }
}

async function enregistrer(zone, d) {
  try {
    const r = await api("PUT", "/api/bureau/assistant/contexte", { contenu: zone.value });
    if (r && typeof r.contenu === "string") zone.value = r.contenu;
    d.markClean();
    toast.ok("Contexte enregistré — pris en compte à la prochaine conversation.");
  } catch (e) { toast.err(`Enregistrement du contexte impossible : ${e.message}`); }
}

export function wireContexte() {
  const bloc = document.getElementById("assistant-contexte-bloc");
  const bouton = document.getElementById("assistant-reglages");
  const zone = document.getElementById("assistant-contexte");
  const save = document.getElementById("assistant-contexte-save");
  if (!bloc || !bouton) return;
  const d = dirty(bloc, { flag: document.getElementById("assistant-contexte-flag") });
  let charge = false;
  bouton.addEventListener("click", async () => {
    const ouvrir = bloc.hidden;
    if (!ouvrir && !(await d.guard())) return;
    bloc.hidden = !ouvrir;
    bouton.setAttribute("aria-expanded", ouvrir ? "true" : "false");
    if (!ouvrir) return;
    if (!charge) charge = await charger(zone, d);
    zone.focus();
  });
  save.addEventListener("click", () => busy(save, "Enregistrement…", () => enregistrer(zone, d)));
}
