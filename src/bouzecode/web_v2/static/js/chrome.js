// [desc] Chrome commun à toutes les pages : thème, pastilles de nav + titre d'onglet, bandeaux API/dérive/connexion, redémarrage serveur. [/desc]
//
// Chargé par base.html sur chaque page. Remplace les scripts inline de l'ancien base.html.
// SPEC.md §3 et règles R7 (connexion perdue), R12 (titre d'onglet avec compteur).

import { api, busy, toast, confirm as askConfirm, hhmm } from "./lib/ui.js";
import { poller, startConnectionMonitor } from "./lib/poll.js";

//  Clé d'un CHOIX EXPLICITE (clic sur ◐). L'ancienne clé « bz.theme » était réécrite à chaque
//  chargement avec le défaut sombre : la relire imposerait le sombre à tout le monde. Elle est ignorée.
const THEME_KEY = "bz.theme.choix";

// ---------------------------------------------------------------- thème

function storedTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch (_) { return null; }
}

//  Clair = défaut (aucun attribut) ; sombre = data-theme="dark". `remember` n'est vrai que pour un
//  geste de l'utilisateur : le chargement de page n'écrit jamais rien.
export function applyTheme(theme, { remember = false } = {}) {
  const t = theme === "dark" ? "dark" : "light";
  if (t === "dark") document.documentElement.dataset.theme = "dark";
  else delete document.documentElement.dataset.theme;
  // Stockage indisponible (navigation privée) : le thème s'applique mais n'est pas mémorisé.
  if (remember) {
    try { localStorage.setItem(THEME_KEY, t); } catch (_) { document.documentElement.dataset.themeUnsaved = "true"; }
  }
  const btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.setAttribute("aria-pressed", t === "dark" ? "true" : "false");
    btn.title = t === "light" ? "Passer au thème sombre" : "Passer au thème clair";
  }
  return t;
}

function wireTheme() {
  applyTheme(storedTheme() === "dark" ? "dark" : "light");
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.addEventListener("click", () => applyTheme(
    document.documentElement.dataset.theme === "dark" ? "light" : "dark", { remember: true }));
}

// ---------------------------------------------------------------- pastilles + titre

const baseTitle = document.title;

/** Met à jour les pastilles de nav et le titre de l'onglet (R12). Exporté pour les pages. */
function paintNavCount(el, n) {
  el.textContent = n > 0 ? String(n) : "";
  const link = el.closest("a");
  if (!link) return;
  const label = link.dataset.label || link.textContent.replace(/\d+$/, "").trim();
  link.dataset.label = label;
  link.setAttribute("aria-label", n > 0 ? `${label} (${n})` : label);
}

export function setNavCounts(counts) {
  const c = counts || {};
  for (const el of document.querySelectorAll("[data-nav-count]")) paintNavCount(el, Number(c[el.dataset.navCount]) || 0);
  const aMoi = Number(c.a_moi) || 0;
  document.title = aMoi > 0 ? `(${aMoi}) ${baseTitle}` : baseTitle;
}

//  Les pastilles sont les MÊMES dans tous les onglets : un onglet qui vient de les lire les
//  partage aux autres, qui sautent alors leur propre lecture. Sans ça, chaque onglet ouvert
//  (Bureau + Agents…) interrogeait /api/nav/counts, et leurs pollers, repartis ENSEMBLE au
//  retour du serveur (`ui:online`), tombaient à la même seconde à chaque tick — le doublon
//  relevé dans le journal du serveur le 2026-09-29.
export const CANAL_PASTILLES = "bz.nav-counts";
const PASTILLES_MS = 15000;

function canalPastilles() {
  try { return typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(CANAL_PASTILLES) : null; } catch (_) { return null; }
}

function wireNavCounts() {
  let disabled = false;
  let recuA = 0;        // instant où un AUTRE onglet nous a passé les pastilles
  let explicite = false; // lecture demandée après un geste : jamais sautée
  const canal = canalPastilles();
  if (canal) {
    canal.onmessage = (e) => {
      if (!e.data || !e.data.counts) return;
      recuA = Date.now();
      setNavCounts(e.data.counts);
    };
  }
  const p = poller(async () => {
    if (disabled) return;
    const demandee = explicite;
    explicite = false;
    if (!demandee && Date.now() - recuA < PASTILLES_MS * 0.8) return;
    try {
      const counts = await api("GET", "/api/nav/counts", undefined, { timeout: 10000 });
      setNavCounts(counts);
      if (canal) canal.postMessage({ counts });
    } catch (e) {
      if (e.status === 404) { disabled = true; p.stop(); setNavCounts({}); return; }
      throw e;
    }
  }, { interval: PASTILLES_MS, jitter: 0.2 });
  p.start();
  // Une page peut demander un rafraîchissement immédiat après une action (ex. question répondue).
  window.addEventListener("ui:counts-changed", () => {
    if (disabled) return;
    explicite = true;
    p.now();
  });
  return p;
}

