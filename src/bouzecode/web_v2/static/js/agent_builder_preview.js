// Étape 3 — « Prompt complet calculé », replié : ce que l'agent a réellement en
// tête (prompt de base + skills préchargées + partie custom), plus le rappel de
// ce qui agit hors du texte (tools, hooks).
(function () {
  const out = document.getElementById("b-preview-out");
  const btn = document.getElementById("b-preview");

  function label(open) { return `${open ? "▾" : "▸"} Prompt complet calculé`; }

  async function togglePreview() {
    if (!out.hidden) { out.hidden = true; btn.textContent = label(false); return; }
    const data = await (await fetch("/api/builder/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    })).json();
    const r = data.runtime || {};
    const fmt = (xs) => (xs && xs.length ? xs.join(", ") : "—");
    document.getElementById("b-preview-runtime").innerHTML =
      `<b>Hors prompt (runtime) :</b> tools = ${fmt(r.tools)} · hooks = ${fmt(r.hooks)}` +
      `<br><b>Préchargées dans le prompt :</b> skills = ${fmt(r.skills)}` +
      `<br><span style="opacity:.8">Les tools sont envoyés comme schémas d'API séparés et les hooks agissent à ` +
      `l'exécution (absents du texte) ; les skills sélectionnées sont injectées dans le prompt ci-dessous. ` +
      `La partie éditable est sous « ${data.custom_marker} ».</span>`;
    document.getElementById("b-preview-prompt").textContent = data.system_prompt || "";
    out.hidden = false;
    btn.textContent = label(true);
  }

  btn.addEventListener("click", togglePreview);
})();
