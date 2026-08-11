// Envoi d'un message dans une conversation ouverte (POST /api/agents/<id>/continue).
// Un 409 « agent occupé » déclenche une interruption gracieuse puis des tentatives
// bornées, pour préciser un tour EN COURS sans le Ctrl+C-puis-retape manuel.

import { agentId } from "../dom.js";
import { openTabs } from "../state.js";
import { refreshList } from "../sidebar/list.js";
import { poll } from "./poll.js";
import { pollPartial } from "./streaming.js";
import { t } from "../../i18n/index.js";

export async function sendMsg(key) {
  const entry = openTabs.get(key);
  if (!entry || !entry.input) return;
  const text = entry.input.value.trim();
  if (!text) return;
  entry.input.disabled = true;
  try {
    const resp = await fetch(`/api/agents/${agentId(key)}/continue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    // Le corps de l'erreur est lu UNE fois (un Response ne se relit pas) : `reason` dit
    // si l'échec est temporaire (agent occupé) ou définitif (agent introuvable).
    const failure = resp.ok ? {} : await resp.json().catch(() => ({}));
    if (resp.ok) {
      entry.input.value = "";
      if (entry.inputError) entry.inputError.textContent = "";
      // Le POST /continue a réussi : l'agent joue le tour suivant (reprise CHAUDE
      // in-process si idle vivant, sinon respawn FROID). Sans relancer le poll ICI,
      // la réponse du follow-up n'apparaissait qu'au prochain tick SPONTANÉ (jusqu'à
      // ~8s de latence visuelle pure). On redémarre immédiatement le streaming de la
      // conversation, comme retargetTab/remapLaunchingTabs le font au rebranchement.
      poll(key);
      pollPartial(key);
      // Le corps repart tout de suite (ci-dessus) ; la SIDEBAR, elle, ne repassait de
      // « terminé » à « en cours » qu'au tick de 8 s. Même geste, même instant.
      refreshList(true);
    } else if (resp.status === 409 && failure.reason !== "agent_missing") {
      // Agent running: interrupt it (graceful cancel), then retry /continue
      // until it lands (bounded). Lets the user precise a turn IN PROGRESS
      // without the manual Ctrl+C-then-retype flow.
      if (entry.inputError) entry.inputError.textContent = t("panel.interrupting");
      await fetch(`/api/agents/${agentId(key)}/interrupt`, { method: "POST" }).catch(
        () => {}
      );
      const deadline = Date.now() + 120000;
      let landed = false;
      let lastError = "";
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 500));
        let r2;
        try {
          r2 = await fetch(`/api/agents/${agentId(key)}/continue`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          });
        } catch (_) {
          continue;
        }
        if (r2.ok) {
          entry.input.value = "";
          if (entry.inputError) entry.inputError.textContent = "";
          landed = true;
          break;
        }
        // Un échec DÉFINITIF (agent introuvable) ne se répare pas en réessayant :
        // insister deux minutes puis accuser l'interruption masquait la vraie cause.
        const retry = await r2.json().catch(() => ({}));
        lastError = retry.error || "";
        if (r2.status === 404 || retry.reason === "agent_missing") break;
      }
      if (!landed && entry.inputError) {
        entry.inputError.textContent = lastError || t("panel.interrupt_failed");
      }
    } else if (entry.inputError) {
      entry.inputError.textContent = failure.error || t("panel.send_blocked");
    }
  } catch (_) {
    if (entry.inputError) entry.inputError.textContent = t("panel.network_retry");
  } finally {
    entry.input.disabled = false;
    entry.input.focus();
  }
}
