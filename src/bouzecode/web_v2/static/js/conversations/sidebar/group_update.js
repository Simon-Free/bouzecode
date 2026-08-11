// Mise à jour IN-PLACE d'une carte de la sidebar : rien n'est détruit, seul le delta
// est appliqué. Le badge n'est recréé que si l'état, le soupçon de mort OU la phase
// changent — la phase étant cuite DANS le badge, l'omettre figeait son libellé.

import { node, agentId } from "../dom.js";
import { openTabs, activeKey } from "../state.js";
import { t } from "../../i18n/index.js";
import { activityChipText } from "../activity.js";
import { effectiveState, buildBadge, stateTooltipLabel } from "../badges.js";
import { i18nText, i18nTitle } from "./group.js";
import {
  childrenOf, markExpanded, markCollapsed, forgetToggle, desiredOpen, aggregateChildren,
} from "./toggles.js";
import { handleArchiveClick } from "./archive.js";
import { reconcileGroups } from "./reconcile.js";
import { formatEventTime, formatEventTimeTooltip } from "../../time_format.js";

// Chip « activité » d'une carte : ce que l'agent fait en ce moment, ou la phase du lancement
// en cours. Ajoutée / mise à jour / retirée selon la présence du libellé (un agent terminé n'a
// rien à raconter, le serveur n'envoie alors aucun de ces champs).
//
// `stale` (aucun battement depuis > 4 min sur un agent « en cours ») ajoute une classe ET un
// texte explicite : règle transverse du front, une alerte n'est JAMAIS un simple point coloré.
function updateActivityChip(rec, n) {
  const texte = activityChipText(n);
  if (!texte) {
    if (rec.activityEl) { rec.activityEl.remove(); rec.activityEl = null; rec.activity = undefined; }
    return;
  }
  if (!rec.activityEl) {
    rec.activityEl = node(rec.metaEl, "span", "conv-item-activity");
    rec.metaEl.insertBefore(rec.activityEl, rec.metaEl.firstChild);
  }
  if (rec.activity !== texte) { rec.activityEl.textContent = texte; rec.activity = texte; }
  rec.activityEl.classList.toggle("is-stale", !!n.stale);
  rec.activityEl.title = n.stale ? t("activity.stale_tip") : texte;
}

