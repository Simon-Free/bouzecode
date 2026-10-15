// Thème : le clair est le défaut ; seul un clic sur ◐ choisit (et mémorise) le sombre.
import { describe, it, expect, vi, beforeEach } from "vitest";

const flush = async (n = 4) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };

async function loadChrome(stored) {
  vi.resetModules();
  localStorage.clear();
  if (stored) for (const [k, v] of Object.entries(stored)) localStorage.setItem(k, v);
  delete document.documentElement.dataset.theme;
  document.body.innerHTML = `<nav><button id="theme-toggle" aria-pressed="false"></button></nav><div id="banners"></div>`;
  global.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 404, headers: { get: () => "application/json" }, json: async () => ({}), text: async () => "{}" }));
  await import("../../static/js/chrome.js");
  await flush();
}

describe("thème", () => {
  beforeEach(() => { document.documentElement.removeAttribute("data-theme"); });

  it("sans choix, la page est claire et rien n'est écrit au chargement", async () => {
    await loadChrome();
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("bz.theme.choix")).toBeNull();
    expect(document.getElementById("theme-toggle").getAttribute("aria-pressed")).toBe("false");
  });

  it("l'ancienne clé « bz.theme=dark » (écrite d'office par l'ancienne version) n'impose plus le sombre", async () => {
    await loadChrome({ "bz.theme": "dark" });
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("◐ passe au sombre, le mémorise, et un second clic revient au clair", async () => {
    await loadChrome();
    const btn = document.getElementById("theme-toggle");
    btn.click();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("bz.theme.choix")).toBe("dark");
    expect(btn.getAttribute("aria-pressed")).toBe("true");
    btn.click();
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("bz.theme.choix")).toBe("light");
  });

  it("un choix sombre mémorisé est rétabli au chargement suivant", async () => {
    await loadChrome({ "bz.theme.choix": "dark" });
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
