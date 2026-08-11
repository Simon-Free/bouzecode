// Onglet « Skills » : lister les skills, éditer le .md brut, enregistrer ou
// supprimer les skills globales (~/.bouzecode/skills).
// g() double $() de agent_builder.js pour garder ce module autonome.
(function () {
  const g = (id) => document.getElementById(id);

  function note(msg, ok = true) {
    const b = g("sk-banner");
    b.textContent = msg;
    b.className = ok ? "ok" : "ko";
    b.hidden = false;
  }

  async function loadList() {
    const sel = g("sk-list");
    const current = sel.value;
    const { skills } = await (await fetch("/api/skills")).json();
    sel.replaceChildren(new Option(window.i18n.t("builder.opt_choose"), ""));
    (skills || []).forEach((s) => {
      const tag = s.editable
        ? s.source
        : `${s.source} ${window.i18n.t("builder.read_only_clone")}`;
      sel.appendChild(new Option(`${s.name} — ${tag}`, s.name));
    });
    sel.value = current;
  }

  async function loadSkill(name) {
    if (!name) { g("sk-content").value = ""; g("sk-meta").textContent = ""; return; }
    const s = await (await fetch(`/api/skills/${name}`)).json();
    if (s.error) { note(s.error, false); return; }
    g("sk-new-name").value = "";
    g("sk-content").value = s.content || "";
    g("sk-meta").textContent = s.editable
      ? window.i18n.t("builder.skill_global_editable")
      : window.i18n.t("builder.skill_readonly", { source: s.source });
  }

  async function newSkill() {
    const name = g("sk-new-name").value.trim();
    if (!name) { note(window.i18n.t("builder.err_skill_name"), false); return; }
    const s = await (await fetch(`/api/skills/${name}?new=1`)).json();
    g("sk-list").value = "";
    g("sk-content").value = s.content || "";
    g("sk-meta").textContent = window.i18n.t("builder.skill_new_unsaved");
  }

  async function save() {
    const name = (g("sk-list").value || g("sk-new-name").value).trim();
    const resp = await fetch("/api/skills", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, content: g("sk-content").value }),
    });
    const data = await resp.json();
    if (data.error) { note(data.error, false); return; }
    note(window.i18n.t("builder.skill_saved", { name: data.name }));
    g("sk-new-name").value = "";
    await loadList();
    g("sk-list").value = data.name;
    loadCatalog();  // une skill ajoutée/retirée change la liste de l'étape 2
  }

  async function remove() {
    const name = g("sk-list").value;
    if (!name) { note(window.i18n.t("builder.err_pick_skill"), false); return; }
    if (!confirm(window.i18n.t("builder.confirm_delete_skill", { name }))) return;
    const data = await (await fetch(`/api/skills/${name}`, { method: "DELETE" })).json();
    if (data.error) { note(data.error, false); return; }
    note(window.i18n.t("builder.skill_deleted", { name }));
    g("sk-content").value = "";
    await loadList();
    loadCatalog();  // une skill ajoutée/retirée change la liste de l'étape 2
  }

  // Redessin sur bascule de langue (appelé par l'unique gestionnaire d'agent_builder.js).
  // On NE rejoue PAS loadSkill : il réécrit le contenu du .md depuis le serveur et ferait
  // perdre une édition en cours. La ligne de méta reste donc dans l'ancienne langue jusqu'à
  // la prochaine sélection — un libellé descriptif vaut moins qu'un texte non enregistré.
  window.redrawSkillsPanel = loadList;

  g("sk-list").addEventListener("change", () => loadSkill(g("sk-list").value));
  g("sk-new").addEventListener("click", newSkill);
  g("sk-save").addEventListener("click", save);
  g("sk-delete").addEventListener("click", remove);
  loadList();
})();
