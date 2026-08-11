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
  summary.textContent = window.i18n.t("session.turn_summary", {
    turn: detail.turn,
    messages: detail.wire_message_count,
    input: fmtTokens(detail.input_tokens),
    read: fmtTokens(detail.cache_read),
    write: fmtTokens(detail.cache_create),
    output: fmtTokens(detail.output_tokens),
  });
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
    body.textContent = item.content || item.preview || window.i18n.t("session.preview_empty");
    block.appendChild(body);
    container.appendChild(block);
  });

  const responseTitle = document.createElement("h3");
  responseTitle.textContent = window.i18n.t("session.model_response");
  container.appendChild(responseTitle);
  const responseBox = document.createElement("div");
  responseBox.innerHTML = detail.response_html;
  container.appendChild(responseBox);
  container.scrollIntoView({ block: "nearest" });
}

// En-tête du tableau. « Δ s », « in », « out », « % hit » et « $ » s'écrivent pareil dans les
// deux langues : les mettre au dictionnaire n'ajouterait que des clés à maintenir.
function turnsTableHead() {
  const labels = [
    window.i18n.t("session.th_turn"), window.i18n.t("session.th_time"), "Δ s", "in", "out",
    window.i18n.t("session.th_cache_read"), window.i18n.t("session.th_cache_write"),
    "% hit", "$", window.i18n.t("session.th_tools"),
  ];
  const head = document.createElement("thead");
  const row = document.createElement("tr");
  labels.forEach((text) => {
    const th = document.createElement("th");
    th.textContent = text;
    row.appendChild(th);
  });
  head.appendChild(row);
  return head;
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
  info.textContent = window.i18n.t("session.turns_info", {
    tokens: fmtTokens(data.system_prompt_tokens), cost: data.total_cost,
  }) + (data.missing_dumps ? ` · ${window.i18n.t("session.turns_no_dumps")}` : "");
  container.appendChild(info);

  const table = document.createElement("table");
  table.className = "turns-table";
  table.appendChild(turnsTableHead());
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
