// [desc] Profils : tiroir « Catalogue d'agents » — disponibles / installés, installation, rafraîchissement. [/desc]
import { api, busy, toast, h, skeleton, failed, empty } from "../lib/ui.js";
import { openDrawer } from "./drawer.js";

const $ = (id) => document.getElementById(id);
let afterInstall = async () => {};
let openProfile = () => {};

/** `onInstalled(name)` recharge les profils ; `onOpen(name)` ouvre un profil dans l'éditeur. */
export function initCatalog({ onInstalled, onOpen }) {
  afterInstall = onInstalled;
  openProfile = onOpen;
  $("pf-catalog-open").addEventListener("click", () => openDrawer("pf-catalog", load));
  $("pf-catalog-refresh").addEventListener("click", (e) => refresh(e.currentTarget));
}

async function load() {
  skeleton($("pf-cat-available"), 3);
  skeleton($("pf-cat-installed"), 2);
  try {
    render(await api("GET", "/api/agents/catalog"));
  } catch (err) {
    failed($("pf-cat-available"), err, load, { title: "Catalogue indisponible." });
    $("pf-cat-installed").replaceChildren();
  }
}

function row(agent, installable) {
  const meta = h("div", { class: "pf-cat__meta" },
    h("b", {}, agent.name),
    agent.description ? h("div", { class: "pf-muted" }, agent.description) : null,
    (agent.tools || []).length ? h("div", { class: "pf-muted pf-cat__tools" }, `Outils : ${agent.tools.join(", ")}`) : null);
  let action;
  if (installable) {
    action = h("button", { type: "button", class: "btn btn--sm btn--primary" }, "Installer");
    action.addEventListener("click", () => install(agent.name, action));
  } else {
    action = h("button", { type: "button", class: "btn btn--sm" }, "Ouvrir");
    action.addEventListener("click", () => openProfile(agent.name));
  }
  return h("div", { class: "pf-cat", "data-name": agent.name }, meta, action);
}

function render(data) {
  const avail = data.available || [];
  const inst = data.installed || [];
  if (avail.length) $("pf-cat-available").replaceChildren(...avail.map((a) => row(a, true)));
  else empty($("pf-cat-available"), { title: "Rien de plus à installer.", text: "Tous les agents du catalogue sont déjà installés.", inline: true });
  if (inst.length) $("pf-cat-installed").replaceChildren(...inst.map((a) => row(a, false)));
  else empty($("pf-cat-installed"), { title: "Aucun agent installé depuis le catalogue.", inline: true });
  $("pf-cat-available").removeAttribute("aria-busy");
  $("pf-cat-installed").removeAttribute("aria-busy");
}

async function install(name, btn) {
  await busy(btn, "Installation…", async () => {
    try {
      await api("POST", "/api/agents/install", { name }, { okField: true, timeout: 180000 });
    } catch (err) {
      toast.err(`Installation de « ${name} » impossible : ${err.message}`);
      return;
    }
    toast.ok(`Agent « ${name} » installé.`, { action: { label: "Ouvrir", fn: () => openProfile(name) } });
    await Promise.all([load(), afterInstall(name)]);
  });
}

async function refresh(btn) {
  await busy(btn, "Rafraîchissement…", async () => {
    try {
      render(await api("POST", "/api/agents/catalog/refresh", undefined, { okField: true, timeout: 120000 }));
      toast.ok("Catalogue rafraîchi.");
    } catch (err) {
      // 502 : le catalogue distant n'a pas répondu, mais la vue en cache est dans le corps.
      const vue = err.data && err.data.error && err.data.error.details;  // vue en cache (502)
      if (vue && (vue.available || vue.installed)) render(vue);
      toast.err(`${err.message} La liste affichée est celle en cache.`);
    }
  });
}
