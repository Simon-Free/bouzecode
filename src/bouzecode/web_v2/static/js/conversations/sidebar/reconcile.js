// Réconciliation du DOM de la sidebar : positionne les groupes et les sections
// existants par insertBefore (déplace sans détruire) et ne retire que le delta.

import { node } from "../dom.js";
import { groupRegistry, createGroup, emptyMsgEl } from "./group.js";
import { updateGroup } from "./group_update.js";

// Reconcilie l'ORDRE et le contenu des groupes d'un container avec la liste `nodes`.
// Positionne chaque groupe persistant via insertBefore (déplace sans détruire),
// puis retire du DOM + du registre les groupes dont la key a disparu.
export function reconcileGroups(container, nodes, depth) {
  const keep = new Set();
  let ref = container.firstChild; // curseur de position attendue
  // Ne jamais insérer un group AVANT le titre de section : garder le titre en tête.
  if (ref && ref.classList && ref.classList.contains("conv-cat-title")) {
    ref = ref.nextSibling;
  }
  nodes.forEach((n) => {
    keep.add(n.key);
    let rec = groupRegistry.get(n.key);
    if (!rec) rec = createGroup(n, depth);
    updateGroup(rec, n, depth);
    if (rec.group !== ref) {
      container.insertBefore(rec.group, ref); // déplace/insère à la bonne position
    } else {
      ref = ref.nextSibling; // déjà en place : avancer le curseur
    }
  });
  // Retirer les groupes de CE container qui ne sont plus désirés.
  [...container.children].forEach((child) => {
    if (!child.classList.contains("conv-group")) return;
    const stillWanted = nodes.some((n) => groupRegistry.get(n.key)?.group === child);
    if (!stillWanted) {
      // Purge récursive du registre pour ce sous-arbre.
      for (const [key, rec] of groupRegistry) {
        if (rec.group === child) { purgeRec(key, rec); break; }
      }
      child.remove();
    }
  });
}

// Retire du registre `key` et, récursivement, les descendants encore stockés.
export function purgeRec(key, rec) {
  if (rec.childrenBox) {
    [...rec.childrenBox.children].forEach((c) => {
      for (const [k, r] of groupRegistry) {
        if (r.group === c) { purgeRec(k, r); break; }
      }
    });
  }
  groupRegistry.delete(key);
}

// Positionne, dans l'ordre, les éléments top-level de #conv-list (structure PLATE :
// titres et groups sont frères, enfants directs). Réutilise les nodes persistants
// (insertBefore les déplace) ; retire les orphelins (titres/section vides).
// Sections d'état persistantes (ordre fixe a→b→c). Chaque section = un wrapper keyé
// (identité DOM stable entre refresh) avec son titre + ses groups. needinput garde
// son cadre orange ; running/finished sont des conteneurs neutres.
const SECTION_ORDER = ["needinput", "running", "finished"];
const SECTION_META = {
  needinput: { cls: "conv-section-needinput", title: "⚠ Nécessite une action" },
  running: { cls: "conv-section-running", title: "● En cours" },
  finished: { cls: "conv-section-finished", title: "Terminés" },
};
// wrapper DOM persistant par section (créé à la demande, retiré quand vide).
const sectionWrappers = new Map(); // sectionKey -> <div.conv-section-*>

export function reconcileTopLevel(list, needInput, running, finished) {
  if (!list) return; // #conv-list absent (render hors DOM monté) : rien à réconcilier.
  const bySection = { needinput: needInput, running: running || [], finished: finished || [] };
  const desired = []; // suite ordonnée d'éléments à placer directement sous #conv-list

  SECTION_ORDER.forEach((sec) => {
    const items = bySection[sec] || [];
    let wrapper = sectionWrappers.get(sec);
    if (items.length) {
      if (!wrapper) {
        const meta = SECTION_META[sec];
        wrapper = document.createElement("div");
        wrapper.className = meta.cls;
        node(wrapper, "div", "conv-cat-title", meta.title);
        sectionWrappers.set(sec, wrapper);
      }
      // Le titre est le firstChild du wrapper ; reconcileGroups gère uniquement les
      // .conv-group frères du titre (il ignore les non-.conv-group).
      reconcileGroups(wrapper, items, 0);
      desired.push(wrapper);
    } else if (wrapper) {
      reconcileGroups(wrapper, [], 0); // purge ses groups
      wrapper.remove();
      sectionWrappers.delete(sec);
    }
  });

  // Retirer les éléments top-level orphelins (sections vidées, groups déplacés).
  const desiredSet = new Set(desired);
  [...list.children].forEach((child) => {
    if (child === emptyMsgEl) return;
    if (desiredSet.has(child)) return;
    if (child.classList.contains("conv-group")) {
      for (const [key, rec] of groupRegistry) {
        if (rec.group === child) { purgeRec(key, rec); break; }
      }
      child.remove();
    } else if (
      child.classList.contains("conv-cat-title") ||
      child.classList.contains("conv-section-needinput") ||
      child.classList.contains("conv-section-running") ||
      child.classList.contains("conv-section-finished")
    ) {
      child.remove();
    }
  });

  // Placer chaque élément désiré dans l'ordre, en déplaçant les nodes persistants.
  let ref = list.firstChild;
  desired.forEach((el) => {
    if (el === ref) { ref = ref.nextSibling; return; }
    list.insertBefore(el, ref);
  });
}
