import { defineConfig } from "vitest/config";

// Harnais JS intermediaire : execute le vrai JavaScript de static/js/ dans un DOM
// simule (happy-dom), sans navigateur. Sert a tester la logique UI (onglets,
// filtre, clics) avec fetch mocke, entre le test_client Flask et Playwright.
export default defineConfig({
  test: {
    environment: "happy-dom",
    include: ["tests/js/**/*.test.js"],
    globals: true,
  },
});
