// Streaming token-par-token du tour en cours (/api/sessions/<key>/partial).
// Vit à part du poll de blocs : sa cadence est de 250 ms, contre 1,5 s pour /blocks.

import { openTabs } from "../state.js";
import { t } from "../../i18n/index.js";

// Au retour de visibilité : réveiller immédiatement le streaming des onglets running
// (pollPartial a été stoppé pendant que l'onglet était caché).
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") return;
  for (const [key, entry] of openTabs) {
    if (entry.lastState === "running" && !entry.partialActive) {
      entry.partialActive = true;
      pollPartial(key);
    }
  }
});

// --- Streaming token-par-token : tick rapide du .partial pendant que ça tourne
// Tant que l'agent est "running", on interroge /api/sessions/<key>/partial toutes
// les 250ms. Le texte assistant en cours de génération est affiché dans un bloc
// provisoire `.streaming-block` dont le textContent grandit mot à mot. Le vrai
// bloc rendu (via poll()/blocks) le remplace dès que le message est complet.
// Rend l'état partiel {phase, text, thinking} dans un conteneur (streaming live).
// - thinking non vide -> bloc repliable `.streaming-thinking` (loader "Réflexion en
//   cours…" tant que phase==="thinking", puis se referme .collapsed dès le texte).
// - text -> `.streaming-block` (tokens qui grandissent). Si le texte contient un
//   `<tool_use name="X"`, un header `.streaming-tool` "Outil en cours : X" s'affiche.
// Le vrai bloc rendu (poll()/blocks) retire tout ça dès que le message est complet.
function renderStreamingPartial(container, data) {
  const phase = data.phase || "text";
  const thinking = data.thinking || "";
  const text = data.text || "";

  // --- Bloc thinking repliable ---
  let stk = container.querySelector(".streaming-thinking");
  if (thinking) {
    if (!stk) {
      stk = document.createElement("div");
      stk.className = "streaming-thinking";
      const head = document.createElement("div");
      head.className = "st-head";
      head.innerHTML = '<span class="st-spinner"></span><span class="st-label"></span>';
      head.addEventListener("click", () => stk.classList.toggle("collapsed"));
      const body = document.createElement("div");
      body.className = "st-body";
      stk.appendChild(head);
      stk.appendChild(body);
      container.appendChild(stk);
    }
    const label = stk.querySelector(".st-label");
    const body = stk.querySelector(".st-body");
    if (phase === "thinking") {
      label.textContent = t("panel.thinking_live");
      stk.classList.remove("collapsed");
      stk.classList.add("thinking-active");
    } else {
      label.textContent = t("panel.thinking");
      stk.classList.add("collapsed");
      stk.classList.remove("thinking-active");
    }
    if (body.textContent !== thinking) body.textContent = thinking;
  } else if (stk) {
    stk.remove();
  }

  // --- Header "outil en cours" (détecté dans le texte partiel) ---
  const toolMatches = [...text.matchAll(/<tool_use\s+name="([^"]+)"/g)];
  const toolName = toolMatches.length ? toolMatches[toolMatches.length - 1][1] : null;
  let stool = container.querySelector(".streaming-tool");
  if (phase === "text" && toolName) {
    if (!stool) {
      stool = document.createElement("div");
      stool.className = "streaming-tool";
      stool.innerHTML = '<span class="st-spinner"></span><span class="st-tool-label"></span>';
      const sbExisting = container.querySelector(".streaming-block");
      container.insertBefore(stool, sbExisting || null);
    }
    stool.querySelector(".st-tool-label").textContent = t("panel.tool_running", { tool: toolName });
  } else if (stool) {
    stool.remove();
  }

  // --- Bloc texte assistant (tokens qui grandissent) ---
  let sb = container.querySelector(".streaming-block");
  if (phase === "text" && text) {
    if (!sb) {
      sb = document.createElement("div");
      sb.className = "streaming-block";
      container.appendChild(sb);
    }
    if (sb.textContent !== text) sb.textContent = text;
  } else if (sb) {
    sb.remove();
  }
}

export async function pollPartial(key) {
  const entry = openTabs.get(key);
  if (!entry) return; // onglet fermé
  // Onglet 'launching/<ticket>' : pas encore de session agent → ne PAS spammer
  // /api/sessions (404). On re-tente doucement ; refreshList rebranchera l'onglet
  // sur agent/<id> dès que le spawn a eu lieu (voir remapLaunchingTabs).
  // Idem onglet ouvert sur un node OPTIMISTE : pas de session → /partial = 404.
  if (key.startsWith("launching/") || key.startsWith("optimistic:")) {
    entry.partialPoller = setTimeout(() => pollPartial(key), 1500);
    return;
  }
  try {
    const resp = await fetch(`/api/sessions/${key}/partial`);
    if (resp.ok) {
      const data = await resp.json();
      const pinned = entry.conv.scrollTop + entry.conv.clientHeight >= entry.conv.scrollHeight - 40;
      renderStreamingPartial(entry.conv, data || {});
      if (pinned) entry.conv.scrollTop = entry.conv.scrollHeight;
    }
  } catch (_) { /* réseau : on retentera */ }
  // pollPartial ne sert QU'au streaming (running). Sur tout autre état — awaiting_input
  // ou terminal (finished/cli) — ou si l'onglet est caché, on STOPPE totalement
  // (aucun re-setTimeout) au lieu de re-boucler indéfiniment (bug B6). poll() relancera
  // pollPartial si l'état repasse à "running" sur un onglet visible.
  const streaming = entry.lastState === "running";
  if (streaming && document.visibilityState !== "hidden") {
    entry.partialActive = true;
    entry.partialPoller = setTimeout(() => pollPartial(key), 250);
  } else {
    // Sortie de "running" (terminal/error/awaiting) OU onglet caché : on STOPPE le
    // stream, mais AVANT de couper on purge une dernière fois l'affichage partiel
    // résiduel. Sinon un header ".streaming-tool" (« Outil en cours : X ») — ou un
    // .streaming-block / .streaming-thinking — reste ORPHELIN dans le DOM : le sablier
    // figé signalé par l'user, surtout en fin d'erreur/concurrence où poll() ne ramène
    // aucun nouveau block ce cycle (nextIndex déjà == total) et ne déclenche donc pas
    // sa propre purge conditionnée à `data.blocks.length`. data={} → text/thinking vides
    // → renderStreamingPartial retire les trois .streaming-*.
    renderStreamingPartial(entry.conv, {});
    entry.partialActive = false;
    entry.partialPoller = null;
  }
}
