// [desc] Rafraîchissement périodique robuste (cadence rapide/lente, backoff, pause onglet caché) et détecteur « connexion perdue » (R7, R8). [/desc]
//
// poller(fn, opts) remplace les setInterval/setTimeout faits main :
//   - UNE seule exécution en vol : un now() pendant une exécution est COALESCÉ et rejoué
//     juste après (le « poll relancé après un envoi » n'est plus jamais perdu) ;
//   - cadence rapide tant que `isFast(résultat)` (ou fast(true)) dit qu'un agent tourne ;
//   - backoff exponentiel sur erreur, remis à zéro au premier succès ;
//   - pause quand l'onglet du navigateur est caché, rattrapage immédiat au retour ;
//   - rattrapage immédiat sur l'événement `ui:online` (retour du serveur).
//
// startConnectionMonitor() : compte les échecs réseau signalés par lib/ui.js::api (événement
// `ui:net`) ; au 2e échec consécutif, lève le bandeau #offline-banner avec un compte à
// rebours, sonde le serveur, et au retour émet `ui:online` (les pollers repartent).

/**
 * @param {() => any} fn  travail à répéter (peut être async ; son résultat est passé à isFast)
 * @param {{interval?:number, fastInterval?:number, isFast?:(res:any)=>boolean,
 *          pauseWhenHidden?:boolean, backoffMax?:number, immediate?:boolean,
 *          onError?:(err:any)=>void, jitter?:number}} [opts]
 *   interval      : cadence normale (défaut 15000 ms)
 *   fastInterval  : cadence rapide (défaut 5000 ms)
 *   isFast        : décide la cadence d'après le résultat de fn
 *   immediate     : start() exécute tout de suite (défaut true)
 *   jitter        : fraction d'aléa sur chaque délai (défaut 0 ; 0.2 = ±20 %). Désynchronise des
 *                   pollers identiques d'onglets différents, partis ensemble (retour du serveur)
 * @returns {{start():void, stop():void, now():Promise<void>, fast(on?:boolean):void,
 *           readonly running:boolean, readonly inFlight:boolean, readonly failures:number}}
 */
export function poller(fn, opts = {}) {
  const {
    interval = 15000, fastInterval = 5000, isFast = null, pauseWhenHidden = true,
    backoffMax = 60000, immediate = true, onError = null, jitter = 0,
  } = opts;
  let timer = null;
  let started = false;
  let inFlight = null;
  let pending = false;
  let fastMode = false;
  let forcedFast = false;
  let failures = 0;

  const hidden = () => pauseWhenHidden && typeof document !== "undefined" && document.visibilityState === "hidden";
  const baseDelay = () => {
    if (failures > 0) return Math.min(backoffMax, (fastMode || forcedFast ? fastInterval : interval) * 2 ** Math.min(failures, 6));
    return fastMode || forcedFast ? fastInterval : interval;
  };
  const nextDelay = () => baseDelay() * (1 + jitter * (2 * Math.random() - 1));
  const schedule = () => {
    clearTimeout(timer);
    timer = null;
    if (!started || hidden()) return;
    timer = setTimeout(run, nextDelay());
  };

  async function run() {
    clearTimeout(timer);
    timer = null;
    if (!started) return;
    if (inFlight) { pending = true; return inFlight; }
    inFlight = (async () => {
      try {
        const res = await fn();
        failures = 0;
        if (isFast) fastMode = !!isFast(res);
      } catch (err) {
        failures += 1;
        if (onError) { try { onError(err); } catch (_) { /* l'observateur ne casse pas la boucle */ } }
      }
    })();
    try { await inFlight; } finally {
      inFlight = null;
      if (pending && started) { pending = false; run(); } else schedule();
    }
  }

  const onVisible = () => {
    if (!started) return;
    if (hidden()) { clearTimeout(timer); timer = null; } else run();
  };
  const onOnline = () => { if (started) { failures = 0; run(); } };

  return {
    start() {
      if (started) return;
      started = true;
      if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisible);
      if (typeof window !== "undefined") window.addEventListener("ui:online", onOnline);
      if (immediate) run(); else schedule();
    },
    stop() {
      started = false;
      clearTimeout(timer);
      timer = null;
      pending = false;
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisible);
      if (typeof window !== "undefined") window.removeEventListener("ui:online", onOnline);
    },
    /** Exécute maintenant (ou juste après l'exécution en cours). */
    now() { return started ? (run() || Promise.resolve()) : Promise.resolve(); },
    /** Force la cadence rapide (true) ou rend la main à isFast (false). */
    fast(on = true) { forcedFast = !!on; if (started && !inFlight) schedule(); },
    get running() { return started; },
    get inFlight() { return !!inFlight; },
    get failures() { return failures; },
  };
}

