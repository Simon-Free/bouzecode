// Appariement des blocs `tool_call` / `tool_result` rendus par le backend.
//
// Ce fichier s'appelait `subagents.js` et portait aussi `renderSubagents`, qui dessinait
// un rail de sous-agents sous le fil. Ce rail a été retiré de l'interface : la navigation
// vers un enfant passe par la sidebar dépliable et les marqueurs inline. La fonction est
// restée morte (aucun appelant) jusqu'à sa suppression ; trois tests gardent l'absence de
// `.conv-sub-head` / `.conv-sub-chip` dans le panneau, en non-régression.

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