// ---------------------------------------------------------------- bandeau API

function envHeadline(data) {
  const fournisseur = data.provider_label || "du modèle";
  return data.env_missing
    ? `API ${fournisseur} : configuration incomplète — les agents ne peuvent pas démarrer. Complète l'environnement du serveur puis redémarre-le.`
    : `API ${fournisseur} injoignable (réseau ou proxy). La configuration est bonne : revérifie, inutile de redémarrer.`;
}

function renderEnv(data, { rechecked = false } = {}) {
  const banner = document.getElementById("env-sanity-banner");
  if (!banner) return;
  const headline = document.getElementById("env-sanity-headline");
  const detail = document.getElementById("env-sanity-detail");
  const when = document.getElementById("env-sanity-when");
  if (!data || data.ok !== false) {
    banner.hidden = true;
    if (rechecked) toast.ok("API de nouveau disponible.");
    return;
  }
  headline.textContent = envHeadline(data);
  detail.textContent = data.detail ? ` (${data.detail})` : "";
  if (when) when.textContent = rechecked ? `Revérifié à ${hhmm()} — toujours indisponible.` : "";
  banner.hidden = false;
}

function wireEnvSanity() {
  const p = poller(async () => { renderEnv(await api("GET", "/api/env-sanity", undefined, { timeout: 15000 })); },
    { interval: 40000 });
  p.start();
  const btn = document.getElementById("env-sanity-recheck");
  if (btn) {
    btn.addEventListener("click", () => busy(btn, "Revérification…", async () => {
      try {
        renderEnv(await api("POST", "/api/env-sanity/recheck", undefined, { timeout: 30000 }), { rechecked: true });
      } catch (e) {
        toast.err(`Revérification impossible : ${e.message}`);
      }
    }));
  }
}

// ---------------------------------------------------------------- dérive de version + redémarrage

function wireVersion() {
  const banner = document.getElementById("version-drift-banner");
  const detail = document.getElementById("version-drift-detail");
  if (!banner) return;
  const p = poller(async () => {
    const data = await api("GET", "/api/version", undefined, { timeout: 15000 });
    if (data && data.drift) {
      const causes = [];
      if (data.sha_drift) causes.push(`boot ${(data.boot_sha || "").slice(0, 8)} → HEAD ${(data.current_head_sha || "").slice(0, 8)}`);
      if (data.source_drift) causes.push("fichiers source modifiés depuis le démarrage");
      detail.textContent = causes.length ? ` (${causes.join(" ; ")})` : "";
      banner.hidden = false;
      const btn = document.getElementById("server-restart");
      if (btn && data.code_root) btn.title = `Redémarre le serveur sur le code de ${data.code_root}`;
    } else {
      banner.hidden = true;
    }
  }, { interval: 40000 });
  p.start();
}

const RESTART_BUDGET_MS = 90000;

async function waitForServer(state, startedAt) {
  await new Promise((r) => setTimeout(r, 1500));
  while (Date.now() - startedAt < RESTART_BUDGET_MS) {
    state.textContent = `Redémarrage… (${Math.round((Date.now() - startedAt) / 1000)} s)`;
    // Connexion refusée = le successeur n'écoute pas encore : on repasse dans 1 s.
    const back = await api("GET", "/api/version", undefined, { timeout: 2000 }).then(() => true, () => false);
    if (back) {
      state.textContent = "Serveur revenu, rechargement…";
      location.reload();
      return true;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

function wireRestart() {
  const btn = document.getElementById("server-restart");
  const state = document.getElementById("server-restart-state");
  if (!btn || !state) return;
  btn.addEventListener("click", async () => {
    const ok = await askConfirm({
      title: "Redémarrer le serveur ?",
      text: "La page se rechargera toute seule quand il sera revenu (quelques secondes). "
        + "Les agents en cours continuent de tourner.",
      confirmLabel: "Redémarrer",
    });
    if (!ok) return;
    await busy(btn, "Redémarrage…", async () => {
      const startedAt = Date.now();
      try {
        await api("POST", btn.dataset.endpoint || "/api/server/restart", undefined, { timeout: 10000 });
      } catch (e) {
        // Le serveur peut couper la connexion en mourant juste après avoir répondu : seul un
        // refus HTTP explicite (status > 0) est un échec.
        if (e.status > 0) {
          toast.err(`Redémarrage refusé : ${e.message}`);
          return;
        }
      }
      const back = await waitForServer(state, startedAt);
      if (!back) {
        state.textContent = "";
        toast.err("Le serveur n'est pas revenu après 90 s : relance-le à la main avec son lanceur (bouzeui).");
      }
    });
  });
}

// ---------------------------------------------------------------- démarrage

export function initChrome() {
  wireTheme();
  startConnectionMonitor();
  wireNavCounts();
  wireEnvSanity();
  wireVersion();
  wireRestart();
}

if (typeof document !== "undefined" && !window.__bzChromeNoAutoInit) {
  initChrome();
}
