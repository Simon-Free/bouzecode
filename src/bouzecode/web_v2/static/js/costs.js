// Session costs tab — fetches /api/sessions/<key>/costs and renders a table
(function () {
  "use strict";

  let loaded = false;

  function fmt(n) {
    if (n == null) return "—";
    if (typeof n === "number" && !Number.isInteger(n)) return n.toFixed(4);
    return n.toLocaleString();
  }

  function buildTable(data) {
    const container = document.getElementById("tab-costs");
    if (!data || !data.total) {
      container.innerHTML = '<p class="muted">Pas de données de coûts disponibles.</p>';
      return;
    }

    let html = '<table class="data-table costs-table"><thead><tr>';
    html += "<th>Modèle</th><th>Appels</th><th>Input tokens</th><th>Output tokens</th>";
    html += "<th>Cache lu</th><th>Cache écrit</th><th>% hit cache</th><th>Coût ($)</th>";
    html += "</tr></thead><tbody>";

    const models = data.models || {};
    for (const [model, stats] of Object.entries(models)) {
      html += "<tr>";
      html += `<td>${model}</td>`;
      html += `<td class="num">${fmt(stats.calls)}</td>`;
      html += `<td class="num">${fmt(stats.input_tokens)}</td>`;
      html += `<td class="num">${fmt(stats.output_tokens)}</td>`;
      html += `<td class="num">${fmt(stats.cache_read_tokens)}</td>`;
      html += `<td class="num">${fmt(stats.cache_write_tokens)}</td>`;
      html += `<td class="num">${stats.cache_hit_pct}%</td>`;
      html += `<td class="num">${fmt(stats.cost)}</td>`;
      html += "</tr>";
    }

    // Total row
    const t = data.total;
    html += '<tr class="total-row">';
    html += `<td><strong>Total</strong></td>`;
    html += `<td class="num"><strong>${fmt(t.calls)}</strong></td>`;
    html += `<td class="num"><strong>${fmt(t.input_tokens)}</strong></td>`;
    html += `<td class="num"><strong>${fmt(t.output_tokens)}</strong></td>`;
    html += `<td class="num"><strong>${fmt(t.cache_read_tokens)}</strong></td>`;
    html += `<td class="num"><strong>${fmt(t.cache_write_tokens)}</strong></td>`;
    html += `<td class="num"><strong>${t.cache_hit_pct}%</strong></td>`;
    html += `<td class="num"><strong>${fmt(t.cost)}</strong></td>`;
    html += "</tr></tbody></table>";

    container.innerHTML = html;
  }

  async function loadCosts() {
    if (loaded) return;
    loaded = true;
    const container = document.getElementById("tab-costs");
    try {
      const resp = await fetch(`/api/sessions/${SESSION_KEY}/costs`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      buildTable(data);
    } catch (e) {
      container.innerHTML = `<p class="error">Erreur chargement coûts: ${e.message}</p>`;
    }
  }

  // Hook into tab switching
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".tab[data-tab='costs']").forEach((btn) => {
      btn.addEventListener("click", loadCosts);
    });
  });
})();
