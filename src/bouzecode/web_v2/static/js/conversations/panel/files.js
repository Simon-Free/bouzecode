// [desc] Vue Fichiers modifiés du panneau d'un agent : un diff côte à côte par fichier, compteur, Actualiser ; squelette, état vide, erreur avec Réessayer. [/desc]

import { api, h, skeleton, failed, empty } from "../../lib/ui.js";
import { renderDiffBlock } from "./diff.js";
import { refreshButton } from "./view_tools.js";

function countLabel(n) {
  return n ? `${n} fichier${n > 1 ? "s" : ""} modifié${n > 1 ? "s" : ""}` : "";
}

export function createFilesView(entry, pane) {
  const tools = h("div", { class: "ag-view__tools" });
  const body = h("div", { class: "ag-view__body ag-files" });
  pane.append(tools, body);
  let loaded = false;

  async function load() {
    skeleton(body, 5);
    try {
      const data = await api("GET", `/api/sessions/${entry.key}/files?raw=1`, undefined, { timeout: 60000 });
      const files = (data && data.files) || [];
      loaded = true;
      tools.replaceChildren(h("span", { class: "ag-muted" }, countLabel(files.length)), refreshButton("Actualiser", load));
      if (!files.length) { empty(body, { title: "Aucun fichier modifié par cet agent." }); return; }
      body.replaceChildren();
      body.removeAttribute("aria-busy");
      for (const f of files) {
        renderDiffBlock(body, { file: f.path, patch: "", original: f.before || "", modified: f.after || "",
          is_new: !!f.is_new, stats: { added: Number(f.added) || 0 } });
      }
    } catch (err) {
      failed(body, err, load, { title: "Impossible de charger les fichiers modifiés." });
    }
  }
  return {
    show() { if (!loaded) load(); },
    maybeRefresh() {},
  };
}
