# [desc] Profils (/agent-builder), parcours U14 + U16 de SPEC.md, cliqués pour de vrai contre un serveur de bac à sable : signal immédiat, indicateur, résultat, erreur simulée pour chaque action. [/desc]
"""E2E de la page Profils contre un VRAI serveur web_v2 lancé à part (bac à sable).

Pourquoi un navigateur : tout ce qui est prouvé ici est du JavaScript exécuté sur de vrais
gestes (bouton occupé, toast, dialogue, aperçu en direct, garde « modifié », tiroirs,
téléchargement). Les contrats HTTP sont prouvés au client Flask dans
`tests/test_profiles_builder_contrats.py`.

Lancer :
    HOME=/tmp/bz-sb-profils … python -m bouzecode.web_v2 --port 5356   (env -i, cf. tests/sandbox)
    BZ_E2E_URL_PROFILS=http://127.0.0.1:5356 [BZ_E2E_HOME_PROFILS=/tmp/bz-sb-profils] \\
        .venv/bin/python -m pytest src/bouzecode/web_v2/tests/e2e_sandbox/test_profils_e2e.py -m "web or not web"

Sans BZ_E2E_URL_PROFILS, tout le module est SKIPPÉ (jamais un faux vert sur un serveur absent).
Les erreurs serveur/réseau sont simulées par `page.route` : le vrai serveur n'est jamais cassé.
Chaque test crée ses profils sous un nom unique et les supprime à la fin.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid
from pathlib import Path

import pytest
from jeton_e2e import en_tetes

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE = os.environ.get("BZ_E2E_URL_PROFILS", "").rstrip("/")
HOME = os.environ.get("BZ_E2E_HOME_PROFILS", "")
pytestmark = [
    pytest.mark.web,
    pytest.mark.skipif(not BASE, reason="BZ_E2E_URL_PROFILS non défini : pas de serveur de bac à sable"),
    pytest.mark.couvre("static/js/profils/**", "static/css/profils.css", "templates/agent_builder.html",
                       "templates/base.html", "static/js/lib/**", "static/js/chrome.js", "static/ds.css",
                       "routes/work/builder.py", "services/profiles*.py", "services/profile_io.py",
                       "services/skills*.py", "services/plugins*.py"),
]

TOAST_OK = "#toasts .toast[data-kind='ok']"
TOAST_ERR = "#toasts .toast[data-kind='err']"
TOAST_INFO = "#toasts .toast[data-kind='info']"


# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as play:
        try:
            chromium = play.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 — chromium absent → skip, pas échec
            pytest.skip(f"Chromium indisponible : {exc}")
        yield chromium
        chromium.close()


@pytest.fixture()
def ctx(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    yield context
    context.close()


@pytest.fixture()
def page(ctx):
    """Page neuve + journal des erreurs console et des requêtes sortant du serveur local."""
    pg = ctx.new_page()
    pg.errors = []
    pg.external = []
    pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))

    def _req(r):
        if not r.url.startswith(BASE) and not r.url.startswith(("data:", "blob:")):
            pg.external.append(r.url)
    pg.on("request", _req)
    yield pg


def _api(method: str, path: str, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **en_tetes(BASE, method)})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


@pytest.fixture()
def cleanup():
    """Noms de profils / skills à supprimer après le test (via l'API, best-effort dit)."""
    names = {"profiles": [], "skills": []}
    yield names
    for n in names["profiles"]:
        _api("DELETE", f"/api/profiles/{n}")
    for n in names["skills"]:
        _api("DELETE", f"/api/skills/{n}")


def uid(prefix="e2e"):
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def open_page(page, query=""):
    page.goto(f"{BASE}/agent-builder{query}", wait_until="domcontentloaded")
    expect(page.locator("#pf-list .pf-item").first).to_be_visible(timeout=20000)
    expect(page.locator("#pf-preview-state")).to_have_text("À jour", timeout=20000)


def hold(page, pattern, method=None):
    """Retient les requêtes `pattern` (la réponse ne part qu'à `release()`) : permet de voir
    l'état OCCUPÉ pendant qu'une action est en vol, sans dépendre d'un chronométrage."""
    held = []

    def handler(route):
        if method and route.request.method != method:
            route.continue_()
            return
        held.append(route)
    page.route(pattern, handler)

    def release():
        while held:
            held.pop().continue_()
        page.unroute(pattern, handler)
    return held, release


def fail(page, pattern, status=500, body=None, method=None, abort=False):
    def handler(route):
        if method and route.request.method != method:
            route.continue_()
            return
        if abort:
            route.abort("connectionrefused")
        else:
            route.fulfill(status=status, content_type="application/json",
                          body=json.dumps(body if body is not None else {"error": f"panne simulée {status}"}))
    page.route(pattern, handler)
    return lambda: page.unroute(pattern, handler)


def new_named(page, name):
    page.click("#pf-new")
    page.fill("#pf-name", name)
    expect(page.locator("#pf-save")).to_be_enabled()


# ---------------------------------------------------------------- chargement (R2, R4, U16)


def test_chargement_montre_un_squelette_puis_la_liste_sans_erreur(page):
    """Au chargement, la liste affiche un squelette tant que les profils ne sont pas arrivés,
    puis « Mes profils » et « Fournis » ; la page n'émet aucune erreur ni requête externe."""
    held, release = hold(page, "**/api/builder/agents")
    page.goto(f"{BASE}/agent-builder", wait_until="domcontentloaded")
    expect(page.locator("#pf-list .skeleton")).to_be_visible()
    release()
    expect(page.locator("#pf-list .pf-list__group").first).to_contain_text("Mes profils")
    expect(page.locator("#pf-list")).to_contain_text("Fournis")
    expect(page.locator("#pf-preview-state")).to_have_text("À jour", timeout=20000)
    assert page.title().startswith(("Profils", "(")), page.title()
    assert page.errors == [], page.errors
    assert page.external == [], page.external


def test_chargement_en_erreur_propose_reessayer_qui_repare(page):
    """Si la liste des profils ne charge pas, un état d'erreur lisible propose « Réessayer »,
    qui recharge vraiment la page une fois le serveur revenu."""
    undo = fail(page, "**/api/builder/agents", status=500)
    page.goto(f"{BASE}/agent-builder", wait_until="domcontentloaded")
    expect(page.locator("#pf-list .error-state")).to_contain_text("Impossible de charger les profils")
    expect(page.locator(TOAST_ERR)).to_be_visible()
    undo()
    page.locator("#pf-list .error-state button", has_text="Réessayer").click()
    expect(page.locator("#pf-list .pf-item").first).to_be_visible(timeout=20000)


# ---------------------------------------------------------------- créer et enregistrer (U14)


def test_creer_personnaliser_voir_l_apercu_et_enregistrer(page, cleanup):
    """Parcours principal : nom, préréglage, skill, instructions → l'aperçu suit EN DIRECT ;
    Enregistrer est occupé pendant l'envoi, puis toast, profil surligné dans « Mes profils »,
    indicateur « modifié » éteint ; un rechargement retrouve tout."""
    name = uid()
    cleanup["profiles"].append(name)
    open_page(page)
    expect(page.locator("#pf-save")).to_be_disabled()   # rien à enregistrer tant qu'il n'a pas de nom
    page.fill("#pf-name", name)
    expect(page.locator("#pf-dirty")).to_have_text("• modifié")
    expect(page.locator("#pf-title")).to_have_text(name)

    page.click("#pf-presets [data-preset='lecture']")
    expect(page.locator("#pf-presets [data-preset='lecture']")).to_have_attribute("aria-checked", "true")
    expect(page.locator("#pf-preview-state")).to_have_text("Mise à jour…")   # signal immédiat
    expect(page.locator("#pf-preview-state")).to_have_text("À jour", timeout=10000)

    skill = page.evaluate("window.__profils.S.catalog.skills[0] && window.__profils.S.catalog.skills[0].name")
    if skill:
        page.fill("#pf-skills-search", skill)
        expect(page.locator("#pf-skills-suggest")).to_be_visible()
        page.press("#pf-skills-search", "Enter")
        expect(page.locator("#pf-skills-chips .chip")).to_contain_text(skill)

    marker = f"CONSIGNE-{uuid.uuid4().hex[:8]}"
    page.fill("#pf-prompt", f"Toujours répondre en listes. {marker}")
    expect(page.locator("#pf-preview-prompt")).to_contain_text(marker, timeout=10000)

    held, release = hold(page, "**/api/profiles", method="POST")
    page.click("#pf-save")
    expect(page.locator("#pf-save")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#pf-save")).to_be_disabled()
    expect(page.locator("#pf-save")).to_have_text("Enregistrement…")
    release()
    expect(page.locator(TOAST_OK)).to_contain_text(f"Profil « {name} » enregistré")
    item = page.locator(f"#pf-list .pf-item[data-name='{name}']")
    expect(item).to_be_visible()
    expect(item).to_have_attribute("aria-current", "true")
    expect(page.locator("#pf-dirty")).to_have_text("")
    expect(page.locator("#pf-save")).to_be_disabled()
    expect(page.locator("#pf-origin")).to_have_text("Mon profil")
    assert f"profil={name}" in page.url

    page.reload()
    expect(page.locator("#pf-name")).to_have_value(name, timeout=20000)
    expect(page.locator("#pf-prompt")).to_have_value(re.compile(marker))
    expect(page.locator("#pf-presets [data-preset='lecture']")).to_have_attribute("aria-checked", "true")
    assert page.errors == [], page.errors


def test_enregistrer_en_erreur_serveur_garde_la_saisie_et_le_dit(page):
    """Un 500 à l'enregistrement : toast d'erreur persistant, bouton rendu, saisie intacte,
    toujours « modifié »."""
    name = uid()
    open_page(page)
    new_named(page, name)
    page.fill("#pf-prompt", "texte précieux")
    undo = fail(page, "**/api/profiles", status=500, method="POST")
    page.click("#pf-save")
    expect(page.locator(TOAST_ERR)).to_contain_text("Profil non enregistré")
    expect(page.locator("#pf-save")).to_be_enabled()
    expect(page.locator("#pf-prompt")).to_have_value("texte précieux")
    expect(page.locator("#pf-dirty")).to_have_text("• modifié")
    undo()
    assert _api("GET", f"/api/profiles/{name}")[0] == 404


def test_enregistrer_serveur_injoignable_le_dit(page):
    """Réseau coupé pendant l'enregistrement : message « Serveur injoignable », rien de perdu."""
    open_page(page)
    new_named(page, uid())
    fail(page, "**/api/profiles", method="POST", abort=True)
    page.click("#pf-save")
    expect(page.locator(TOAST_ERR)).to_contain_text("injoignable")
    expect(page.locator("#pf-save")).to_be_enabled()


def test_nom_invalide_ou_deja_pris_erreur_sous_le_champ(page):
    """Le nom est vérifié AVANT l'envoi : format invalide ou nom pris → erreur sous le
    champ, focus dessus, aucune requête d'enregistrement."""
    open_page(page)
    posts = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/api/profiles") and posts.append(r))
    new_named(page, "Mauvais Nom")
    page.click("#pf-save")
    expect(page.locator("#pf-name-error")).to_contain_text("Minuscules")
    expect(page.locator("#pf-name")).to_be_focused()
    expect(page.locator("#pf-name")).to_have_attribute("aria-invalid", "true")
    page.fill("#pf-name", "coder")   # profil fourni existant
    page.click("#pf-save")
    expect(page.locator("#pf-name-error")).to_contain_text("existe déjà")
    page.fill("#pf-name", uid())
    expect(page.locator("#pf-name-error")).to_have_text("")   # l'erreur s'efface en tapant
    assert posts == []


def test_creer_un_nom_deja_pris_cote_serveur_repond_409_sous_le_champ(page, cleanup):
    """Course : le nom est pris entre-temps (un autre onglet) → 409 du serveur affiché sous le
    champ, jamais un écrasement du profil existant."""
    name = uid()
    cleanup["profiles"].append(name)
    open_page(page)
    new_named(page, name)
    status, _ = _api("POST", "/api/profiles", {"name": name, "system_prompt_extra": "original"})
    assert status == 200
    page.click("#pf-save")
    expect(page.locator("#pf-name-error")).to_contain_text("existe déjà")
    assert _api("GET", f"/api/profiles/{name}")[1]["system_prompt_extra"] == "original"


# ---------------------------------------------------------------- aperçu en direct


def test_apercu_jamais_perime_et_requetes_obsoletes_annulees(page):
    """Chaque frappe marque l'aperçu « Mise à jour… » (jamais présenté comme à jour à tort) ;
    une rafale de frappes ne produit qu'un calcul, et le dernier texte est bien celui affiché."""
    open_page(page)
    calls = []
    page.on("request", lambda r: r.url.endswith("/api/builder/preview") and calls.append(r))
    page.click("#pf-prompt")
    page.keyboard.type("abcdefghij", delay=30)
    expect(page.locator("#pf-preview-state")).to_have_text("Mise à jour…")
    expect(page.locator("#pf-preview-body")).to_have_class(re.compile("pf-preview__body--stale"))
    expect(page.locator("#pf-preview-prompt")).to_contain_text("abcdefghij", timeout=10000)
    expect(page.locator("#pf-preview-state")).to_have_text("À jour")
    assert len(calls) <= 2, f"{len(calls)} calculs pour une rafale de frappes"


def test_apercu_en_erreur_propose_reessayer(page):
    """Si le calcul échoue : état d'erreur dans l'aperçu + Réessayer, qui répare."""
    open_page(page)
    undo = fail(page, "**/api/builder/preview", status=500)
    page.fill("#pf-prompt", "x")
    expect(page.locator("#pf-preview-body .error-state")).to_contain_text("Impossible de calculer l'aperçu")
    undo()
    page.locator("#pf-preview-body .error-state button").click()
    expect(page.locator("#pf-preview-state")).to_have_text("À jour", timeout=10000)
    expect(page.locator("#pf-preview-prompt")).to_be_visible()


# ---------------------------------------------------------------- profil fourni, duplication


def test_profil_fourni_en_lecture_seule_puis_dupliquer_pour_modifier(page, cleanup):
    """Un profil fourni s'ouvre en lecture (pas d'Enregistrer, champs non modifiables, liste
    d'outils consultable) ; « Dupliquer pour modifier » donne une copie nommée, enregistrable."""
    open_page(page)
    page.click("#pf-list .pf-item[data-name='coder']")
    expect(page.locator("#pf-readonly")).to_be_visible()
    expect(page.locator("#pf-save")).to_be_hidden()
    expect(page.locator("#pf-origin")).to_contain_text("Fourni")
    assert page.locator("#pf-prompt").evaluate("el => el.readOnly")
    page.click("#pf-customize")
    expect(page.locator("#pf-tools-panel")).to_be_visible()
    expect(page.locator("#pf-tools .pf-check input").first).to_be_disabled()
    assert "profil=coder" in page.url

    page.click("#pf-fork")
    expect(page.locator("#pf-readonly")).to_be_hidden()
    expect(page.locator("#pf-name")).to_have_value(re.compile(r"^coder-copie"))
    expect(page.locator("#pf-name")).to_be_focused()
    expect(page.locator("#pf-origin")).to_contain_text("Copie de coder")
    expect(page.locator(TOAST_INFO)).to_contain_text("non enregistrée")
    name = uid("coder-copie")
    cleanup["profiles"].append(name)
    page.fill("#pf-name", name)
    page.click("#pf-save")
    expect(page.locator(TOAST_OK)).to_contain_text(name)
    status, saved = _api("GET", f"/api/profiles/{name}")
    assert status == 200 and "demo" in saved["system_prompt_extra"].lower()


def test_prereglages_reconnus_et_personnalise_des_qu_on_s_en_ecarte(page):
    """Les préréglages Lecture seule / Code / Orchestration cochent chacun leur ensemble d'outils
    (le résumé change de nombre) ; décocher un outil à la main fait passer à « Personnalisé ».
    L'aperçu annonce sa taille en tokens (« ≈ N tokens »)."""
    open_page(page)
    page.click("#pf-new")
    comptes = {}
    for preset in ("lecture", "code", "orchestration"):
        page.click(f"#pf-presets [data-preset='{preset}']")
        expect(page.locator(f"#pf-presets [data-preset='{preset}']")).to_have_attribute("aria-checked", "true")
        comptes[preset] = int(re.match(r"\d+", page.locator("#pf-caps-summary").inner_text()).group())
    assert comptes["lecture"] < comptes["code"] < comptes["orchestration"], comptes
    page.click("#pf-customize")
    page.locator("#pf-tools .pf-check input:checked").first.uncheck()
    expect(page.locator("#pf-presets [data-preset='perso']")).to_have_attribute("aria-checked", "true")
    expect(page.locator("#pf-caps-summary")).to_contain_text(f"{comptes['orchestration'] - 1} outils")
    expect(page.locator("#pf-preview-state")).to_have_text("À jour", timeout=10000)
    expect(page.locator("#pf-preview-meta .chip").first).to_have_text(re.compile(r"^≈ [\d\s\u202f\u00a0]+ tokens$"))


def test_dupliquer_une_copie_n_empile_pas_les_suffixes(page, cleanup):
    """Dupliquer « x-copie » propose « x-copie-2 », jamais « x-copie-copie »."""
    base = f"{uid()}-copie"
    cleanup["profiles"].append(base)
    assert _api("POST", "/api/profiles", {"name": base, "system_prompt_extra": "v1"})[0] == 200
    open_page(page, f"?profil={base}")
    page.click("#pf-duplicate")
    expect(page.locator("#pf-name")).to_have_value(f"{base}-2")


def test_utiliser_ce_profil_mene_aux_agents_avec_le_profil(page):
    """« Utiliser ce profil » pointe vers /conversations?profil=<nom>."""
    open_page(page, "?profil=coder")
    expect(page.locator("#pf-use")).to_have_attribute("href", "/conversations?profil=coder")


def test_profil_demande_dans_l_url_mais_inconnu_le_dit(page):
    open_page(page, "?profil=nexiste-pas-du-tout")
    expect(page.locator(TOAST_ERR)).to_contain_text("introuvable")
    expect(page.locator("#pf-title")).to_have_text("Nouveau profil")


# ---------------------------------------------------------------- garde « modifié » (R9)


def test_changer_de_profil_avec_des_modifications_demande_confirmation(page):
    """Une modification non enregistrée n'est jamais perdue sans le demander : « Continuer
    l'édition » garde tout, « Abandonner » change de profil."""
    open_page(page)
    page.fill("#pf-prompt", "brouillon à ne pas perdre")
    page.click("#pf-list .pf-item[data-name='coder']")
    dialog = page.locator("dialog.ui-dialog")
    expect(dialog).to_contain_text("Abandonner les modifications")
    dialog.locator("[data-role='cancel']").click()
    expect(page.locator("#pf-prompt")).to_have_value("brouillon à ne pas perdre")
    page.click("#pf-list .pf-item[data-name='coder']")
    page.locator("dialog.ui-dialog [data-role='confirm']").click()
    expect(page.locator("#pf-title")).to_have_text("coder")


# ---------------------------------------------------------------- menu ⋯ : supprimer, exporter, importer


def _saved_profile(page, cleanup, extra="", tools=None):
    name = uid()
    cleanup["profiles"].append(name)
    body = {"name": name, "system_prompt_extra": extra or "exporte-moi", "description": "profil de test"}
    if tools is not None:
        body["tools"] = tools
    assert _api("POST", "/api/profiles", body)[0] == 200
    open_page(page, f"?profil={name}")
    return name


def test_supprimer_demande_confirmation_puis_retire_le_profil(page, cleanup):
    name = _saved_profile(page, cleanup)
    page.click("#pf-more")
    page.locator(".menu__item", has_text="Supprimer").click()
    dialog = page.locator("dialog.ui-dialog")
    expect(dialog).to_contain_text(f"Supprimer le profil « {name} »")
    dialog.locator("[data-role='cancel']").click()
    expect(page.locator(f"#pf-list .pf-item[data-name='{name}']")).to_be_visible()
    page.click("#pf-more")
    page.locator(".menu__item", has_text="Supprimer").click()
    page.locator("dialog.ui-dialog [data-role='confirm']").click()
    expect(page.locator(TOAST_OK)).to_contain_text("supprimé")
    expect(page.locator(f"#pf-list .pf-item[data-name='{name}']")).to_have_count(0)
    expect(page.locator("#pf-title")).to_have_text("Nouveau profil")


def test_supprimer_en_erreur_le_dit_et_garde_le_profil(page, cleanup):
    name = _saved_profile(page, cleanup)
    fail(page, f"**/api/profiles/{name}", status=500, method="DELETE")
    page.click("#pf-more")
    page.locator(".menu__item", has_text="Supprimer").click()
    page.locator("dialog.ui-dialog [data-role='confirm']").click()
    expect(page.locator(TOAST_ERR)).to_contain_text("non supprimé")
    expect(page.locator(f"#pf-list .pf-item[data-name='{name}']")).to_be_visible()


def test_menu_au_clavier_et_actions_indisponibles_sur_un_profil_neuf(page):
    """Le menu ⋯ s'ouvre au clavier ; sur un profil non enregistré, Exporter / Supprimer
    sont désactivés (avec la raison en infobulle) ; Échap le referme."""
    open_page(page)
    page.focus("#pf-more")
    page.keyboard.press("ArrowDown")
    expect(page.locator(".menu__list")).to_be_visible()
    expect(page.locator(".menu__item", has_text="Exporter")).to_be_disabled()
    expect(page.locator(".menu__item", has_text="Supprimer")).to_be_disabled()
    page.keyboard.press("Escape")
    expect(page.locator(".menu__list")).to_have_count(0)


def test_exporter_telecharge_le_yaml(page, cleanup):
    name = _saved_profile(page, cleanup)
    page.click("#pf-more")
    with page.expect_download() as dl:
        page.locator(".menu__item", has_text="Exporter").click()
    assert dl.value.suggested_filename == f"{name}.yaml"
    assert "exporte-moi" in Path(dl.value.path()).read_text(encoding="utf-8")
    expect(page.locator(TOAST_OK)).to_contain_text("exporté")


def test_importer_un_fichier_yaml_ouvre_le_profil_importe(page, cleanup, tmp_path):
    name = uid("importe")
    cleanup["profiles"].append(name)
    f = tmp_path / f"{name}.yaml"
    f.write_text(f"name: {name}\ndescription: importé par e2e\nsystem_prompt_extra: bonjour\n", encoding="utf-8")
    open_page(page)
    page.set_input_files("#pf-import-file", str(f))
    expect(page.locator(TOAST_OK)).to_contain_text("importé")
    expect(page.locator("#pf-title")).to_have_text(name)
    expect(page.locator(f"#pf-list .pf-item[data-name='{name}']")).to_have_attribute("aria-current", "true")


def test_importer_un_yaml_casse_le_dit(page, tmp_path):
    f = tmp_path / "casse.yaml"
    f.write_text("name: [pas: fermé\n", encoding="utf-8")
    open_page(page)
    page.set_input_files("#pf-import-file", str(f))
    expect(page.locator(TOAST_ERR)).to_contain_text("Import impossible")


def test_mettre_a_jour_les_plugins_dit_le_resultat(page, cleanup):
    _saved_profile(page, cleanup)
    page.click("#pf-more")
    page.locator(".menu__item", has_text="Mettre à jour les plugins").click()
    expect(page.locator("#toasts .toast").last).to_contain_text(re.compile("plugin|Plugins"))


# ---------------------------------------------------------------- sélections introuvables (bug D3)


def test_un_outil_introuvable_est_affiche_et_conserve_a_l_enregistrement(page, cleanup):
    """Un profil qui référence un outil disparu du catalogue (plugin retiré) l'affiche
    « introuvable » et le CONSERVE quand on enregistre une autre modification."""
    if not HOME:
        pytest.skip("BZ_E2E_HOME_PROFILS non défini : impossible d'écrire le YAML directement")
    name = uid()
    cleanup["profiles"].append(name)
    d = Path(HOME) / ".bouzecode" / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(
        f"name: {name}\ntools: [Read, OutilDisparu]\nskills: [skill-disparue]\nsystem_prompt_extra: v1\n",
        encoding="utf-8")
    open_page(page, f"?profil={name}")
    expect(page.locator(f"#pf-list .pf-item[data-name='{name}'] .pf-tag--warn")).to_be_visible()
    expect(page.locator("#pf-skills-chips")).to_contain_text("skill-disparue (introuvable)")
    expect(page.locator("#pf-caps-summary")).to_contain_text("1 introuvable")
    page.fill("#pf-prompt", "v2")
    page.click("#pf-save")
    expect(page.locator(TOAST_OK)).to_contain_text("enregistré")
    expect(page.locator(TOAST_INFO)).to_contain_text("conservées")
    saved = _api("GET", f"/api/profiles/{name}")[1]
    assert "OutilDisparu" in saved["tools"] and "skill-disparue" in saved["skills"]
    assert saved["system_prompt_extra"] == "v2"


# ---------------------------------------------------------------- catalogue (tiroir)


CATALOG = {"installed": [{"name": "deja-la", "description": "installé", "tools": ["Read"]}],
           "available": [{"name": "a-installer", "description": "dispo", "tools": ["Read", "Bash"]}]}


def test_catalogue_installer_en_erreur_puis_avec_succes(page):
    """Tiroir catalogue : squelette → listes ; Installer occupé pendant l'envoi ; un échec
    (422) est dit, le bouton est rendu ; un succès propose d'ouvrir le profil."""
    open_page(page)
    held, release = hold(page, "**/api/agents/catalog")
    page.click("#pf-catalog-open")
    expect(page.locator("#pf-catalog")).to_have_attribute("data-open", "true")
    expect(page.locator("#pf-cat-available .skeleton")).to_be_visible()
    for r in held:
        r.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG))
    page.unroute("**/api/agents/catalog")
    page.route("**/api/agents/catalog", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG)))
    btn = page.locator("#pf-cat-available .pf-cat[data-name='a-installer'] button")
    expect(btn).to_have_text("Installer")

    page.route("**/api/agents/install", lambda r: r.fulfill(status=422, content_type="application/json",
               body=json.dumps({"ok": False, "errors": ["plugin xyz introuvable"], "error": "plugin xyz introuvable"})))
    btn.click()
    expect(page.locator(TOAST_ERR)).to_contain_text("plugin xyz introuvable")
    expect(btn).to_be_enabled()

    page.unroute("**/api/agents/install")
    held2, release2 = hold(page, "**/api/agents/install")
    btn.click()
    expect(btn).to_have_text("Installation…")
    expect(btn).to_be_disabled()
    for r in held2:
        r.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "errors": [], "name": "a-installer"}))
    page.unroute("**/api/agents/install")
    expect(page.locator(TOAST_OK)).to_contain_text("installé")
    expect(page.locator(TOAST_OK).locator(".toast__action")).to_have_text("Ouvrir")


