// [desc] Bouton « Relancer » du panneau de conversation : seule affordance UI pour
// remettre en marche un ticket dont l'agent est MORT (POST .../launch). [/desc]
//
// Pourquoi un endpoint dédié plutôt que la boîte de message : envoyer un message
// REPREND la session de l'agent. Sur une session vide (agent mort avec 0 bloc,
// returncode=-1) la reprise écrase la session et l'agent renaît SANS worktree
// valide. `POST /api/tickets/<slug>/<id>/launch` est le seul chemin qui
// re-provisionne l'isolation (dispatch.reisolate) et purge les drapeaux terminaux.

// États de vivacité du TICKET (services/work/liveness.py::classify_ticket) pour
// lesquels une relance a du sens. `classify_ticket` renvoie 'running' dès qu'UN run
// est encore vivant : ces états prouvent donc déjà qu'aucun agent ne tourne.
// On ne se fie PAS au statut dérivé affiché (derive_status mélange plusieurs notions,
// `done` y prime et masque `crashed`).
//
// `awaiting_decision` a repris ce que `stalled` désignait jusqu'ici : le codeur a livré
// et personne n'a encore tranché — c'est l'issue NORMALE de tout ticket depuis le retrait
// de la chaîne automatique, et le moment exact où l'on veut pouvoir relancer l'agent avec
// des objections. `stalled` ne reste que pour l'anomalie « livré, rien de commité », tout
// aussi relançable. `delivered` = issue ACTÉE (mergé/verdict) : pas de bouton.
//
// `missing` = l'enregistrement de l'agent a disparu du parc : il est INJOIGNABLE (tout
// message échoue). Relançable au même titre que `crashed` — un nouvel agent est la porte
// de sortie quand la fiche n'est pas restaurable. Il était jusqu'ici confondu avec
// `crashed` ; le nommer ne doit pas lui retirer son seul bouton.
export const RELAUNCHABLE_STATES = new Set([
  "crashed", "stalled", "awaiting_decision", "missing",
]);

// États du panneau qui prouvent un agent ENCORE EN VIE. Garde-fou de ceinture :
// un double lancement ferait travailler deux agents concurrents sur le même worktree.
const LIVE_PANEL_STATES = new Set(["running", "awaiting_input", "awaiting_plan_validation"]);

const SHARED = "shared";
const CONFIRM_MESSAGE =
  "Relancer ce ticket ?\n\nUn NOUVEL agent est créé et le worktree est re-provisionné "
  + "(peut prendre ~45 s). L'agent mort n'est pas repris : son travail non commité reste "
  + "dans le worktree.";

// Cible de relance, ou null si la relance n'a PAS de sens. `node` = node de flotte
// (/api/agents/tree : project_slug, ticket_id, liveness), `ticket` = détail ticket
// (/api/tickets/<slug>/<id> : liveness_state, isolation, typology).
export function relaunchTarget(panelState, node, ticket) {
  if (LIVE_PANEL_STATES.has(panelState)) return null;
  if (!node || node.liveness === "running") return null;
  if (!ticket || !RELAUNCHABLE_STATES.has(ticket.liveness_state)) return null;
  const slug = node.project_slug || "";
  const id = ticket.id || node.ticket_id || "";
  if (!slug || !id) return null;
  // L'isolation envoyée est celle DÉJÀ portée par le ticket (un ticket provisionné en
  // worktree doit le rester), sinon 'shared'. Le serveur repasse de toute façon par
  // `resolve_isolation` (garde-fou anti-collision) : on ne le contourne pas.
  return {
    slug,
    id,
    isolation: ticket.isolation || SHARED,
    typology: ticket.typology || "",
  };
}