// Met à jour IN-PLACE ce qui a changé — ne détruit rien, ne touche pas hidden.
export function updateGroup(rec, n, depth) {
  const row = rec.row;
  // Profondeur (classe conv-child) — rare mais possible si l'arbre change.
  if (rec.depth !== depth) {
    row.className = depth > 0 ? "conv-item conv-child" : "conv-item";
    rec.depth = depth;
  }
  // Classes d'état : `open` = onglet ouvert ; `active` = onglet courant (activeKey).
  // Pour une entrée FLAT, on reflète l'état de la VRAIE conv (n._realKey).
  const stateKey = n._realKey || n.key;
  row.classList.toggle("open", openTabs.has(stateKey));
  row.classList.toggle("active", stateKey === activeKey);
  // Pastille « Récap » : visible dès que la session a un récap structuré (n.has_recap).
  if (rec.recapBtn) rec.recapBtn.hidden = !n.has_recap;
  // badge : recréé UNIQUEMENT si state, suspect_dead ou PHASE a changé. La phase est cuite
  // DANS le badge (elle prime sur l'état, cf. badge()) : l'omettre de cette condition figeait
  // le libellé sur la dernière phase vue tant que l'état ne bougeait pas — « le modèle lit
  // votre demande… » restait affiché pendant tout le travail de l'agent, puisque la phase
  // s'efface (→ "") à état `running` INCHANGÉ.
  const eff = effectiveState(n);
  const phase = n.phase || "";
  if (rec.state !== eff || rec.suspectDead !== n.suspect_dead || rec.phase !== phase) {
    const fresh = buildBadge(eff, n.suspect_dead, { compact: true, phase });
    row.replaceChild(fresh, rec.badgeEl);
    rec.badgeEl = fresh;
    rec.state = eff; rec.suspectDead = n.suspect_dead; rec.phase = phase;
  }
  // titre : textContent seulement si différent.
  const title = n.title || n.agent_id || n.key;
  if (rec.title !== title) { rec.titleEl.textContent = title; rec.title = title; }
  rec.titleEl.title = n.title_full || title;
  // Ligne 2 (SUJET) : MAJ du texte seulement si changé.
  if (rec.subjectEl) {
    const subj = n.title_full || "";
    if (rec.subject !== subj) { rec.subjectEl.textContent = subj; rec.subject = subj; }
  }
  // CE QUE FAIT L'AGENT : phrase servie par le serveur (`activity_label` pour un agent vivant,
  // `phase_label` pour un ticket en cours de lancement). Une seule source de mots pour l'UI et
  // pour l'API : cf. services/work/activity.py et launch_phase.py. Sans cette ligne, « en
  // cours » était tout ce que l'utilisateur pouvait savoir de onze minutes de travail.
  updateActivityChip(rec, n);
  // Heure sidebar : re-formate si started_at a changé (helper unique, heure locale).
  if (rec.timeEl && rec.startedAt !== (n.started_at || "")) {
    rec.startedAt = n.started_at || "";
    rec.timeEl.textContent = formatEventTime(rec.startedAt);
    rec.timeEl.title = formatEventTimeTooltip(rec.startedAt);
  }
  // meta B8 — branche structurée (label + name) : add / update / remove selon présence.
  if (n.branch) {
    if (!rec.branchWrap) {
      rec.branchWrap = node(rec.metaEl, "span", "conv-item-branch");
      i18nText(node(rec.branchWrap, "span", "conv-item-branch-label"), "sidebar.branch_label");
      rec.branchNameEl = node(rec.branchWrap, "span", "conv-item-branch-name", n.branch);
      // La branche doit précéder l'id court dans la ligne meta.
      rec.metaEl.insertBefore(rec.branchWrap, rec.metaEl.firstChild);
    } else if (rec.branch !== n.branch) {
      rec.branchNameEl.textContent = n.branch;
    }
    rec.branch = n.branch;
  } else if (rec.branchWrap) {
    rec.branchWrap.remove();
    rec.branchWrap = null; rec.branchNameEl = null; rec.branch = undefined;
  }
  // meta B8 — id court copiable (#shortId) : add / update selon présence.
  const shortId = n.agent_id || agentId(n.key);
  if (shortId) {
    if (!rec.idBadge) {
      const idBadge = node(rec.metaEl, "span", "conv-item-agentid", `#${shortId}`);
      idBadge.setAttribute("role", "button");
      idBadge.tabIndex = 0;
      i18nTitle(idBadge, "sidebar.copy_agent_id");
      const copyId = (e) => {
        e.stopPropagation();
        const current = rec.shortId; // capture la valeur courante au moment du clic
        navigator.clipboard.writeText(current).then(() => {
          const prev = idBadge.textContent;
          idBadge.textContent = t("sidebar.copied");
          idBadge.classList.add("is-copied");
          setTimeout(() => {
            idBadge.textContent = prev;
            idBadge.classList.remove("is-copied");
          }, 1200);
        });
      };
      idBadge.addEventListener("click", copyId);
      idBadge.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") copyId(e);
      });
      rec.idBadge = idBadge;
    } else if (rec.shortId !== shortId) {
      rec.idBadge.textContent = `#${shortId}`;
    }
    rec.shortId = shortId;
  } else if (rec.idBadge) {
    rec.idBadge.remove(); rec.idBadge = null; rec.shortId = undefined;
  }
  // toggle + childrenBox : présents ssi le node a des enfants.
  // Une entrée FLAT (sous-agent en propre) est une feuille : childrenOf(::flat) === []
  // donc pas de toggle. La vraie racine porte l'imbrication.
  const kids = childrenOf(n);
  if (kids.length) {
    if (!rec.toggleEl) {
      // Création UNE FOIS. Ligne d'en-tête dédiée `.conv-toggle` : div role=button,
      // frère du childrenBox dans le group (TOUJOURS visible), cliquable EN ENTIER.
      rec.childrenBox = document.createElement("div");
      rec.childrenBox.className = "conv-children";
      rec.toggleEl = document.createElement("div");
      rec.toggleEl.className = "conv-toggle";
      rec.toggleEl.setAttribute("role", "button");
      rec.toggleEl.tabIndex = 0;
      // Header PUIS box : le header reste visible quand la box est repliée.
      rec.group.appendChild(rec.toggleEl);
      rec.group.appendChild(rec.childrenBox);
      // État déplié initial (choix user > auto-expand) — fixé UNE SEULE FOIS.
      const isOpen = desiredOpen(n, kids);
      rec.childrenBox.hidden = !isOpen;
      rec.toggleEl.textContent = `${isOpen ? "▾" : "▸"} ${aggregateChildren(kids)}`;
      const doToggle = () => {
        const nowOpen = rec.childrenBox.hidden; // on va inverser
        rec.childrenBox.hidden = !nowOpen;
        const kidsNow = childrenOf(n);
        rec.toggleEl.textContent = `${nowOpen ? "▾" : "▸"} ${aggregateChildren(kidsNow)}`;
        if (nowOpen) markExpanded(n.key); else markCollapsed(n.key);
      };
      rec.toggleEl.addEventListener("click", (e) => { e.stopPropagation(); doToggle(); });
      rec.toggleEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doToggle(); }
      });
    } else {
      // Toggle déjà présent : NE touche PAS hidden (piloté par l'utilisateur),
      // mais rafraîchit le libellé agrégé en préservant la flèche courante.
      rec.toggleEl.textContent = `${rec.childrenBox.hidden ? "▸" : "▾"} ${aggregateChildren(kids)}`;
    }
    reconcileGroups(rec.childrenBox, kids, depth + 1);
  } else if (rec.toggleEl) {
    // Plus d'enfants : retire toggle + box (et purge leurs registres via reconcile vide).
    reconcileGroups(rec.childrenBox, [], depth + 1);
    rec.toggleEl.remove(); rec.toggleEl = null;
    rec.childrenBox.remove(); rec.childrenBox = null;
    forgetToggle(n.key);
  }
  // B9 : bouton "Archiver" sur TOUTE vraie racine (depth 0) ET sur les entrées FLAT
  // (sous-agents/méta-agents remontés en propre dans « Nécessite une action »). Une entrée
  // FLAT porte `_realKey` = sa clé réelle `agent/<id>` ; on archive CELLE-CI (pas `n.key`
  // suffixée `::flat`, qui casserait collectSubtree/agentId). Sans ça, un méta-agent parké
  // en needinput n'avait aucun bouton Archiver.
  const wantArch = depth === 0 && !n._ghost;
  if (wantArch && !rec.archBtn) {
    const arch = i18nText(node(row, "span", "conv-archive-btn"), "sidebar.archive");
    arch.setAttribute("role", "button");
    i18nTitle(arch, "sidebar.archive_tip");
    arch.addEventListener("click", (e) => { e.stopPropagation(); handleArchiveClick(n._realKey || n.key, arch); });
    rec.archBtn = arch;
  } else if (!wantArch && rec.archBtn) {
    rec.archBtn.remove(); rec.archBtn = null;
  }
  // Tooltip de la CARTE (row) : id + branche + état, regroupés au survol. Spec 2 :
  // les chips #id et branche sont retirées visuellement de la carte (CSS) mais AUCUNE
  // info n'est perdue — elles restent dans le DOM (metaEl) ET accessibles ici en tooltip.
  const stateLabel = stateTooltipLabel(eff, n.suspect_dead);
  const tipParts = [];
  if (stateLabel) tipParts.push(stateLabel);
  if (n.branch) tipParts.push(t("sidebar.branch_tip", { branch: n.branch }));
  if (rec.shortId) tipParts.push(`#${rec.shortId}`);
  row.title = tipParts.join(" · ");
}
