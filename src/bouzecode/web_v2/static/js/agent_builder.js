// Agent builder — coquille de la page : onglets, catalogue tools/skills/hooks et
// résumé replié des capacités.
// Script classique : les helpers ci-dessous sont globaux et réutilisés par les
// fichiers agent_builder_*.js chargés ensuite (form, preview, catalog, skills, plugins).
const $ = (id) => document.getElementById(id);
let CATALOG = { tools: [], skills: [], hooks: [] };

function banner(msg, ok = true) {
  const b = $("b-banner");
  b.textContent = msg;
  b.className = ok ? "ok" : "ko";
  b.hidden = false;
}

// Onglets : un seul .ab-panel visible à la fois.
function showPanel(panelId) {
  document.querySelectorAll(".ab-panel").forEach((p) => (p.hidden = p.id !== panelId));
  document.querySelectorAll("#ab-tabs .tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.panel === panelId));
}

function checkItem(item, group) {
  const wrap = document.createElement("label");
  wrap.className = "check-item";
  wrap.dataset.search = (item.name + " " + (item.description || "")).toLowerCase();
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.value = item.name;
  cb.dataset.group = group;
  if (item.system) {
    cb.checked = true;
    cb.disabled = true;
    wrap.classList.add("system-tool");
    wrap.title = window.i18n.t("builder.system_tool");
  }
  const body = document.createElement("div");
  const name = document.createElement("span");
  name.className = "ci-name";
  name.textContent = item.name;
  if (item.read_only) {
    const ro = document.createElement("span");
    ro.className = "ci-ro";
    ro.textContent = "read-only";
    name.appendChild(ro);
  }
  body.appendChild(name);
  if (item.description) {
    const desc = document.createElement("div");
    desc.className = "ci-desc";
    desc.textContent = item.description;
    body.appendChild(desc);
  }
  wrap.appendChild(cb);
  wrap.appendChild(body);
  return wrap;
}

function renderChecks(containerId, items, group, countId) {
  $(containerId).replaceChildren(...items.map((it) => checkItem(it, group)));
  if (countId) $(countId).textContent = `(${items.length})`;
}

function renderHooks(hooks) {
  const box = $("b-hooks");
  box.replaceChildren();
  hooks.forEach((h) => {
    const row = document.createElement("div");
    row.className = "hook-row";
    const sel = document.createElement("select");
    sel.dataset.hook = h.name;
    [["", "builder.hook_default"], ["on", "builder.hook_on"], ["off", "builder.hook_off"]]
      .forEach(([value, key]) => sel.appendChild(new Option(window.i18n.t(key), value)));
    const label = document.createElement("div");
    label.innerHTML = `<span class="ci-name">${h.name}</span>` +
      `<div class="ci-desc">${h.description || ""}</div>`;
    row.appendChild(sel);
    row.appendChild(label);
    box.appendChild(row);
  });
}

function wireFilter(filterId, containerId) {
  $(filterId).addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    $(containerId).querySelectorAll(".check-item").forEach((el) => {
      el.style.display = el.dataset.search.includes(q) ? "" : "none";
    });
  });
}

function selectedNames(group) {
  return [...document.querySelectorAll(`#b-${group} input:checked`)].map((cb) => cb.value);
}

// Hooks non "défaut", au format attendu par l'API : `nom` activé, `no-nom` désactivé.
function selectedHooks() {
  const hooks = [];
  document.querySelectorAll("#b-hooks select").forEach((s) => {
    if (s.value === "on") hooks.push(s.dataset.hook);
    else if (s.value === "off") hooks.push("no-" + s.dataset.hook);
  });
  return hooks;
}

// Résumé affiché sur l'étape 2 repliée : « 8 tools · 3 skills [· 2 hooks] ».
function updateCapabilitiesRecap() {
  const parts = [
    `${selectedNames("tools").length} tools`,
    `${selectedNames("skills").length} skills`,
  ];
  const hooks = selectedHooks().length;
  if (hooks) parts.push(`${hooks} hooks`);
  $("b-caps-recap").textContent = parts.join(" · ");
}

async function loadCatalog() {
  CATALOG = await (await fetch("/api/builder/catalog")).json();
  renderChecks("b-tools", CATALOG.tools, "tools", "b-tools-count");
  renderChecks("b-skills", CATALOG.skills, "skills", "b-skills-count");
  renderHooks(CATALOG.hooks);
  updateCapabilitiesRecap();
}

// Bascule de langue — L'UNIQUE point de redessin de la page. `applyDom` a déjà retraduit le
// gabarit ; ne restent que les listes composées en JavaScript. Elles sont reconstruites depuis
// zéro, ce qui EFFACERAIT la saisie en cours : on relève donc le brouillon avant, et on le
// réapplique après. Les panneaux repliés dans des IIFE publient leur redessin sur `window`.
function redrawBuilder() {
  const draft = collect();
  loadCatalog().then(() => applyProfile(draft));
  loadAgents();
  loadAgentCatalog();
  if (window.redrawPlugins) window.redrawPlugins();
  if (window.redrawSkillsPanel) window.redrawSkillsPanel();
  if (window.redrawPreview) window.redrawPreview();
}

$("ab-tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (tab) showPanel(tab.dataset.panel);
});
window.i18n.onChange(redrawBuilder);
$("b-caps").addEventListener("change", updateCapabilitiesRecap);
wireFilter("b-tools-filter", "b-tools");
wireFilter("b-skills-filter", "b-skills");

loadCatalog();