// Un corps de réponse peut ne PAS être du JSON (500 HTML d'un proxy). On garde alors
// le texte brut comme détail : aucune erreur n'est avalée en silence.
function errorDetail(status, raw) {
  let detail = raw || "";
  if (raw && raw.trim().startsWith("{")) {
    const parsed = JSON.parse(raw);
    detail = parsed.error || raw;
  }
  return `Relance impossible (HTTP ${status})` + (detail ? ` : ${detail}` : "");
}

// Contrôle persistant (créé UNE fois par onglet, comme le segmented control) : il
// survit au replaceChildren de la ligne meta à chaque poll, donc ses listeners et son
// état « relance en cours » aussi. `deps` = { fetch, confirm, onLaunched }.
export function createRelaunchControl(deps) {
  const slot = document.createElement("div");
  slot.className = "conv-relaunch";
  slot.hidden = true;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "conv-relaunch-btn";
  button.textContent = "Relancer";
  button.title = "Créer un nouvel agent sur ce ticket (re-provisionne le worktree)";
  const error = document.createElement("div");
  error.className = "conv-relaunch-error";
  slot.appendChild(button);
  slot.appendChild(error);

  let target = null;
  let busy = false;
  let launched = false;
  // Dernier couple (état de panneau, ticket) déjà sondé : évite un GET ticket à CHAQUE
  // poll (le panneau repoll toutes les 15 s en état terminal).
  let probed = "";

  function show(label, enabled) {
    slot.hidden = false;
    button.textContent = label;
    button.disabled = !enabled;
  }

  function hide() {
    slot.hidden = true;
    error.textContent = "";
  }

  async function relaunch() {
    if (busy || launched || !target) return;
    if (!deps.confirm(CONFIRM_MESSAGE)) return;
    busy = true;
    error.textContent = "";
    // Le POST est SYNCHRONE côté serveur (reisolate + spawn, ~45 s mesuré) : le bouton
    // devient non cliquable pendant toute l'attente, jamais un second lancement.
    show("Relance en cours…", false);
    const response = await deps.fetch(
      `/api/tickets/${target.slug}/${target.id}/launch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ isolation: target.isolation, typology: target.typology }),
      },
    ).catch((exc) => ({ networkError: String((exc && exc.message) || exc) }));
    busy = false;
    if (response.networkError) {
      show("Relancer", true);
      error.textContent = `Relance impossible : ${response.networkError}`;
      return;
    }
    if (!response.ok) {
      const raw = await response.text().catch(() => "");
      show("Relancer", true);
      error.textContent = errorDetail(response.status, raw);
      return;
    }
    const payload = await response.json();
    launched = true;
    show("Relancé ✓", false);
    // La réponse est {"key": "agent/<id>"} : on ouvre le nouvel agent en onglet pour
    // que la relance soit VISIBLE (sinon rien ne bouge à l'écran).
    if (payload && payload.key && deps.onLaunched) deps.onLaunched(payload.key);
  }

  button.addEventListener("click", relaunch);

  // Appelé à chaque renderMeta. Ne sonde le ticket que quand l'état de panneau ou le
  // ticket a CHANGÉ, et jamais pendant/après une relance partie d'ici.
  async function update(panelState, node) {
    if (busy || launched) return;
    const ticketId = (node && node.ticket_id) || "";
    const slug = (node && node.project_slug) || "";
    if (LIVE_PANEL_STATES.has(panelState) || !slug || !ticketId
        || (node && node.liveness === "running")) {
      target = null;
      probed = "";
      hide();
      return;
    }
    const stamp = `${panelState}|${slug}/${ticketId}`;
    if (stamp === probed) return;
    probed = stamp;
    const response = await deps.fetch(`/api/tickets/${slug}/${ticketId}`)
      .catch(() => null);
    // Ticket illisible (réseau/404) : pas de bouton, et on redemandera au poll suivant.
    if (!response || !response.ok) {
      probed = "";
      target = null;
      hide();
      return;
    }
    target = relaunchTarget(panelState, node, await response.json());
    if (target) show("Relancer", true); else hide();
  }

  return { slot, update };
}