def test_catalogue_rafraichir_en_echec_le_dit_et_garde_la_liste(page):
    open_page(page)
    page.route("**/api/agents/catalog", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG)))
    page.click("#pf-catalog-open")
    expect(page.locator("#pf-cat-installed")).to_contain_text("deja-la")
    page.route("**/api/agents/catalog/refresh", lambda r: r.fulfill(status=502, content_type="application/json",
               body=json.dumps({**CATALOG, "ok": False, "errors": ["git injoignable"],
                                "error": "rafraîchissement du catalogue impossible : git injoignable"})))
    page.click("#pf-catalog-refresh")
    expect(page.locator(TOAST_ERR)).to_contain_text("git injoignable")
    expect(page.locator(TOAST_ERR)).to_contain_text("en cache")
    expect(page.locator("#pf-cat-installed")).to_contain_text("deja-la")
    page.keyboard.press("Escape")
    expect(page.locator("#pf-catalog")).to_have_attribute("data-open", "false")
    expect(page.locator("#pf-catalog-open")).to_be_focused()


def test_catalogue_indisponible_propose_reessayer(page):
    open_page(page)
    undo = fail(page, "**/api/agents/catalog", status=500)
    page.click("#pf-catalog-open")
    expect(page.locator("#pf-cat-available .error-state")).to_contain_text("Catalogue indisponible")
    undo()
    page.route("**/api/agents/catalog", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG)))
    page.locator("#pf-cat-available .error-state button").click()
    expect(page.locator("#pf-cat-available")).to_contain_text("a-installer")


