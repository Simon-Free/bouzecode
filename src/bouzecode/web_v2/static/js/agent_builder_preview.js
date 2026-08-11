// Étape 3 — « Prompt complet calculé », replié : ce que l'agent a réellement en
// tête (prompt de base + skills préchargées + partie custom), plus le rappel de
// ce qui agit hors du texte (tools, hooks).
(function () {
  const out = document.getElementById("b-preview-out");
  const btn = document.getElementById("b-preview");
  // Dernier aperçu rendu : la bascule de langue le réécrit sans rappeler le serveur.
  let lastPreview = null;

  // Le libellé du bouton porte sa clé en `data-i18n` plutôt que d'être posé en dur : c'est
  // `applyDom` qui le retraduira, et il restera cohérent avec l'état ouvert/fermé.
  function setLabel(open) {
    const key = open ? "builder.preview_open" : "builder.preview_closed";
    btn.setAttribute("data-i18n", key);
    btn.textContent = window.i18n.t(key);
  }

  function renderPreview(data) {
    lastPreview = data;
    const r = data.runtime || {};
    const fmt = (xs) => (xs && xs.length ? xs.join(", ") : "—");
    document.getElementById("b-preview-runtime").innerHTML =
      `<b>${window.i18n.t("builder.preview_runtime")}</b> tools = ${fmt(r.tools)} · ` +
      `hooks = ${fmt(r.hooks)}` +
      `<br><b>${window.i18n.t("builder.preview_preloaded")}</b> skills = ${fmt(r.skills)}` +
      `<br><span style="opacity:.8">` +
      window.i18n.t("builder.preview_note", { marker: data.custom_marker }) +
      `</span>`;
    document.getElementById("b-preview-prompt").textContent = data.system_prompt || "";
  }

  async function togglePreview() {
    if (!out.hidden) { out.hidden = true; setLabel(false); return; }
    renderPreview(await (await fetch("/api/builder/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    })).json());
    out.hidden = false;
    setLabel(true);
  }

  window.redrawPreview = () => { if (lastPreview && !out.hidden) renderPreview(lastPreview); };

  btn.addEventListener("click", togglePreview);
})();