// ---------------------------------------------------------------- connexion perdue

let monitor = null;

/**
 * Démarre (une fois par page) le détecteur de connexion perdue. Idempotent.
 * @param {{threshold?:number, probeUrl?:string, probeEvery?:number, banner?:HTMLElement|null,
 *          fetchImpl?:typeof fetch}} [opts]
 * @returns {{report(ok:boolean):void, readonly offline:boolean, stop():void}}
 */
export function startConnectionMonitor(opts = {}) {
  if (monitor) return monitor;
  const {
    threshold = 2, probeUrl = "/api/version", probeEvery = 5000,
    fetchImpl = (typeof fetch !== "undefined" ? fetch.bind(globalThis) : null),
  } = opts;
  let banner = opts.banner || (typeof document !== "undefined" ? document.getElementById("offline-banner") : null);
  let consecutive = 0;
  let offline = false;
  let probeTimer = null;
  let tickTimer = null;
  let nextProbeAt = 0;

  const text = () => banner && banner.querySelector("[data-offline-countdown]");
  const render = () => {
    const el = text();
    if (!el) return;
    const s = Math.max(0, Math.ceil((nextProbeAt - Date.now()) / 1000));
    el.textContent = s > 0 ? `nouvel essai dans ${s} s` : "nouvel essai…";
  };
  const show = () => {
    if (!banner && typeof document !== "undefined") banner = document.getElementById("offline-banner");
    if (banner) banner.hidden = false;
    clearInterval(tickTimer);
    tickTimer = setInterval(render, 1000);
    render();
  };
  const hide = () => {
    if (banner) banner.hidden = true;
    clearInterval(tickTimer);
    tickTimer = null;
  };
  const probe = async () => {
    probeTimer = null;
    let ok = false;
    try {
      const r = await fetchImpl(probeUrl, { cache: "no-store" });
      ok = !!r;
    } catch (_) { ok = false; }
    if (ok) goOnline();
    else scheduleProbe();
  };
  const scheduleProbe = () => {
    clearTimeout(probeTimer);
    nextProbeAt = Date.now() + probeEvery;
    probeTimer = setTimeout(probe, probeEvery);
    render();
  };
  const goOffline = () => {
    if (offline) return;
    offline = true;
    show();
    scheduleProbe();
  };
  const goOnline = () => {
    consecutive = 0;
    if (!offline) return;
    offline = false;
    clearTimeout(probeTimer);
    probeTimer = null;
    hide();
    try { window.dispatchEvent(new CustomEvent("ui:online")); } catch (_) { /* hors navigateur */ }
  };
  const report = (ok) => {
    if (ok) { goOnline(); return; }
    consecutive += 1;
    if (consecutive >= threshold) goOffline();
  };
  const onNet = (e) => report(!!(e && e.detail && e.detail.ok));
  if (typeof window !== "undefined") window.addEventListener("ui:net", onNet);
  const retryBtn = banner && banner.querySelector("[data-offline-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => { clearTimeout(probeTimer); probe(); });

  monitor = {
    report,
    get offline() { return offline; },
    stop() {
      if (typeof window !== "undefined") window.removeEventListener("ui:net", onNet);
      clearTimeout(probeTimer);
      clearInterval(tickTimer);
      monitor = null;
    },
  };
  return monitor;
}

export default { poller, startConnectionMonitor };
