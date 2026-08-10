// Onglet « Plugins » : la liste unique des plugins installés, l'installation
// depuis GitLab (ou un dossier git local), la mise à jour d'un plugin et celle
// de tous les plugins de l'agent sélectionné à l'étape 1.
// $(), loadCatalog() et loadAgents() viennent des fichiers chargés avant.
(function () {
  function pluginsBanner(msg, ok = true) {
    const el = $("b-plugins-banner");
    el.textContent = msg;
    el.className = ok ? "ok" : "ko";
    el.hidden = false;
  }

  async function loadPlugins() {
    const box = $("b-plugins");
    const { plugins } = await (await fetch("/api/plugins")).json();
    box.replaceChildren();
    if (!plugins || !plugins.length) {
      box.innerHTML = '<p class="muted">Aucun plugin installé.</p>';
      return;
    }
    plugins.forEach((p) => box.appendChild(pluginRow(p)));
  }

  function pluginRow(p) {
    const row = document.createElement("div");
    row.className = "plugin-row";
    const label = document.createElement("span");
    const ver = p.version ? ` v${p.version}` : "";
    label.textContent = `${p.name}${ver} — ${(p.tools || []).length} tool(s)`;
    const btn = document.createElement("button");
    btn.textContent = "Mettre à jour";
    btn.onclick = async () => {
      await installPluginPackage(p.name, p.source || "");
      loadPlugins();
    };
    row.appendChild(label);
    row.appendChild(btn);
    return row;
  }

  // POST /api/plugins ; si le paquet vient de git, le serveur demande d'abord
  // confirmation, puis on rejoue avec confirm_git.
  async function installPluginPackage(pkg, source) {
    const body = { package: pkg, source: source || "" };
    const post = async () => (await (await fetch("/api/plugins", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })).json());
    let data = await post();
    if (data.requires_confirmation) {
      if (!confirm(data.message)) { pluginsBanner("Installation annulée.", false); return null; }
      body.confirm_git = true;
      data = await post();
    }
    if (data.error) { pluginsBanner(data.error, false); return null; }
    pluginsBanner(data.message || "Plugin installé.");
    return data;
  }
  // Seule sortie publique historique de ce module.
  window.builderInstallPlugin = installPluginPackage;

  // POST /api/plugins/from-gitlab ; en cas d'absence côté index de paquets, le serveur
  // propose le repli sur un clone git qu'il faut confirmer.
  async function postFromGitlab(input, confirmGit) {
    return (await (await fetch("/api/plugins/from-gitlab", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input, confirm_git: confirmGit }),
    })).json());
  }

  async function installFromGitlab() {
    const input = $("xdir-input").value.trim();
    if (!input) return;
    const btn = $("xdir-add-btn");
    btn.disabled = true; btn.textContent = "Installation…";
    let data = await postFromGitlab(input, false);
    if (data.requires_confirmation && window.confirm(data.message)) {
      btn.textContent = "Clonage…";
      data = await postFromGitlab(input, true);
    }
    btn.disabled = false; btn.textContent = "Installer";
    if (data.requires_confirmation) return;  // repli git refusé par l'utilisateur
    if (data.error) { pluginsBanner(data.error, false); return; }
    $("xdir-input").value = "";
    const via = data.via === "git" ? "depuis le repo git" : "depuis l'index de paquets";
    pluginsBanner(`Plugin « ${data.package} » installé ${via} — recharge la page pour ses skills.`);
    await loadPlugins();
    await loadCatalog();
    await loadAgents();
  }

  async function upgradeAgentPlugins() {
    const name = $("b-existing").value;
    if (!name) { pluginsBanner("Choisis d'abord un agent à l'étape 1.", false); return; }
    const url = `/api/agents/${encodeURIComponent(name)}/upgrade-plugins`;
    const post = (body) => fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then((r) => r.json());

    let data = await post({});
    if (data.requires_confirmation) {
      if (!confirm(data.message)) { pluginsBanner("Mise à jour annulée.", false); return; }
      data = await post({ confirm_git: true });
    }
    if (data.error) { pluginsBanner(data.error, false); loadPlugins(); return; }

    const lines = (data.results || []).map((r) => (r.ok
      ? `${r.package} OK v${r.before || "?"}->v${r.after || "?"}`
      : `${r.package} ECHEC ${r.message || ""}`));
    pluginsBanner(lines.length ? lines.join(" | ") : "Aucun plugin à mettre à jour.");
    loadPlugins();
  }

  $("xdir-add-btn").addEventListener("click", installFromGitlab);
  $("b-upgrade-agent").addEventListener("click", upgradeAgentPlugins);
  loadPlugins();
})();
