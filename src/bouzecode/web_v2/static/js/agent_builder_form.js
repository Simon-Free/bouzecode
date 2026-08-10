// Étapes 1 → 3 du parcours : charger un profil existant dans le formulaire,
// collecter la saisie, enregistrer ou supprimer le profil global.
// $(), banner(), selectedNames(), selectedHooks() et updateCapabilitiesRecap()
// viennent de agent_builder.js, chargé avant ce fichier.

let AGENTS_BY_NAME = {};

async function loadAgents() {
  const sel = $("b-existing");
  const current = sel.value;
  const { agents } = await (await fetch("/api/builder/agents")).json();
  AGENTS_BY_NAME = {};
  sel.replaceChildren(new Option("— nouveau —", ""));
  (agents || []).forEach((a) => {
    AGENTS_BY_NAME[a.name] = a;
    const tag = a.editable ? a.source : `${a.source} · ${a.kind} (lecture seule → clone)`;
    sel.appendChild(new Option(`${a.name} — ${tag}`, a.name));
  });
  sel.value = current;
}

function clearForm() {
  $("b-name").value = "";
  $("b-prompt").value = "";
  document.querySelectorAll("#b-tools input, #b-skills input").forEach((cb) => (cb.checked = false));
  document.querySelectorAll("#b-hooks select").forEach((s) => (s.value = ""));
  updateCapabilitiesRecap();
}

function applyProfile(p) {
  clearForm();
  $("b-name").value = p.name || "";
  $("b-prompt").value = p.system_prompt_extra || "";
  const set = (group, names) => {
    const wanted = new Set(names || []);
    document.querySelectorAll(`#b-${group} input`).forEach((cb) => (cb.checked = wanted.has(cb.value)));
  };
  set("tools", p.tools);
  set("skills", p.skills);
  (p.hooks || []).forEach((h) => {
    const off = h.startsWith("no-");
    const sel = document.querySelector(`#b-hooks select[data-hook="${off ? h.slice(3) : h}"]`);
    if (sel) sel.value = off ? "off" : "on";
  });
  updateCapabilitiesRecap();
}

function collect() {
  return {
    name: $("b-name").value.trim(),
    tools: selectedNames("tools"),
    skills: selectedNames("skills"),
    hooks: selectedHooks(),
    system_prompt_extra: $("b-prompt").value,
  };
}

async function save() {
  const body = collect();
  if (!body.name) { banner("Donne un nom au profil.", false); return; }
  const resp = await fetch("/api/profiles", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (data.error) { banner(data.error, false); return; }
  banner(`Profil « ${data.name} » enregistré (global).`);
  await loadAgents();
  $("b-existing").value = data.name;
}

async function remove() {
  const name = $("b-existing").value;
  if (!name) { banner("Sélectionne un profil existant à supprimer.", false); return; }
  const a = AGENTS_BY_NAME[name];
  if (a && !a.editable) {
    banner(`« ${name} » (${a.source}) n'est pas un profil global — seuls les profils globaux sont supprimables ici.`, false);
    return;
  }
  if (!confirm(`Supprimer le profil « ${name} » ?`)) return;
  const resp = await fetch(`/api/profiles/${name}`, { method: "DELETE" });
  const data = await resp.json();
  if (data.error) { banner(data.error, false); return; }
  banner(`Profil « ${name} » supprimé.`);
  clearForm();
  await loadAgents();
}

$("b-existing").addEventListener("change", () => {
  const a = AGENTS_BY_NAME[$("b-existing").value];
  if (!a) { clearForm(); return; }
  applyProfile(a);
  banner(a.editable
    ? `Profil global « ${a.name} » chargé — édite et enregistre.`
    : `« ${a.name} » (${a.source}) chargé en lecture seule — enregistre pour en faire un profil global.`);
});
$("b-save").addEventListener("click", save);
$("b-delete").addEventListener("click", remove);

loadAgents();
