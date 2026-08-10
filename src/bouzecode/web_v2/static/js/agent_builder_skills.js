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
    sel.replaceChildren(new Option("— choisir —", ""));
    (skills || []).forEach((s) => {
      const tag = s.editable ? s.source : `${s.source} (lecture seule → clone)`;
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
      ? "globale — éditable directement"
      : `${s.source} — lecture seule ; enregistre pour la forker en skill globale`;
  }

  async function newSkill() {
    const name = g("sk-new-name").value.trim();
    if (!name) { note("Donne un nom à la nouvelle skill.", false); return; }
    const s = await (await fetch(`/api/skills/${name}?new=1`)).json();
    g("sk-list").value = "";
    g("sk-content").value = s.content || "";
    g("sk-meta").textContent = "nouvelle skill globale (non enregistrée)";
  }

  async function save() {
    const name = (g("sk-list").value || g("sk-new-name").value).trim();
    const resp = await fetch("/api/skills", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, content: g("sk-content").value }),
    });
    const data = await resp.json();
    if (data.error) { note(data.error, false); return; }
    note(`Skill « ${data.name} » enregistrée.`);
    g("sk-new-name").value = "";
    await loadList();
    g("sk-list").value = data.name;
    loadCatalog();  // une skill ajoutée/retirée change la liste de l'étape 2
  }

  async function remove() {
    const name = g("sk-list").value;
    if (!name) { note("Sélectionne une skill à supprimer.", false); return; }
    if (!confirm(`Supprimer la skill globale « ${name} » ?`)) return;
    const data = await (await fetch(`/api/skills/${name}`, { method: "DELETE" })).json();
    if (data.error) { note(data.error, false); return; }
    note(`Skill « ${name} » supprimée.`);
    g("sk-content").value = "";
    await loadList();
    loadCatalog();  // une skill ajoutée/retirée change la liste de l'étape 2
  }

  g("sk-list").addEventListener("change", () => loadSkill(g("sk-list").value));
  g("sk-new").addEventListener("click", newSkill);
  g("sk-save").addEventListener("click", save);
  g("sk-delete").addEventListener("click", remove);
  loadList();
})();
