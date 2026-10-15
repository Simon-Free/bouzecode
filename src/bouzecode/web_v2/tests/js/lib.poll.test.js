import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// lib/poll.js : cadence rapide/lente, coalescence du « poll relancé après un envoi »
// (bug D2 de l'audit Conversations), backoff, pause d'onglet caché, et détecteur
// « connexion perdue » (R7).

import { poller, startConnectionMonitor } from "../../static/js/lib/poll.js";

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe("poller()", () => {
  it("exécute tout de suite puis à la cadence normale", async () => {
    const fn = vi.fn();
    const p = poller(fn, { interval: 1000 });
    p.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(fn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(fn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2);
    expect(fn).toHaveBeenCalledTimes(2);
    p.stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("isFast bascule en cadence rapide", async () => {
    let fast = true;
    const fn = vi.fn(() => ({ running: fast }));
    const p = poller(fn, { interval: 10000, fastInterval: 500, isFast: (r) => r.running });
    p.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(501);
    expect(fn).toHaveBeenCalledTimes(2);
    fast = false;
    await vi.advanceTimersByTimeAsync(501);
    expect(fn).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(5000);
    expect(fn).toHaveBeenCalledTimes(3);
    p.stop();
  });

  it("now() pendant une exécution est coalescé et rejoué juste après (jamais perdu)", async () => {
    let release;
    const fn = vi.fn(() => new Promise((r) => { release = r; }));
    const p = poller(fn, { interval: 60000 });
    p.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(p.inFlight).toBe(true);
    p.now();
    p.now();
    expect(fn).toHaveBeenCalledTimes(1);
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(fn).toHaveBeenCalledTimes(2); // un seul rejeu malgré deux now()
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(fn).toHaveBeenCalledTimes(2);
    p.stop();
  });

  it("backoff sur erreur puis retour à la normale", async () => {
    let fail = true;
    const onError = vi.fn();
    const fn = vi.fn(() => { if (fail) throw new Error("x"); });
    const p = poller(fn, { interval: 1000, backoffMax: 8000, onError });
    p.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(p.failures).toBe(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(fn).toHaveBeenCalledTimes(1); // 2 s de backoff, pas 1 s
    await vi.advanceTimersByTimeAsync(2);
    expect(fn).toHaveBeenCalledTimes(2);
    expect(onError).toHaveBeenCalledTimes(2);
    fail = false;
    await vi.advanceTimersByTimeAsync(4001);
    expect(p.failures).toBe(0);
    const n = fn.mock.calls.length;
    await vi.advanceTimersByTimeAsync(1001);
    expect(fn.mock.calls.length).toBe(n + 1);
    p.stop();
  });

  it("se met en pause onglet caché et rattrape au retour", async () => {
    const fn = vi.fn();
    let state = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
    const p = poller(fn, { interval: 1000 });
    p.start();
    await vi.advanceTimersByTimeAsync(0);
    state = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(10000);
    expect(fn).toHaveBeenCalledTimes(1);
    state = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fn).toHaveBeenCalledTimes(2);
    p.stop();
    state = "visible";
  });

  it("repart immédiatement sur ui:online", async () => {
    const fn = vi.fn();
    const p = poller(fn, { interval: 60000 });
    p.start();
    await vi.advanceTimersByTimeAsync(0);
    window.dispatchEvent(new CustomEvent("ui:online"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fn).toHaveBeenCalledTimes(2);
    p.stop();
  });
});

describe("startConnectionMonitor()", () => {
  it("bandeau au 2e échec, sonde, puis ui:online au retour", async () => {
    document.body.innerHTML = `<div id="offline-banner" hidden><span data-offline-countdown></span><button data-offline-retry></button></div>`;
    let up = false;
    const fetchImpl = vi.fn(() => (up ? Promise.resolve({ ok: true }) : Promise.reject(new TypeError("down"))));
    const online = vi.fn();
    window.addEventListener("ui:online", online);
    const m = startConnectionMonitor({ fetchImpl, probeEvery: 1000 });
    const banner = document.getElementById("offline-banner");

    window.dispatchEvent(new CustomEvent("ui:net", { detail: { ok: false } }));
    expect(banner.hidden).toBe(true); // un seul échec : pas d'alarme
    window.dispatchEvent(new CustomEvent("ui:net", { detail: { ok: false } }));
    expect(banner.hidden).toBe(false);
    expect(m.offline).toBe(true);
    expect(banner.querySelector("[data-offline-countdown]").textContent).toMatch(/nouvel essai dans 1 s/);

    await vi.advanceTimersByTimeAsync(1001);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(banner.hidden).toBe(false);

    up = true;
    await vi.advanceTimersByTimeAsync(1001);
    expect(banner.hidden).toBe(true);
    expect(m.offline).toBe(false);
    expect(online).toHaveBeenCalledTimes(1);

    // Une réponse réussie remet le compteur à zéro
    window.dispatchEvent(new CustomEvent("ui:net", { detail: { ok: false } }));
    window.dispatchEvent(new CustomEvent("ui:net", { detail: { ok: true } }));
    window.dispatchEvent(new CustomEvent("ui:net", { detail: { ok: false } }));
    expect(banner.hidden).toBe(true);

    window.removeEventListener("ui:online", online);
    m.stop();
  });

  it("« Réessayer maintenant » sonde tout de suite", async () => {
    document.body.innerHTML = `<div id="offline-banner" hidden><span data-offline-countdown></span><button data-offline-retry></button></div>`;
    const fetchImpl = vi.fn(() => Promise.resolve({ ok: true }));
    const m = startConnectionMonitor({ fetchImpl, probeEvery: 60000 });
    m.report(false); m.report(false);
    document.querySelector("[data-offline-retry]").click();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(m.offline).toBe(false);
    m.stop();
  });
});
