// [desc] Home: ajout de projet, refresh des badges projets, sessions récentes hors projet. [/desc]
"use strict";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

document.getElementById("proj-add").addEventListener("click", async () => {
  const name = document.getElementById("proj-name").value.trim();
  const path = document.getElementById("proj-path").value.trim();
  if (!name || !path) return;
  const response = await fetch("/api/projects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, path }),
  });
  const data = await response.json();
  if (data.error) { document.getElementById("proj-error").textContent = data.error; return; }
  window.location.reload();
});

async function refreshBadges() {
  const response = await fetch("/api/projects");
  if (!response.ok) return;
  const { projects } = await response.json();
  projects.forEach((project) => {
    const card = document.querySelector(`.project-card[data-slug="${project.slug}"]`);
    if (!card) return;
    const counts = {
      running: project.agents_running, awaiting: project.agents_awaiting,
      review: project.tickets_to_review, ko: project.validations_ko, total: project.tickets_total,
    };
    Object.entries(counts).forEach(([key, value]) => {
      const badge = card.querySelector(`[data-count="${key}"]`);
      if (!badge) return;
      badge.querySelector("b").textContent = value;
      if (key !== "total") badge.hidden = !value;
    });
  });
}

const STATE_LABELS = { running: "en cours", awaiting_input: "question posée", finished: "terminé", cli: "cli" };

async function refreshRecent() {
  const response = await fetch("/api/sessions");
  if (!response.ok) return;
  const data = await response.json();
  const container = document.getElementById("recent-list");
  container.replaceChildren();

  // Merge agents + all CLI sessions into one unified list
  const items = [];
  (data.agents || []).forEach((agent) => {
    items.push({
      key: agent.key,
      title: agent.title,
      subtitle: [agent.model, agent.cwd, agent.started_at].filter(Boolean).join(" · "),
      badge_class: `st-${agent.status.state}`,
      badge_label: STATE_LABELS[agent.status.state] || agent.status.state,
      saved_at: agent.saved_at || agent.started_at || "",
    });
  });
  (data.days || []).forEach((day) => {
    (day.sessions || []).forEach((session) => {
      items.push({
        key: session.key,
        title: session.title,
        subtitle: `${session.model} · ${session.turn_count} tours · ${session.saved_at}`,
        badge_class: "st-cli",
        badge_label: "cli",
        saved_at: session.saved_at || "",
      });
    });
  });

  // Sort by last activity descending
  items.sort((a, b) => (b.saved_at || "").localeCompare(a.saved_at || ""));

  items.slice(0, 20).forEach((item) => {
    const card = el("a", "card");
    card.href = `/sessions/${item.key}`;
    card.appendChild(el("span", `badge ${item.badge_class}`, item.badge_label));
    card.appendChild(el("div", "card-title", item.title));
    card.appendChild(el("div", "muted", item.subtitle));
    container.appendChild(card);
  });
  if (!container.children.length) container.appendChild(el("p", "muted", "Aucune session récente."));
}

refreshRecent();
setInterval(refreshBadges, 8000);
setInterval(refreshRecent, 8000);
