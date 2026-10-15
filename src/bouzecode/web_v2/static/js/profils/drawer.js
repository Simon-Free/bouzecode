// [desc] Profils : tiroirs latéraux (catalogue, bibliothèque) — ouverture, Échap, focus rendu à l'origine. [/desc]

const openers = new Map();

/** Ouvre le tiroir `id` ; `onOpen` est appelé à chaque ouverture (chargement des données). */
export function openDrawer(id, onOpen) {
  const d = document.getElementById(id);
  if (!d) return;
  openers.set(id, document.activeElement);
  for (const other of document.querySelectorAll(".drawer[data-open='true']")) {
    if (other.id !== id) closeDrawer(other.id, false);
  }
  d.dataset.open = "true";
  d.setAttribute("aria-hidden", "false");
  d.removeAttribute("inert");
  const first = d.querySelector("[data-close]");
  if (first) first.focus();
  if (onOpen) onOpen();
}

export function closeDrawer(id, restoreFocus = true) {
  const d = document.getElementById(id);
  if (!d || d.dataset.open !== "true") return;
  d.dataset.open = "false";
  d.setAttribute("aria-hidden", "true");
  d.setAttribute("inert", "");
  const back = openers.get(id);
  openers.delete(id);
  if (restoreFocus && back && typeof back.focus === "function") back.focus();
}

export function isOpen(id) {
  const d = document.getElementById(id);
  return !!d && d.dataset.open === "true";
}

/** Câble les boutons [data-close] et Échap pour tous les tiroirs de la page. */
export function wireDrawers() {
  for (const d of document.querySelectorAll(".drawer")) {
    d.setAttribute("inert", "");
    for (const b of d.querySelectorAll("[data-close]")) b.addEventListener("click", () => closeDrawer(d.id));
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented) return;
    if (document.querySelector("dialog[open]")) return;
    const open = document.querySelector(".drawer[data-open='true']");
    if (open) { e.preventDefault(); closeDrawer(open.id); }
  });
}
