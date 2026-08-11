// Session costs tab — fetches /api/sessions/<key>/costs and renders a table
(function () {
  "use strict";

  let loaded = false;
  // Dernière réponse rendue : la bascule de langue redessine le tableau à partir d'elle,
  // sans refaire l'appel réseau.
  let lastData = null;

  function fmt(n) {
    if (n == null) return "—";
    if (typeof n === "number" && !Number.isInteger(n)) return n.toFixed(4);
    return n.toLocaleString();
  }

  // « Input tokens », « Output tokens » et « Total » s'écrivent pareil dans les deux langues.
  function headerCells() {
    return [
      window.i18n.t("session.costs_model"), window.i18n.t("session.costs_calls"),
      "Input tokens", "Output tokens",
      window.i18n.t("session.costs_cache_read"), window.i18n.t("session.costs_cache_write"),
      window.i18n.t("session.costs_hit_pct"), window.i18n.t("session.costs_cost"),
    ].map((label) => `<th>${label}</th>`).join("");
  }

  function buildTable(data) {
    lastData = data;
    const container = document.getElementById("tab-costs");
    if (!data || !data.total) {
      container.innerHTML = `<p class="muted">${window.i18n.t("session.costs_none")}</p>`;
      return;
    }

    let html = '<table class="data-table costs-table"><thead><tr>';
    html += headerCells();
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
      const msg = window.i18n.t("session.costs_error", { msg: e.message });
      container.innerHTML = `<p class="error">${msg}</p>`;
    }
  }

  // Redessin sur bascule de langue, appelé par l'unique gestionnaire de session.js : ce
  // module est une IIFE, `lastData` ne lui est pas accessible autrement.
  window.redrawCosts = () => { if (lastData) buildTable(lastData); };

  // Hook into tab switching
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".tab[data-tab='costs']").forEach((btn) => {
      btn.addEventListener("click", loadCosts);
    });
  });
})();
