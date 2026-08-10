// [desc] Onglet Tours: tableau des appels LLM + drill-down payload annoté cache. [/desc]
"use strict";

let turnsLoaded = false;

function tcell(row, text, cls) {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (cls) cell.className = cls;
  row.appendChild(cell);
}

function fmtTokens(n) { return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n); }

async function showTurnDetail(turn, container) {
  const response = await fetch(`/api/sessions/${SESSION_KEY}/turns/${turn}`);
  const detail = await response.json();
  container.replaceChildren();
  if (detail.error) { container.textContent = detail.error; return; }
  const summary = document.createElement("div");
  summary.className = "turn-summary";
  summary.textContent =
    `Tour ${detail.turn} — ${detail.wire_message_count} messages envoyés · ` +
    `in ${fmtTokens(detail.input_tokens)} (cache lu ${fmtTokens(detail.cache_read)}, ` +
    `écrit ${fmtTokens(detail.cache_create)}) · out ${fmtTokens(detail.output_tokens)}`;
  container.appendChild(summary);

  detail.items.forEach((item) => {
    const block = document.createElement("details");
    block.className = `payload-item cs-${item.cache_status}`;
    const head = document.createElement("summary");
    head.innerHTML =
      `<span class="badge cs-badge">${item.cache_label}</span> ` +
      `<span class="pi-kind">${item.kind}</span> ` +
      `<span class="pi-label"></span> <span class="muted">${fmtTokens(item.est_tokens)} tok</span>`;
    head.querySelector(".pi-label").textContent = item.label;
    block.appendChild(head);
    const body = document.createElement("pre");
    body.className = "code";
    body.textContent = item.content || item.preview || "(aperçu vide)";
    block.appendChild(body);
    container.appendChild(block);
  });

  const responseTitle = document.createElement("h3");
  responseTitle.textContent = "Réponse du modèle";
  container.appendChild(responseTitle);
  const responseBox = document.createElement("div");
  responseBox.innerHTML = detail.response_html;
  container.appendChild(responseBox);
  container.scrollIntoView({ block: "nearest" });
}

async function loadTurns() {
  if (turnsLoaded) return;
  turnsLoaded = true;
  const container = document.getElementById("tab-turns");
  const response = await fetch(`/api/sessions/${SESSION_KEY}/turns`);
  const data = await response.json();
  container.replaceChildren();
  if (data.note) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = data.note;
    container.appendChild(note);
  }
  if (!data.calls || !data.calls.length) return;
  const info = document.createElement("p");
  info.className = "muted";
  info.textContent = `system prompt ≈ ${fmtTokens(data.system_prompt_tokens)} tok · coût total ≈ $${data.total_cost}` +
    (data.missing_dumps ? " · dumps de payload absents (drill-down indisponible)" : "");
  container.appendChild(info);

  const table = document.createElement("table");
  table.className = "turns-table";
  table.innerHTML = "<thead><tr><th>tour</th><th>heure</th><th>Δ s</th><th>in</th><th>out</th>" +
    "<th>cache lu</th><th>cache écrit</th><th>% hit</th><th>$</th><th>outils</th></tr></thead>";
  const body = document.createElement("tbody");
  const detailPane = document.createElement("div");
  detailPane.id = "turn-detail";
  data.calls.forEach((call) => {
    const row = document.createElement("tr");
    tcell(row, call.turn); tcell(row, call.time);
    tcell(row, call.delta_s === null ? "—" : call.delta_s, call.delta_s > 60 ? "warn" : "");
    tcell(row, fmtTokens(call.input_tokens)); tcell(row, fmtTokens(call.output_tokens));
    tcell(row, fmtTokens(call.cache_read)); tcell(row, fmtTokens(call.cache_create));
    tcell(row, `${call.cache_hit_pct}%`, call.cache_hit_pct < 50 ? "warn" : "ok");
    tcell(row, call.cost); tcell(row, call.tools.join(", "));
    row.addEventListener("click", () => showTurnDetail(call.turn, detailPane));
    body.appendChild(row);
  });
  table.appendChild(body);
  container.appendChild(table);
  container.appendChild(detailPane);
}
