// Un ticket dont l'agent est MORT doit pouvoir être relancé DEPUIS L'INTERFACE.
// L'endpoint `POST /api/tickets/<slug>/<id>/launch` existait mais le front ne
// l'appelait JAMAIS : le panneau de conversation n'offrait que Conversation / Recap /
// Détails / boîte de message, et la boîte de message ne convient pas (elle REPREND la
// session — sur une session vide elle l'écrase et l'agent renaît sans worktree valide).
import { beforeEach, describe, expect, it, vi } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../static/js/conversations.js",
);

const KEY = "agent/dead0000111122223333444455556666777788";
const SLUG = "demo-app";
const TICKET = "deadbeef";
const LAUNCH_URL = `/api/tickets/${SLUG}/${TICKET}/launch`;

// Le node de flotte du ticket : mort (state finished, liveness crashed), rattaché à son
// projet et à son ticket. C'est la forme réelle servie par /api/agents/tree.
function deadNode(overrides = {}) {
  return {
    key: KEY,
    parent: null,
    state: "finished",
    liveness: "crashed",
    run_kind: "work",
    title: "Codeur",
    project_slug: SLUG,
    ticket_id: TICKET,
    ...overrides,
  };
}

// Le détail ticket servi par /api/tickets/<slug>/<id> : `liveness_state` vient du
// classifieur partagé (liveness.classify_ticket), `isolation`/`typology` sont ceux
// que la relance doit renvoyer tels quels.
function crashedTicket(overrides = {}) {
  return {
    id: TICKET,
    title: "ticket planté",
    liveness_state: "crashed",
    isolation: "worktree",
    typology: "python-coder",
    ...overrides,
  };
}

function mountDom() {
  document.body.innerHTML = `
    <div id="conv-list"></div>
    <div id="conv-tabs"></div>
    <div id="conv-panels"></div>
    <form id="conv-new-bar">
      <textarea id="conv-new-input"></textarea>
      <button id="conv-new-send" type="button"></button>
    </form>
    <div id="conv-new-error"></div>
  `;
}

// Sert l'arbre, les blocs (état terminal), le détail ticket, et enregistre le POST
// de relance. `launch` décide de la réponse du POST (ok / 500 / jamais résolu).
function installFetch({ node, ticket, launch }) {
  const posts = [];
  global.fetch = vi.fn((url, init) => {
    const target = String(url);
    if (target.includes("/api/agents/tree")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes: [node] }) });
    }
    if (target.includes("/blocks")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ blocks: [], total: 0, status: { state: node.state } }),
      });
    }
    if (target.includes("/partial")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    if (target.endsWith(LAUNCH_URL)) {
      posts.push({ url: target, body: JSON.parse(init.body) });
      return launch();
    }
    if (target.endsWith(`/api/tickets/${SLUG}/${TICKET}`)) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ticket) });
    }
    return Promise.resolve({ ok: false, status: 404, text: () => Promise.resolve("") });
  });
  return posts;
}

async function flush() {
  for (let i = 0; i < 60; i += 1) await Promise.resolve();
}

const ok = (payload) => () => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
const failing = (status, payload) => () => Promise.resolve({
  ok: false, status, text: () => Promise.resolve(JSON.stringify(payload)),
});

// Ouvre la conversation du ticket en onglet et rend son contrôle de relance.
async function openPanel(options) {
  mountDom();
  const posts = installFetch(options);
  vi.resetModules();
  await import(/* @vite-ignore */ `${SCRIPT}?t=${Math.random()}`);
  await flush();
  document.querySelector(`#conv-list .conv-item[data-key="${KEY}"]`).click();
  await flush();
  return { posts, control: document.querySelector(".conv-panel .conv-relaunch") };
}

