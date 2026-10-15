// [desc] Profils : skills préchargées du profil en chips (retrait par ×) + recherche avec suggestions au clavier (↑ ↓ Entrée Échap). Une skill introuvable reste affichée et conservée. [/desc]
import { h } from "../lib/ui.js";
import { S } from "./state.js";

const $ = (id) => document.getElementById(id);
const MAX_SUGGESTIONS = 8;

let skills = [];
let changed = () => {};

export function getSkills() { return [...skills]; }

export function setSkills(list) { skills = [...(list || [])]; }

function isKnownSkill(name) {
  return (S.catalog.skills || []).some((s) => s.name === name);
}

function chip(name) {
  const missing = !isKnownSkill(name);
  const remove = h("button", { type: "button", class: "chip__remove", "aria-label": `Retirer la skill ${name}` }, "×");
  remove.addEventListener("click", () => {
    skills = skills.filter((s) => s !== name);
    renderSkillChips();
    changed();
    $("pf-skills-search").focus();
  });
  return h("span", {
    class: "chip", "data-tone": missing ? "warn" : null,
    title: missing ? "Skill introuvable dans le catalogue actuel — conservée tant que tu ne la retires pas." : null,
  }, h("span", {}, missing ? `${name} (introuvable)` : name), remove);
}

export function renderSkillChips() {
  const box = $("pf-skills-chips");
  if (!skills.length) { box.replaceChildren(h("span", { class: "pf-muted" }, "Aucune skill préchargée.")); return; }
  box.replaceChildren(...skills.map(chip));
}

function suggestions(q) {
  const query = q.trim().toLowerCase();
  const correspond = (s) => !query || s.name.toLowerCase().includes(query) || (s.description || "").toLowerCase().includes(query);
  return (S.catalog.skills || []).filter((s) => !skills.includes(s.name) && correspond(s)).slice(0, MAX_SUGGESTIONS);
}

function option(s, i) {
  const opt = h("div", { class: "pf-suggest__item", role: "option", id: `pf-sugg-${i}`, "aria-selected": String(i === 0) },
    h("b", {}, s.name), s.description ? h("span", { class: "pf-muted" }, ` — ${s.description}`) : null);
  opt.addEventListener("mousedown", (e) => { e.preventDefault(); addSkill(s.name); });
  return opt;
}

function renderSuggest() {
  const input = $("pf-skills-search");
  const box = $("pf-skills-suggest");
  const items = suggestions(input.value);
  const open = document.activeElement === input && (input.value.trim() !== "" || items.length > 0);
  box.hidden = !open;
  input.setAttribute("aria-expanded", String(open));
  if (!open) return;
  box.replaceChildren(...(items.length ? items.map(option)
    : [h("div", { class: "pf-suggest__none" }, `Aucune skill ne correspond à « ${input.value.trim()} ».`)]));
}

function addSkill(name) {
  if (!name || skills.includes(name)) return;
  skills.push(name);
  $("pf-skills-search").value = "";
  renderSkillChips();
  renderSuggest();
  changed();
}

function deplacerSelection(input, opts, i, sens) {
  if (!opts.length) return;
  const next = (i + sens + opts.length) % opts.length;
  opts.forEach((o, k) => o.setAttribute("aria-selected", String(k === next)));
  input.setAttribute("aria-activedescendant", opts[next].id);
}

function surTouche(e) {
  const input = e.currentTarget;
  const opts = [...$("pf-skills-suggest").querySelectorAll(".pf-suggest__item")];
  const i = opts.findIndex((o) => o.getAttribute("aria-selected") === "true");
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    deplacerSelection(input, opts, i, e.key === "ArrowDown" ? 1 : -1);
  } else if (e.key === "Enter") {
    e.preventDefault();
    const pick = opts[i >= 0 ? i : 0];
    if (pick) addSkill(pick.querySelector("b").textContent);
  } else if (e.key === "Escape" && input.value) {
    e.stopPropagation();
    input.value = "";
    renderSuggest();
  }
}

/** Câble la recherche de skills ; `onChange` est appelé à chaque ajout / retrait. */
export function wireSkillSearch(onChange) {
  changed = onChange;
  const input = $("pf-skills-search");
  input.addEventListener("input", renderSuggest);
  input.addEventListener("focus", renderSuggest);
  input.addEventListener("blur", () => { setTimeout(renderSuggest, 0); });
  input.addEventListener("keydown", surTouche);
}