# ---------------------------------------------------------------- bibliothèque : skills


def test_skills_creer_refuser_un_nom_existant_puis_supprimer(page, cleanup):
    """Nouvelle skill : un nom déjà pris est refusé SOUS le champ (avec « Ouvrir la skill
    existante ») ; un nom libre crée la skill, qui devient proposée dans l'éditeur de profil ;
    Supprimer confirme puis efface, et la fiche est vidée (bug D20)."""
    open_page(page)
    page.click("#pf-library-open")
    expect(page.locator("#pf-library")).to_have_attribute("data-open", "true")
    expect(page.locator("#pf-sk-list .pf-item").first).to_be_visible(timeout=20000)
    existing = page.locator("#pf-sk-list .pf-item").first.get_attribute("data-name")

    page.click("#pf-sk-new")
    expect(page.locator("#pf-sk-name")).to_be_focused()
    page.fill("#pf-sk-name", existing if "/" not in existing else "bouzecode")
    page.click("#pf-sk-save")
    expect(page.locator("#pf-sk-name-error")).to_contain_text(re.compile("existe déjà|Minuscules"))

    name = uid("skill")
    cleanup["skills"].append(name)
    page.fill("#pf-sk-name", name)
    content = f"---\nname: {name}\ndescription: skill de test e2e\n---\n\n# {name}\n"
    page.fill("#pf-sk-content", content)
    expect(page.locator("#pf-sk-dirty")).to_have_text("• modifié")
    page.click("#pf-sk-save")
    expect(page.locator(TOAST_OK)).to_contain_text(f"Skill « {name} » enregistrée")
    expect(page.locator(f"#pf-sk-list .pf-item[data-name='{name}']")).to_be_visible()
    expect(page.locator("#pf-sk-name")).to_have_attribute("readonly", "")
    expect(page.locator("#pf-sk-dirty")).to_have_text("")

    page.click("#pf-sk-delete")
    page.locator("dialog.ui-dialog [data-role='confirm']").click()
    expect(page.locator(TOAST_OK).filter(has_text="supprimée")).to_be_visible()
    expect(page.locator("#pf-sk-form")).to_be_hidden()
    expect(page.locator("#pf-sk-meta")).to_have_text("")
    expect(page.locator(f"#pf-sk-list .pf-item[data-name='{name}']")).to_have_count(0)


