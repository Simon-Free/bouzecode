// [desc] Renders a "Fichiers livrés" list of delivered files, each with an Open button that calls the API. [/desc]

import { h, api, toast } from "./ui.js";

const nomDe = (path) => String(path || "").split(/[\\/]/).filter(Boolean).pop() || String(path || "");

/** `files` = [{path, label?, kind?, name?, exists?}] ; `livraison` = {session_id} ou {micro_id}. */
export function fichiersLivres(files, livraison) {
  const liste = Array.isArray(files) ? files.filter((f) => f && f.path) : [];
  if (!liste.length) return null;
  const items = liste.map((f) => {
    const ouvrir = h("button", { type: "button", class: "btn btn--ghost btn--sm", "data-fichiers": "ouvrir" }, "Ouvrir");
    ouvrir.addEventListener("click", async () => {
      try {
        await api("POST", "/api/fichiers/ouvrir", { path: f.path, ...livraison });
        toast.ok(`Ouverture de ${nomDe(f.path)}`);
      } catch (e) {
        toast.err(e?.message || "Ouverture impossible");
      }
    });
    const etat = f.exists === undefined ? null
      : h("span", { class: f.exists ? "ag-muted" : "ag-muted ag-fichier--absent", "data-fichiers": "etat" },
        f.exists ? "existe" : "absent");
    return h("li", { class: "ag-fichier", "data-fichiers": "item" },
      h("strong", {}, f.label || f.name || nomDe(f.path)), " ",
      h("code", {}, f.path), " ", etat, f.kind ? ` (${f.kind})` : "", " ", ouvrir);
  });
  return h("section", { class: "ag-recap__section", "data-fichiers": "section" },
    h("h3", {}, "Fichiers livrés"), h("ul", { class: "ag-recap__fichiers" }, ...items));
}
