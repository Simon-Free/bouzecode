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
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = window.i18n.t("builder.no_plugins");
      box.appendChild(empty);
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
    btn.textContent = window.i18n.t("builder.update");
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
      if (!confirm(data.message)) {
        pluginsBanner(window.i18n.t("builder.install_cancelled"), false);
        return null;
      }
      body.confirm_git = true;
      data = await post();
    }
    if (data.error) { pluginsBanner(data.error, false); return null; }
    pluginsBanner(data.message || window.i18n.t("builder.plugin_installed"));
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
    btn.disabled = true; btn.textContent = window.i18n.t("builder.installing");
    let data = await postFromGitlab(input, false);
    if (data.requires_confirmation && window.confirm(data.message)) {
      btn.textContent = window.i18n.t("builder.cloning");
      data = await postFromGitlab(input, true);
    }
    btn.disabled = false; btn.textContent = window.i18n.t("builder.install");
    if (data.requires_confirmation) return;  // repli git refusé par l'utilisateur
    if (data.error) { pluginsBanner(data.error, false); return; }
    $("xdir-input").value = "";
    const via = window.i18n.t(data.via === "git" ? "builder.via_git" : "builder.via_index");
    pluginsBanner(window.i18n.t("builder.plugin_installed_from", { package: data.package, via }));
    await loadPlugins();
    await loadCatalog();
    await loadAgents();
  }

  async function upgradeAgentPlugins() {
    const name = $("b-existing").value;
    if (!name) { pluginsBanner(window.i18n.t("builder.err_pick_agent"), false); return; }
    const url = `/api/agents/${encodeURIComponent(name)}/upgrade-plugins`;
    const post = (body) => fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then((r) => r.json());

    let data = await post({});
    if (data.requires_confirmation) {
      if (!confirm(data.message)) {
        pluginsBanner(window.i18n.t("builder.update_cancelled"), false);
        return;
      }
      data = await post({ confirm_git: true });
    }
    if (data.error) { pluginsBanner(data.error, false); loadPlugins(); return; }

    const lines = (data.results || []).map((r) => (r.ok
      ? `${r.package} OK v${r.before || "?"}->v${r.after || "?"}`
      : `${r.package} ${window.i18n.t("builder.failed")} ${r.message || ""}`));
    pluginsBanner(lines.length
      ? lines.join(" | ")
      : window.i18n.t("builder.no_plugins_to_update"));
    loadPlugins();
  }

  window.redrawPlugins = loadPlugins;

  $("xdir-add-btn").addEventListener("click", installFromGitlab);
  $("b-upgrade-agent").addEventListener("click", upgradeAgentPlugins);
  loadPlugins();
})();
