// Ligne meta du panneau (badge d'état, modèle, id copiable, branche, bascule de vue,
// relance) et menu « document » qui porte le chemin du session.json.

import { node, agentId } from "../dom.js";
import { NODES } from "../state.js";
import { badge } from "../badges.js";

// --- Chemin de stockage du JSON de session (copier / télécharger) ----------

// Remplit le menu "document" : chemin complet du session.json (sélectionnable)
// + Copier + Télécharger. Appelé une fois à l'ouverture de l'onglet (le chemin est
// stable). Aucune perte d'info : tout reste accessible à 1 clic via l'icône document.
export function buildSessionMenu(menu, key) {
  const meta = NODES.find((n) => n.key === key);
  const path = (meta && meta.session_path) || "";
  const row = node(menu, "div", "conv-path");
  node(row, "code", "conv-path-code", path || "(chemin indisponible)");
  const copyBtn = node(row, "button", "conv-path-btn", "Copier");
  copyBtn.type = "button";
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(path);
      copyBtn.textContent = "Copié ✓";
      setTimeout(() => { copyBtn.textContent = "Copier"; }, 1500);
    } catch (_) { copyBtn.textContent = "Échec copie"; }
  });
  const dl = node(row, "a", "conv-path-btn", "Télécharger");
  dl.href = `/api/sessions/${key}/download`;
  dl.setAttribute("download", "");
}

// Ligne meta UNIQUE et compacte : badge état (libellé complet) + modèle + id court
// (#xxxxxxxx) + branche + icône "document" qui toggle le menu (chemin/Copier/Télécharger).
// Reconstruite à chaque poll (replaceChildren) ; le menu, lui, est persistant (entry.metaMenu).
export function renderMeta(entry, data) {
  const rawState = (data && data.status && data.status.state) || entry.lastState || "cli";
  const meta = NODES.find((n) => n.key === entry.key);
  // MÊME vivacité que la sidebar et le board : servie par /api/sessions/<key>/blocks
  // (status.liveness), avec la sidebar (n.liveness) en repli quand le panneau s'ouvre avant
  // le premier poll. Sans elle ce badge lisait `status.state` seul et annonçait « terminé »
  // un agent mort à 0 bloc, en contradiction directe avec « planté » sur le board.
  const live = (data && data.status && data.status.liveness) || (meta && meta.liveness) || "";
  const st = live === "crashed" ? "crashed" : rawState;
  entry.status.replaceChildren();
  // suspect_dead propagé : le panneau doit dire « mort ? » là où la vignette le dit.
  // Phase servie par le poll de blocs (status.phase), repli sur la sidebar tant que le
  // premier poll n'est pas revenu — c'est justement l'instant où elle est la plus utile.
  const phase = (data && data.status && data.status.phase) || (meta && meta.phase) || "";
  badge(entry.status, st, meta && meta.suspect_dead, { phase }); // libellé complet, référence lisible
  const model = data && data.meta && data.meta.model;
  if (model) node(entry.status, "span", "conv-meta-model muted", model);
  const idFull = (meta && meta.agent_id) || agentId(entry.key);
  const id8 = idFull.slice(0, 8);
  if (id8) {
    // Chip d'id UNIQUE du panneau (l'onglet ne l'affiche plus). Clic/Entrée → copie l'id
    // COMPLET dans le presse-papier, feedback furtif « copié ✓ ». Même style/comportement
    // que l'ex-chip d'onglet, réutilisés ici (role=button, tabIndex, is-copied).
    const idChip = node(entry.status, "span", "conv-meta-id muted", `#${id8}`);
    idChip.setAttribute("role", "button");
    idChip.tabIndex = 0;
    idChip.title = "Copier l'id complet";
    const copyId = (e) => {
      if (e) e.stopPropagation();
      try { navigator.clipboard && navigator.clipboard.writeText(idFull); } catch (_e) { /* noop */ }
      idChip.textContent = "copié ✓";
      idChip.classList.add("is-copied");
      setTimeout(() => {
        idChip.textContent = `#${id8}`;
        idChip.classList.remove("is-copied");
      }, 900);
    };
    idChip.addEventListener("click", copyId);
    idChip.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copyId(e); }
    });
  }
  const branch = meta && meta.branch;
  if (branch) node(entry.status, "span", "conv-meta-branch muted", branch);
  // Le segmented control [Conversation | Récap] vit DANS la ligne meta (plus de ligne
  // dédiée). appendChild déplace le nœud persistant entry.viewSwitch ici, AVANT le doc
  // (qui a margin-left:auto et colle donc à droite).
  if (entry.viewSwitch) entry.status.appendChild(entry.viewSwitch);
  // Relance : le contrôle s'affiche LUI-MÊME (slot.hidden) selon l'état de vivacité du
  // TICKET servi par /api/tickets/<slug>/<id> (liveness.classify_ticket). On lui passe
  // l'état du panneau et le node de flotte ; il ne sonde le ticket qu'au changement.
  if (entry.relaunch) {
    entry.status.appendChild(entry.relaunch.slot);
    entry.relaunch.update(st, meta);
  }
  const doc = node(entry.status, "button", "conv-meta-doc");
  doc.type = "button";
  doc.title = "Chemin de session — Copier / Télécharger";
  doc.setAttribute("aria-label", "Détails de la session");
  doc.setAttribute("aria-expanded", entry.metaMenu && !entry.metaMenu.hidden ? "true" : "false");
  // Icône document (SVG inline, aucune dépendance).
  doc.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>';
  doc.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!entry.metaMenu) return;
    const open = entry.metaMenu.hidden;
    entry.metaMenu.hidden = !open;
    doc.setAttribute("aria-expanded", open ? "true" : "false");
  });
}
