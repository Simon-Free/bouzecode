// Onglet « Catalogue » : agents déjà installés vs agents disponibles à distance,
// installation d'un agent du catalogue, rafraîchissement du catalogue distant,
// et import d'un agent décrit en YAML.
// $() et loadAgents() viennent des fichiers agent_builder(.form).js chargés avant.

function catalogBanner(msg, ok = true) {
  const el = $("cat-banner");
  el.textContent = msg;
  el.className = ok ? "ok" : "ko";
  el.hidden = false;
}

async function loadAgentCatalog() {
  let data;
  try {
    data = await (await fetch("/api/agents/catalog")).json();
  } catch (e) {
    catalogBanner("Catalogue indisponible : " + e, false);
    return;
  }
  renderCatalogList("cat-installed", data.installed || [], false);
  renderCatalogList("cat-available", data.available || [], true);
}

function renderCatalogList(containerId, items, installable) {
  const box = $(containerId);
  const countEl = $(containerId + "-count");
  if (countEl) countEl.textContent = `(${items.length})`;
  box.replaceChildren();
  if (!items.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "(aucun)";
    box.appendChild(p);
    return;
  }
  items.forEach((a) => box.appendChild(catalogRow(a, installable)));
}

function catalogRow(agent, installable) {
  const row = document.createElement("div");
  row.className = "cat-row";
  const meta = document.createElement("div");
  meta.className = "cat-meta";
  const title = document.createElement("b");
  title.textContent = agent.name;
  const desc = document.createElement("span");
  desc.className = "muted";
  desc.textContent = agent.description ? " — " + agent.description : "";
  const tools = document.createElement("div");
  tools.className = "muted cat-tools";
  tools.textContent = (agent.tools || []).join(", ");
  meta.appendChild(title);
  meta.appendChild(desc);
  meta.appendChild(tools);
  row.appendChild(meta);
  if (installable) {
    const btn = document.createElement("button");
    btn.textContent = "Installer";
    btn.onclick = () => installAgent(agent.name, btn);
    row.appendChild(btn);
  } else {
    const badge = document.createElement("span");
    badge.className = "cat-badge";
    badge.textContent = "Installé";
    row.appendChild(badge);
  }
  return row;
}

async function installAgent(name, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Installation…"; }
  let res;
  try {
    res = await (await fetch("/api/agents/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    })).json();
  } catch (e) {
    catalogBanner("Échec installation : " + e, false);
    if (btn) { btn.disabled = false; btn.textContent = "Installer"; }
    return;
  }
  if (res.ok) catalogBanner(`Agent « ${name} » installé.`, true);
  else catalogBanner(`Erreurs : ${(res.errors || []).join(" ; ")}`, false);
  await loadAgentCatalog();
  await loadAgents();
}

async function refreshAgentCatalog(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Rafraîchissement…"; }
  try {
    await fetch("/api/agents/catalog/refresh", { method: "POST" });
    catalogBanner("Catalogue rafraîchi.", true);
  } catch (e) {
    catalogBanner("Échec rafraîchissement : " + e, false);
  }
  if (btn) { btn.disabled = false; btn.textContent = "Rafraîchir le catalogue"; }
  await loadAgentCatalog();
}

// Importe un agent décrit en YAML. Si l'agent tire des plugins depuis git, le
// serveur répond d'abord requires_confirmation ; on demande, puis on réessaie
// avec confirm_git. Pas de déclencheur dans la page : appelé depuis la console.
async function importAgent(yamlText) {
  let resp = await fetch("/api/agents/import", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml: yamlText }),
  });
  let data = await resp.json();
  if (data.requires_confirmation) {
    const sources = (data.git_sources || []).join("\n");
    if (!confirm(`${data.message}\n\n${sources}`)) { catalogBanner("Import annulé.", false); return null; }
    resp = await fetch("/api/agents/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml: yamlText, confirm_git: true }),
    });
    data = await resp.json();
  }
  if (data.error) { catalogBanner(data.error, false); return null; }
  const errs = (data.errors || []).length ? ` (erreurs: ${data.errors.join("; ")})` : "";
  catalogBanner(`Agent « ${data.name} » importé${errs}.`);
  await loadAgents();
  return data;
}
window.builderImportAgent = importAgent;

$("cat-refresh").addEventListener("click", (e) => refreshAgentCatalog(e.currentTarget));
loadAgentCatalog();
