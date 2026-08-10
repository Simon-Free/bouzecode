// Rail des sous-agents d'une conversation, et appariement des blocs tool_call /
// tool_result rendus par le backend.

import { node, agentId } from "../dom.js";
import { NODES, openTabs } from "../state.js";
import { badge, effectiveState } from "../badges.js";
import { openTab } from "./tabs.js";

// --- Subagents d'une conversation ------------------------------------------

// Un sous-agent est en "alerte" si mort suspecté, en attente d'action, ou en échec ;
// sinon il est compté "ok". Sert à la synthèse repliée « N — X ok / Y alerte ».
function subIsAlert(c) {
  const s = c.state || "";
  // `liveness === "crashed"` : mort PROUVÉE par le backend. Sans elle un enfant mort à 0 bloc
  // était compté « ok » dans la synthèse — la contradiction que corrige effectiveState.
  return !!c.suspect_dead || c.liveness === "crashed" || c.verdict === "KO"
    || s.startsWith("awaiting_") || ["error", "failed", "dead"].includes(s);
}
// Un enfant "actif" (running ou en attente d'action) force l'ouverture du rail.
function subIsActive(c) {
  const s = c.state || "";
  return s === "running" || s.startsWith("awaiting_");
}

function subRailKey(key) { return `bz.conv.subrail.collapsed:${key}`; }
function subRailCollapsed(key) {
  try { return localStorage.getItem(subRailKey(key)) !== "0"; } catch (_) { return true; }
}
function setSubRailCollapsed(key, collapsed) {
  try { localStorage.setItem(subRailKey(key), collapsed ? "1" : "0"); } catch (_) {}
}

export function renderSubagents(key) {
  const entry = openTabs.get(key);
  if (!entry) return;
  const id = agentId(key);
  const children = NODES.filter((n) => n.parent === id || n.parent === key);
  entry.sub.replaceChildren();
  if (!children.length) return;

  const okCount = children.filter((c) => !subIsAlert(c)).length;
  const alertCount = children.length - okCount;
  const hasActive = children.some(subIsActive);
  // Replié par défaut ; état persisté par conversation. Un enfant actif force l'ouverture
  // (override runtime — on n'écrit PAS le localStorage pour ne pas piétiner le choix user).
  const collapsed = hasActive ? false : subRailCollapsed(key);

  const head = node(entry.sub, "button", "conv-sub-head");
  head.type = "button";
  head.setAttribute("aria-expanded", collapsed ? "false" : "true");
  const caret = node(head, "span", "conv-sub-caret", collapsed ? "▸" : "▾");
  caret.setAttribute("aria-hidden", "true");
  const summary = alertCount
    ? `Sous-agents (${children.length}) — ${okCount} ok / ${alertCount} alerte`
    : `Sous-agents (${children.length}) — ${okCount} ok`;
  node(head, "span", "conv-sub-summary", summary);

  const body = node(entry.sub, "div", "conv-sub-body");
  body.hidden = collapsed;
  children.forEach((c) => {
    const chip = node(body, "button", "conv-sub-chip pui-btn pui-btn--sm");
    chip.title = c.title_full || c.title || c.agent_id || c.key;
    badge(chip, effectiveState(c), c.suspect_dead, { compact: true, phase: c.phase });
    node(chip, "span", null, c.title || c.agent_id || c.key);
    // Verdict du validateur (backend fleet._node) : « ✓ OK » vert / « ✗ KO » ambre.
    // On ne SUPPRIME rien : le verdict s'ajoute au libellé role·profil·heure existant.
    if (c.verdict === "OK" || c.verdict === "KO") {
      const ok = c.verdict === "OK";
      const v = node(chip, "span", `conv-sub-verdict conv-sub-verdict--${ok ? "ok" : "ko"}`,
        `${ok ? "✓" : "✗"} ${c.verdict}`);
      v.title = ok ? "Validateur : verdict OK" : "Validateur : verdict KO";
    }
    chip.addEventListener("click", () => openTab(c.key, c.title || c.agent_id || c.key, c.title_full));
  });

  head.addEventListener("click", () => {
    const nowCollapsed = !body.hidden;
    body.hidden = nowCollapsed;
    caret.textContent = nowCollapsed ? "▸" : "▾";
    head.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
    setSubRailCollapsed(key, nowCollapsed);
  });
}

// --- Appariement call+result : imbrique chaque tool_result dans son call ----

export function pairToolBlocks(conv) {
  conv.querySelectorAll("details.tr[data-tool-call-id]").forEach((tr) => {
    if (tr.dataset.paired) return;
    const callId = tr.dataset.toolCallId;
    const tc = conv.querySelector(`details.tc[data-tool-id="${callId}"]`);
    if (tc) {
      tc.appendChild(tr);
      tr.dataset.paired = "1";
    }
  });
}