def test_skill_enregistrer_en_erreur_le_dit(page):
    open_page(page)
    page.click("#pf-library-open")
    page.click("#pf-sk-new")
    page.fill("#pf-sk-name", uid("skill"))
    page.fill("#pf-sk-content", "pas de front-matter")
    page.click("#pf-sk-save")
    expect(page.locator(TOAST_ERR)).to_contain_text("frontmatter")
    expect(page.locator("#pf-sk-save")).to_be_enabled()


# ---------------------------------------------------------------- bibliothèque : plugins


def test_plugins_installer_vide_en_erreur_puis_avec_confirmation_git(page):
    open_page(page)
    page.click("#pf-library-open")
    page.click("#pf-lib-tab-plugins")
    expect(page.locator("#pf-lib-plugins")).to_be_visible()
    page.click("#pf-plugin-install")
    expect(page.locator("#pf-plugin-error")).to_contain_text("Colle l'URL")

    page.fill("#pf-plugin-input", "https://gitlab.example/plugin-inexistant")
    page.route("**/api/plugins/from-gitlab", lambda r: r.fulfill(status=400, content_type="application/json",
               body=json.dumps({"error": "dépôt introuvable"})))
    page.click("#pf-plugin-install")
    expect(page.locator("#pf-plugin-error")).to_contain_text("dépôt introuvable")
    expect(page.locator(TOAST_ERR)).to_contain_text("Plugin non installé")
    expect(page.locator("#pf-plugin-install")).to_have_text("Installer")

    page.unroute("**/api/plugins/from-gitlab")
    answers = iter([
        {"requires_confirmation": True, "message": "Absent d'Artifactory : cloner le dépôt git ?"},
        {"ok": True, "package": "plugin-demo", "via": "git"},
    ])
    page.route("**/api/plugins/from-gitlab", lambda r: r.fulfill(status=200, content_type="application/json",
               body=json.dumps(next(answers))))
    page.click("#pf-plugin-install")
    dialog = page.locator("dialog.ui-dialog")
    expect(dialog).to_contain_text("cloner le dépôt git")
    expect(page.locator("#pf-plugin-install")).to_have_attribute("aria-busy", "true")
    dialog.locator("[data-role='confirm']").click()
    expect(page.locator(TOAST_OK)).to_contain_text("plugin-demo")
    expect(page.locator("#pf-plugin-input")).to_have_value("")


