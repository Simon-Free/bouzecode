// [desc] Profils : tiroir « Bibliothèque » (onglets Skills / Plugins) — ouverture avec chargement des deux listes. [/desc]
import { openDrawer } from "./drawer.js";
import { loadSkills } from "./library_skills.js";
import { loadPlugins } from "./library_plugins.js";

const $ = (id) => document.getElementById(id);
const ONGLETS = [["pf-lib-tab-skills", "pf-lib-skills"], ["pf-lib-tab-plugins", "pf-lib-plugins"]];

export function openLibrary() {
  openDrawer("pf-library", () => { loadSkills(); loadPlugins(); });
}

function montrerOnglet(tabId) {
  for (const [t, p] of ONGLETS) {
    const on = t === tabId;
    $(t).setAttribute("aria-selected", String(on));
    $(p).hidden = !on;
  }
}

export function wireLibraryTabs() {
  for (const [tabId] of ONGLETS) $(tabId).addEventListener("click", () => montrerOnglet(tabId));
}
