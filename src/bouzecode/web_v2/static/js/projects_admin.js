// [desc] Dialogue « Gérer les dépôts » : lister les dépôts enregistrés, en ajouter un (aussitôt sélectionnable), modifier leur description, en retirer un, et ne plus écarter un dossier déclaré « pas un projet ». [/desc]

import { api, busy, toast, confirm as askConfirm, h, highlight } from "./lib/ui.js";

let dlg = null;

function field(label, attrs) {
  const input = h("input", { class: "input", type: "text", ...attrs });
  return { input, el: h("label", { class: "field" }, h("span", { class: "field__label" }, label), input) };
}

/** Une ligne de dépôt : description modifiable (Enregistrer actif seulement si elle a changé), Retirer. */
function repoRow(p, opts, listEl) {
  const desc = h("input", { class: "input", type: "text", value: p.description || "", maxlength: "200",
    "aria-label": `Description de ${p.name}`, placeholder: "Description (affichée dans le choix du dépôt)" });
  const save = h("button", { type: "button", class: "btn btn--sm", disabled: true }, "Enregistrer");
  const remove = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, "Retirer");
  const unchanged = () => desc.value.trim() === (p.description || "");
  desc.addEventListener("input", () => { save.disabled = unchanged(); });
  desc.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (!save.disabled) save.click(); } });
  save.addEventListener("click", () => busy(save, "Enregistrement…", async () => {
    try {
      await api("PATCH", `/api/projects/${encodeURIComponent(p.slug)}`, { description: desc.value.trim() });
      p.description = desc.value.trim();
      toast.ok(`Description de « ${p.name} » enregistrée.`);
      await opts.onChange?.();
    } catch (err) { toast.err(`Enregistrement impossible : ${err.message}`); }
  }).then(() => { save.disabled = unchanged(); }));
  remove.addEventListener("click", () => removeRepo(p, opts, listEl, remove));
  return h("li", { class: "ag-repo", dataset: { slug: p.slug } },
    h("div", { class: "ag-repo__head" }, h("strong", {}, p.name), h("code", { class: "ag-repo__path" }, p.path || "")),
    h("div", { class: "ag-repo__edit" }, desc, save, remove));
}

async function removeRepo(p, opts, listEl, btn) {
  const ok = await askConfirm({ title: `Retirer « ${p.name} » ?`,
    text: "Le dépôt n'est plus proposé au lancement. Rien n'est supprimé sur le disque ; tu pourras le rajouter.",
    confirmLabel: "Retirer", danger: true });
  if (!ok) return;
  await busy(btn, "Retrait…", async () => {
    try {
      await api("DELETE", `/api/projects/${encodeURIComponent(p.slug)}`);
      toast.ok(`« ${p.name} » retiré de la liste.`);
      await opts.onChange?.();
      await renderList(listEl, opts);
    } catch (err) { toast.err(`Retrait impossible : ${err.message}`); }
  });
}

function listError(listEl, err, retry) {
  const btn = h("button", { type: "button", class: "btn btn--sm" }, "Réessayer");
  btn.addEventListener("click", retry);
  listEl.replaceChildren(h("div", { class: "error-state error-state--inline", role: "alert" }, `Liste indisponible : ${err.message}`, btn));
}

async function renderList(listEl, opts, highlightSlug, added) {
  listEl.setAttribute("aria-busy", "true");
  let projects;
  try {
    projects = ((await api("GET", "/api/projects")).projects) || [];
  } catch (err) {
    listEl.removeAttribute("aria-busy");
    listError(listEl, err, () => renderList(listEl, opts, highlightSlug));
    return;
  }
  // La vue d'ensemble des dépôts peut être mémorisée côté serveur : un dépôt qu'on vient
  // d'ajouter peut y manquer. On l'ajoute nous-mêmes plutôt que de le cacher.
  if (added && added.slug && !projects.some((x) => x.slug === added.slug)) projects.push(added);
  listEl.removeAttribute("aria-busy");
  if (!projects.length) {
    listEl.replaceChildren(h("p", { class: "ag-muted" }, "Aucun dépôt enregistré pour l'instant : ajoute le premier ci-dessous."));
    return;
  }
  listEl.replaceChildren(h("ul", { class: "ag-repos__list" }, ...projects.map((p) => repoRow(p, opts, listEl))));
  if (highlightSlug) highlight(listEl.querySelector(`[data-slug="${CSS.escape(highlightSlug)}"]`));
}