def test_plugins_reseau_coupe_ne_bloque_jamais_le_bouton(page):
    """Bug D1 : réseau coupé pendant l'installation → message, et le bouton redevient cliquable."""
    open_page(page)
    page.click("#pf-library-open")
    page.click("#pf-lib-tab-plugins")
    page.fill("#pf-plugin-input", "https://gitlab.example/x")
    fail(page, "**/api/plugins/from-gitlab", abort=True)
    page.click("#pf-plugin-install")
    expect(page.locator(TOAST_ERR)).to_contain_text("injoignable")
    expect(page.locator("#pf-plugin-install")).to_be_enabled()
    expect(page.locator("#pf-plugin-install")).to_have_text("Installer")


# ---------------------------------------------------------------- clavier (R10)


def test_clavier_nouveau_profil_ctrl_s_et_echap(page, cleanup):
    """Tout au clavier : Tab jusqu'à « + Nouveau profil », saisie, Ctrl+S enregistre ; Échap
    referme la bibliothèque et rend le focus à son bouton."""
    open_page(page)
    page.focus("#pf-new")
    page.keyboard.press("Enter")
    expect(page.locator("#pf-name")).to_be_focused()
    name = uid()
    cleanup["profiles"].append(name)
    page.keyboard.type(name)
    page.keyboard.press("Control+s")
    expect(page.locator(TOAST_OK)).to_contain_text(name)
    page.focus("#pf-library-open")
    page.keyboard.press("Enter")
    expect(page.locator("#pf-library")).to_have_attribute("data-open", "true")
    page.keyboard.press("Escape")
    expect(page.locator("#pf-library")).to_have_attribute("data-open", "false")
    expect(page.locator("#pf-library-open")).to_be_focused()
    assert page.errors == [], page.errors
