# Tests JS (harnais intermediaire)

Tests du **vrai JavaScript** de `static/js/` executes dans un **DOM simule**
(happy-dom) via **Vitest**, sans navigateur. Ils occupent la couche intermediaire
entre :

- les tests Flask `test_client` (Python, cote serveur) ;
- et Playwright (navigateur reel, lourd, reserve aux parcours UI critiques).

## Principe

On charge le script global (ex: `conversations.js`) via un `import()` dynamique
apres avoir :

1. monte le DOM attendu (`document.body.innerHTML`) ;
2. mocke `global.fetch` pour repondre aux endpoints (`/api/agents/tree`,
   `/api/sessions/<key>/blocks`) ;
3. neutralise les timers (`vi.useFakeTimers`) car le module lance `refreshList()`
   et `setInterval` au chargement.

Comme le script n'exporte rien (fonctions locales au module), on teste via le
**DOM et les evenements** (clics), pas en appelant les fonctions directement.

## Lancer

```bash
npm install      # une fois, depuis src/bouzecode/web_v2/
npm test         # vitest run
```

### Sans installer Node localement (Docker)

Depuis `src/bouzecode/web_v2/`, sans rien installer sur la machine :

```bash
npm run test:docker
```

Ce script lance l'image officielle `node:22`, installe les deps et execute les
tests dans un conteneur ephemere :

```bash
docker run --rm -v "${PWD}:/app" -w /app node:22 sh -c "npm ci && npm test"
```