describe("panneau de conversation — relance d'un ticket mort", () => {
  beforeEach(() => {
    window.confirm = vi.fn(() => true);
  });

  it("n'offre AUCUNE relance sur un ticket vivant", async () => {
    // Double lancement = deux agents concurrents sur le MÊME worktree : jamais de bouton
    // tant qu'un agent tourne, quel que soit ce que raconte le détail ticket.
    const { control, posts } = await openPanel({
      node: deadNode({ state: "running", liveness: "running" }),
      ticket: crashedTicket({ liveness_state: "running" }),
      launch: ok({ key: "agent/neuf" }),
    });

    expect(control.hidden).toBe(true);
    expect(posts).toHaveLength(0);
  });

  it("offre la relance sur un ticket crashé", async () => {
    const { control } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket(),
      launch: ok({ key: "agent/neuf" }),
    });

    expect(control.hidden).toBe(false);
    expect(control.querySelector(".conv-relaunch-btn").textContent).toBe("Relancer");
  });

  it("offre aussi la relance sur un ticket en péril (stalled = rien de commité)", async () => {
    const { control } = await openPanel({
      node: deadNode({ liveness: "delivered" }),
      ticket: crashedTicket({ liveness_state: "stalled" }),
      launch: ok({ key: "agent/neuf" }),
    });

    expect(control.hidden).toBe(false);
  });

  it("offre la relance sur un ticket livré qui attend une décision", async () => {
    // L'issue NORMALE d'un ticket depuis le retrait de la chaîne automatique : le codeur
    // a livré, personne n'a tranché. C'est LÀ qu'on veut relancer avec des objections.
    // Le board l'appelait « stalled » — le mot disait « planté » et l'arbre disait
    // « delivered » au même instant (cas vécu 28/07).
    const { control } = await openPanel({
      node: deadNode({ liveness: "delivered" }),
      ticket: crashedTicket({ liveness_state: "awaiting_decision" }),
      launch: ok({ key: "agent/neuf" }),
    });

    expect(control.hidden).toBe(false);
  });

  it("n'offre pas la relance sur un ticket dont l'issue est actée (delivered)", async () => {
    const { control } = await openPanel({
      node: deadNode({ liveness: "delivered" }),
      ticket: crashedTicket({ liveness_state: "delivered" }),
      launch: ok({ key: "agent/neuf" }),
    });

    expect(control.hidden).toBe(true);
  });

  it("demande CONFIRMATION avant de relancer, et ne poste rien si on refuse", async () => {
    window.confirm = vi.fn(() => false);
    const { control, posts } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket(),
      launch: ok({ key: "agent/neuf" }),
    });

    control.querySelector(".conv-relaunch-btn").click();
    await flush();

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(posts).toHaveLength(0);
  });

  it("poste l'isolation ET la typologie portées par le ticket", async () => {
    // Le serveur repasse par resolve_isolation (garde-fou anti-collision) : envoyer
    // l'isolation DÉJÀ inscrite sur le ticket évite qu'un ticket provisionné en
    // worktree reparte dans le dépôt principal.
    const { control, posts } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket(),
      launch: ok({ key: "agent/neuf" }),
    });

    control.querySelector(".conv-relaunch-btn").click();
    await flush();

    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({ isolation: "worktree", typology: "python-coder" });
  });

  it("retombe sur shared quand le ticket ne porte aucune isolation", async () => {
    const { control, posts } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket({ isolation: undefined, typology: undefined }),
      launch: ok({ key: "agent/neuf" }),
    });

    control.querySelector(".conv-relaunch-btn").click();
    await flush();

    expect(posts[0].body).toEqual({ isolation: "shared", typology: "" });
  });

  it("montre « relance en cours » et NE se laisse PAS cliquer deux fois", async () => {
    // La relance re-provisionne un worktree (~45 s mesuré) : pendant l'attente le bouton
    // ne doit plus être cliquable, sinon deux agents naissent sur le même ticket.
    const { control, posts } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket(),
      launch: () => new Promise(() => {}),
    });
    const button = control.querySelector(".conv-relaunch-btn");

    button.click();
    await flush();

    expect(button.textContent).toBe("Relance en cours…");
    expect(button.disabled).toBe(true);
    button.click();
    await flush();
    expect(posts).toHaveLength(1);
  });

  it("ouvre le nouvel agent en onglet quand la relance aboutit", async () => {
    const { control } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket(),
      launch: ok({ key: "agent/relance00001111222233334444555566667777" }),
    });

    control.querySelector(".conv-relaunch-btn").click();
    await flush();

    expect(document.querySelectorAll("#conv-tabs .conv-tab")).toHaveLength(2);
    expect(control.querySelector(".conv-relaunch-btn").textContent).toBe("Relancé ✓");
  });

  it("AFFICHE l'erreur serveur au lieu de l'avaler", async () => {
    const { control } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket(),
      launch: failing(500, { error: "ANTHROPIC_API_KEY manquante" }),
    });

    control.querySelector(".conv-relaunch-btn").click();
    await flush();

    const error = control.querySelector(".conv-relaunch-error").textContent;
    expect(error).toContain("500");
    expect(error).toContain("ANTHROPIC_API_KEY manquante");
    // L'échec n'est pas définitif : le bouton redevient cliquable pour réessayer.
    expect(control.querySelector(".conv-relaunch-btn").disabled).toBe(false);
  });

  it("affiche aussi le refus de sanité API (503)", async () => {
    const { control } = await openPanel({
      node: deadNode(),
      ticket: crashedTicket(),
      launch: failing(503, { error: "API injoignable" }),
    });

    control.querySelector(".conv-relaunch-btn").click();
    await flush();

    expect(control.querySelector(".conv-relaunch-error").textContent).toContain("503");
  });
});
