# navigateur

## Purpose
Installer (ou reutiliser) sur la VM un Chromium headless pilotable par Playwright, tout venant de l'Artifactory :
Playwright + Node (`nodejs-wheel-binaries`), `@sparticuz/chromium` (npm), NSS/NSPR (conda-forge).

## Usage
`python3.11 installer_navigateur.py <cache> <index_pip> <npm> <conda> <suffixe> [version_playwright]`
-> derniere ligne `BZ_NAVIGATEUR|{PLAYWRIGHT_BROWSERS_PATH, PLAYWRIGHT_NODEJS_PATH, ...}`.
