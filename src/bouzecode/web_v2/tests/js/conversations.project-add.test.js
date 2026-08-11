import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

// Ouvrir un projet DEPUIS L'INTERFACE. `POST /api/projects` a toujours existé, mais aucun
// bouton ne l'appelait : seul un agent pouvait enregistrer un projet, et un serveur neuf —
// zéro projet — laissait la page Conversations sans issue (bannière vide, dispatch qui
// répond needs_project sans rien à suggérer).
//
// On attaque le module par le DOM, comme le reste du harnais : on monte le gabarit de la
// bannière, on remplit les champs, on clique, et on regarde ce qui est parti sur le réseau.

const MODULE = "../../static/js/conversations/composer/project.js";

function mountDom() {
  document.body.innerHTML = `
    <button id="conv-project-toggle" aria-expanded="false"></button>
    <span id="conv-project-value"></span>
    <div id="conv-project-panel"></div>
    <div id="conv-projects-admin"></div>
  `;
}

function installFetch(onPost) {
  const calls = [];
  global.fetch = vi.fn((url, options) => {
    calls.push({ url, options });
    if (options && options.method === "POST") return Promise.resolve(onPost());
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ projects: [] }) });
  });
  return calls;
}

async function flush() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

async function loadBanner() {
  mountDom();
  vi.resetModules();
  const module = await import(/* @vite-ignore */ `${MODULE}?t=${Math.random()}`);
  await module.loadProjects();
  await flush();
  return module;
}

function fillForm({ name, path, description }) {
  const inputs = Array.from(document.querySelectorAll(".conv-projects-admin-input"));
  expect(inputs).toHaveLength(3);
  [name, path, description].forEach((value, i) => { inputs[i].value = value ?? ""; });
  document.querySelector(".conv-projects-admin-btn").click();
}

const errorText = () => document.querySelector(".conv-projects-admin-error").textContent;

beforeEach(() => { try { localStorage.clear(); } catch (_e) { /* env sans stockage */ } });
afterEach(() => { vi.restoreAllMocks(); });

describe("bannière projet — ouvrir un projet depuis l'interface", () => {
  it("le formulaire est rendu sous la liste des projets", async () => {
    installFetch(() => ({ ok: true, json: () => Promise.resolve({}) }));
    await loadBanner();

    const host = document.getElementById("conv-projects-admin");
    expect(host.querySelectorAll(".conv-projects-admin-input")).toHaveLength(3);
    expect(host.querySelector(".conv-projects-admin-btn").textContent).toBe("Add");
    // Les champs s'annoncent aux lecteurs d'écran, pas seulement en placeholder.
    const labels = Array.from(host.querySelectorAll(".conv-projects-admin-input"))
      .map((i) => i.getAttribute("aria-label"));
    expect(labels).toEqual(["name", "absolute path", "description (optional)"]);
  });

  it("envoie {name, path, description} sur POST /api/projects", async () => {
    const calls = installFetch(() => ({
      ok: true,
      json: () => Promise.resolve({ slug: "demo-app", name: "demo-app" }),
    }));
    await loadBanner();

    fillForm({ name: " demo-app ", path: " /srv/demo-app ", description: " la démo " });
    await flush();

    const post = calls.find((c) => c.options && c.options.method === "POST");
    expect(post.url).toBe("/api/projects");
    expect(JSON.parse(post.options.body))
      .toEqual({ name: "demo-app", path: "/srv/demo-app", description: "la démo" });
  });

  it("recharge la liste des projets après un ajout réussi", async () => {
    const calls = installFetch(() => ({ ok: true, json: () => Promise.resolve({ slug: "demo-app" }) }));
    await loadBanner();
    const before = calls.filter((c) => !c.options).length;

    fillForm({ name: "demo-app", path: "/srv/demo-app" });
    await flush();

    expect(calls.filter((c) => !c.options).length).toBe(before + 1);
    expect(errorText()).toBe("");
  });

  it("refuse un formulaire incomplet sans appeler le serveur", async () => {
    const calls = installFetch(() => ({ ok: true, json: () => Promise.resolve({}) }));
    await loadBanner();

    fillForm({ name: "demo-app", path: "   " });
    await flush();

    expect(calls.some((c) => c.options && c.options.method === "POST")).toBe(false);
    expect(errorText()).toBe("Both the name and the path are required.");
  });

  it("montre le refus du serveur au lieu de l'avaler", async () => {
    installFetch(() => ({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ error: "dossier introuvable: /nowhere" }),
    }));
    await loadBanner();

    fillForm({ name: "demo-app", path: "/nowhere" });
    await flush();

    expect(errorText()).toBe("dossier introuvable: /nowhere");
  });
});
