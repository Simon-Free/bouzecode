// Bloc question/réponse (AskUserQuestion, validation de plan, reprise après crash).
// Il n'est reconstruit QUE lorsqu'il change réellement : reconstruire les boutons à
// chaque poll les rendait incliquables (un nœud détruit entre mousedown et mouseup
// n'émet aucun click).

import { node, agentId } from "../dom.js";
import { sendMsg } from "./send.js";
import { poll } from "./poll.js";

// --- Question (AskUserQuestion) : affiche options + permet de repondre -------

// Pour une validation de plan : extraire le PLAN du dernier tool_call WritePlan
// déjà rendu dans le DOM (details.tc dont .tc-name === "WritePlan") et l'afficher
// au-dessus des boutons. Le plan est replié sous « N outils » sinon invisible.
function extractLastPlanHtml(entry) {
  const details = entry.conv.querySelectorAll("details.tc");
  let last = null;
  details.forEach((d) => {
    const name = d.querySelector(".tc-name");
    if (name && name.textContent.trim() === "WritePlan") last = d;
  });
  if (!last) return null;
  const clone = last.cloneNode(true);
  const summary = clone.querySelector("summary");
  if (summary) summary.remove();
  return clone.innerHTML;
}

function fillQuestionPlan(entry, planHtml) {
  if (planHtml) {
    entry.questionPlan.innerHTML = planHtml;
    entry.questionPlan.hidden = false;
  } else {
    entry.questionPlan.replaceChildren();
    entry.questionPlan.hidden = true;
  }
}

// CE QUI RENDAIT LES RÉPONSES PROPOSÉES INCLIQUABLES (mesuré le 2026-08-03).
// `renderQuestion` détruisait et recréait les boutons de réponse à CHAQUE poll — soit toutes
// les 1,5 s tant que l'agent attend. Or un bouton remplacé ENTRE le mousedown et le mouseup
// n'émet jamais de `click` : le navigateur dispatche l'événement sur le plus proche ancêtre
// COMMUN des deux cibles, c'est-à-dire le conteneur, où aucun listener n'écoute. L'utilisateur
// cliquait « (a) … », et il ne se passait RIEN — aucune requête, aucune erreur, aucune trace.
// Reproduction contrôlée sur la page : 0 clic reçu sur 34 reconstructions au même rythme,
// puis 1 clic reçu immédiatement une fois les reconstructions arrêtées.
// D'où cette signature : le bloc question n'est reconstruit que lorsqu'il CHANGE réellement.
function questionSignature(status, awaiting, planHtml) {
  return JSON.stringify([
    awaiting ? status.state : "",
    awaiting ? status.question : "",
    awaiting ? (status.options || []).map((o) => o.label || String(o)) : [],
    !awaiting && !!status.interrupted,
    planHtml || "",
  ]);
}

export function renderQuestion(entry, status) {
  const awaiting = (status.state === "awaiting_input" || status.state === "awaiting_plan_validation") && status.question;
  // Le plan est extrait du DOM de la conversation, qui se remplit tour après tour : il entre
  // dans la signature pour que son ARRIVÉE TARDIVE déclenche bien une (unique) reconstruction.
  const planHtml = (awaiting && status.state === "awaiting_plan_validation")
    ? extractLastPlanHtml(entry) : null;
  const signature = questionSignature(status, awaiting, planHtml);
  if (entry.questionSignature === signature) return;
  entry.questionSignature = signature;
  // Agent interrompu (crash / redémarrage forcé) : « décider de son sort » EST un input
  // qu'on attend. On réutilise le formatage awaiting (bloc question + option) pour offrir
  // la reprise, plutôt qu'une zone séparée. Reprendre → /continue {text:""} = reprise
  // CHAUDE in-process si le process est encore idle vivant, sinon respawn COLD.
  if (!awaiting && status.interrupted) {
    entry.question.hidden = false;
    entry.questionText.textContent = "Cet agent a été interrompu (crash ou redémarrage). Reprendre là où il en était ?";
    fillQuestionPlan(entry, null);
    entry.questionOptions.replaceChildren();
    const button = node(entry.questionOptions, "button", "conv-question-option", "Reprendre");
    button.addEventListener("click", () => {
      button.disabled = true;
      fetch(`/api/agents/${agentId(entry.key)}/continue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "" }),
      }).then((r) => {
        // Un 409 (l'agent tourne encore) ou 500 (respawn crashé) doit être VISIBLE :
        // sans ce garde, l'erreur était avalée et l'utilisateur croyait « rien ne se passe ».
        if (!r.ok) {
          button.disabled = false;
          return r.text().then((body) => {
            let msg = "";
            try { msg = JSON.parse(body).error || ""; } catch (_) { msg = body; }
            window.alert("La reprise a échoué : " + (msg || `HTTP ${r.status}`));
          });
        }
        return poll(entry.key);
      }).catch(() => { button.disabled = false; });
    });
    return;
  }
  entry.question.hidden = !awaiting;
  if (!awaiting) return;
  entry.questionText.textContent = status.question;
  fillQuestionPlan(entry, planHtml);
  entry.questionOptions.replaceChildren();
  (status.options || []).forEach((option) => {
    const label = option.label || String(option);
    const button = node(entry.questionOptions, "button", "conv-question-option", label);
    button.addEventListener("click", () => {
      // Écho optimiste : trace visuelle immédiate du choix avant reprise du process.
      // Retiré au prochain poll() quand le vrai bloc message arrive.
      const echo = node(entry.conv, "div", "msg msg-user optimistic-echo", label);
      echo.dataset.optimistic = "1";
      entry.conv.scrollTop = entry.conv.scrollHeight;
      entry.input.value = label;
      sendMsg(entry.key);
    });
  });
}
