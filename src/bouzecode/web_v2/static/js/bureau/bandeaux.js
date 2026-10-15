// [desc] Bandeau du Bureau : réponses qui n'ont pas atteint leur agent (avec « Renvoyer », progression i/N). [/desc]
//
// Le bandeau du lien Teams a été retiré (2026-09-29) : le pont de chat Teams n'existe plus et
// /api/board ne porte plus de clé `teams` — le bandeau restait caché à vie.

import { api, busy, toast } from "../lib/ui.js";

// ---------------------------------------------------------------- réponses non livrées

function idsEnEchec(d) {
  const items = (d && (d.failed || d.decisions || d.items)) || (Array.isArray(d) ? d : []);
  return items.map((x) => x.id || x.decision_id).filter(Boolean);
}

export async function majLivraison() {
  const banner = document.getElementById("delivery-banner");
  if (!banner) return;
  let d;
  try { d = await api("GET", "/api/decisions/failed", undefined, { timeout: 10000 }); } catch (_) { return; }
  const ids = idsEnEchec(d);
  banner.hidden = !ids.length;
  banner.dataset.ids = JSON.stringify(ids);
  document.getElementById("delivery-text").textContent = ids.length === 1
    ? "1 réponse n'a pas atteint son agent."
    : `${ids.length} réponses n'ont pas atteint leur agent.`;
}

async function renvoyerTout(bouton) {
  const ids = JSON.parse(document.getElementById("delivery-banner").dataset.ids || "[]");
  let ok = 0;
  const echecs = [];
  for (let i = 0; i < ids.length; i++) {
    bouton.textContent = `Renvoi ${i + 1}/${ids.length}…`;
    try { await api("POST", `/api/decisions/${encodeURIComponent(ids[i])}/retry`, {}, { okField: true }); ok += 1; }
    catch (e) { echecs.push(e.message); }
  }
  if (ok) toast.ok(`${ok} réponse(s) renvoyée(s).`);
  if (echecs.length) toast.err(`${echecs.length} renvoi(s) en échec : ${echecs[0]}`);
  await majLivraison();
}

export function wireLivraison() {
  const bouton = document.getElementById("delivery-retry-all");
  if (bouton) bouton.addEventListener("click", () => busy(bouton, "Renvoi…", () => renvoyerTout(bouton)));
}
