// [desc] Bloc question d'un agent (AskUserQuestion, plan à valider) : options cliquables verrouillées au premier clic, sans toucher au brouillon du champ de message ; reconstruit seulement quand la question change (sinon les clics se perdent). [/desc]

import { h } from "../../lib/ui.js";

// Le plan à valider est l'appel WritePlan déjà rendu dans le fil : on le recopie au-dessus des
// options pour qu'il soit lisible sans déplier « N outils ».
function lastPlanHtml(conv) {
  const plans = [...conv.querySelectorAll("details.tc")]
    .filter((d) => { const name = d.querySelector(".tc-name"); return name && name.textContent.trim() === "WritePlan"; });
  if (!plans.length) return "";
  const clone = plans[plans.length - 1].cloneNode(true);
  const summary = clone.querySelector("summary");
  if (summary) summary.remove();
  return clone.innerHTML;
}

const optionLabel = (o) => o.label || String(o);

function isAwaiting(status) {
  return !!(status && (status.state === "awaiting_input" || status.state === "awaiting_plan_validation") && status.question);
}

function noteText(status, count) {
  if (!count) return "Réponds dans le champ ci-dessous.";
  return status.allow_freetext === false ? "Choisis une des options." : "Ou réponds librement dans le champ ci-dessous.";
}

export function createQuestion(hooks) {
  const text = h("div", { class: "ag-question__text" });
  const plan = h("div", { class: "ag-question__plan", hidden: true });
  const options = h("div", { class: "ag-question__options" });
  const note = h("div", { class: "ag-question__note" });
  const error = h("div", { class: "field__error", role: "alert" });
  const el = h("section", { class: "ag-question", hidden: true, "aria-label": "Question de l'agent" },
    h("div", { class: "ag-question__eyebrow" }, "L'agent attend ta réponse"), text, plan, options, note, error);
  let sig = "";

  /** Un clic verrouille TOUTES les options ; un échec les rend avec un message. */
  async function choose(label, button, buttons) {
    if (buttons.some((x) => x.disabled)) return;
    for (const x of buttons) x.disabled = true;
    button.setAttribute("aria-busy", "true");
    error.textContent = "";
    const ok = await hooks.answer(label);
    button.removeAttribute("aria-busy");
    if (ok) {
      note.textContent = `Réponse « ${label} » envoyée : l'agent reprend…`;
      return;
    }
    for (const x of buttons) x.disabled = false;
    error.textContent = "La réponse n'est pas partie : réessaie (le détail est dans le fil).";
  }

  function paintOptions(opts) {
    const buttons = opts.map((o) => h("button", { type: "button", class: "btn btn--sm ag-question__option", title: o.description || "" }, optionLabel(o)));
    buttons.forEach((b, i) => b.addEventListener("click", () => choose(optionLabel(opts[i]), b, buttons)));
    options.replaceChildren(...buttons);
  }

  function update(status, conv) {
    const awaiting = isAwaiting(status);
    const planHtml = awaiting && status.state === "awaiting_plan_validation" ? lastPlanHtml(conv) : "";
    const next = awaiting ? JSON.stringify([status.state, status.question, (status.options || []).map(optionLabel), planHtml]) : "";
    if (next === sig) return;
    sig = next;
    el.hidden = !awaiting;
    error.textContent = "";
    if (!awaiting) return;
    text.textContent = status.question;
    plan.innerHTML = planHtml;
    plan.hidden = !planHtml;
    const opts = status.options || [];
    paintOptions(opts);
    note.textContent = noteText(status, opts.length);
  }
  return { el, update };
}