async function renderDismissed(box) {
  let items = [];
  try {
    items = ((await api("GET", "/api/projects/dismissed")).dismissed) || [];
  } catch (err) {
    box.replaceChildren(h("p", { class: "field__error" }, `Dossiers écartés indisponibles : ${err.message}`));
    return;
  }
  if (!items.length) { box.replaceChildren(); return; }
  const rows = items.map((it) => {
    const undo = h("button", { type: "button", class: "btn btn--ghost btn--sm", title: "La question « est-ce un projet ? » pourra être reposée." }, "Ne plus écarter");
    undo.addEventListener("click", () => busy(undo, "…", async () => {
      try {
        await api("DELETE", "/api/projects/dismissed", { path: it.path });
        toast.ok(`« ${it.path} » n'est plus écarté.`);
        await renderDismissed(box);
      } catch (err) { toast.err(`Impossible : ${err.message}`); }
    }));
    return h("li", { class: "ag-repo" }, h("code", {}, it.path), it.reason ? h("span", { class: "ag-muted" }, ` — ${it.reason}`) : null, undo);
  });
  box.replaceChildren(h("details", {}, h("summary", {}, `Dossiers déclarés « pas un projet » (${items.length})`), h("ul", { class: "ag-repos__list" }, ...rows)));
}

/**
 * Ouvre le dialogue. `onChange` : rappelé après chaque modification (rechargement des dépôts
 * dans le sélecteur) ; `onAdded(slug)` : le dépôt ajouté devient le dépôt choisi.
 */
export function openReposDialog(opts = {}) {
  if (dlg) dlg.remove();
  const listEl = h("div", { class: "ag-repos__listwrap" }, h("p", { class: "ag-muted", role: "status" }, "Chargement des dépôts…"));
  const name = field("Nom", { placeholder: "ex. mon-api", autocomplete: "off" });
  const path = field("Chemin absolu du dépôt", { placeholder: "/home/moi/projets/mon-api", autocomplete: "off" });
  const desc = field("Description (optionnelle)", { maxlength: "200", autocomplete: "off" });
  const err = h("div", { class: "field__error", role: "alert" });
  const add = h("button", { type: "submit", class: "btn btn--primary" }, "Ajouter");
  const form = h("form", { class: "ag-repos__add", novalidate: true },
    h("h3", {}, "Ajouter un dépôt"), name.el, path.el, desc.el, err, h("div", { class: "btn-row" }, add));
  const dismissed = h("div", { class: "ag-repos__dismissed" });
  const close = h("button", { type: "button", class: "btn" }, "Fermer");
  dlg = h("dialog", { class: "ui-dialog ag-repos", "aria-labelledby": "ag-repos-title" },
    h("div", { class: "ui-dialog__body" },
      h("h2", { class: "ui-dialog__title", id: "ag-repos-title" }, "Dépôts"),
      listEl, form, dismissed),
    h("div", { class: "ui-dialog__actions" }, close));
  document.body.appendChild(dlg);
  const done = () => { if (dlg) { try { dlg.close(); } catch (e) { console.warn(e); } dlg.remove(); dlg = null; } };
  close.addEventListener("click", done);
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(); });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    err.textContent = "";
    if (!name.input.value.trim() || !path.input.value.trim()) {
      err.textContent = "Le nom et le chemin sont tous les deux requis.";
      (name.input.value.trim() ? path.input : name.input).focus();
      return;
    }
    busy(add, "Ajout…", async () => {
      try {
        const res = await api("POST", "/api/projects", {
          name: name.input.value.trim(), path: path.input.value.trim(), description: desc.input.value.trim() });
        const slug = (res && (res.slug || (res.project && res.project.slug))) || "";
        toast.ok(`Dépôt « ${name.input.value.trim()} » ajouté${slug ? " et sélectionné" : ""}.`);
        name.input.value = path.input.value = desc.input.value = "";
        await opts.onChange?.();
        if (slug) opts.onAdded?.(slug, res);
        await renderList(listEl, opts, slug, res);
      } catch (e2) {
        err.textContent = e2.message;
      }
    });
  });
  if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  name.input.focus();
  renderList(listEl, opts);
  renderDismissed(dismissed);
  return dlg;
}
