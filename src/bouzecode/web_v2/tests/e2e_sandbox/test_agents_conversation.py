# [desc] E2E page Agents — lancer, suivre et parler à un agent : barre de lancement (dépôt obligatoire, profil via ?profil=), étapes de préparation, streaming, question, plan, file d'attente sans interruption, Arrêter, agent planté (Continuer / Relancer), vues Récap / Fichiers / Coûts, onglets et liens profonds (U11, U13). [/desc]
from __future__ import annotations

import re
import time

import pytest

from agents_e2e_support import (  # noqa: F401 — fixtures importées
    BASE, DEPOT, MARQUES, Retenue, TOAST_ERR, TOAST_INFO, TOAST_OK, api, attendre_etat, browser, cle_agent, expect,
    lancer, ouvrir, ouvrir_agent, panneau, pg, uid,
)

pytestmark = [*MARQUES, pytest.mark.couvre("static/js/conversations.js", "static/js/conversations/**", "static/css/agents.css", "templates/conversations.html", "templates/base.html", "static/js/lib/**", "static/js/chrome.js", "static/ds.css", "static/js/shared/**", "routes/sessions/**", "routes/work/fleet.py", "services/work/fleet.py", "services/work/lexique.py", "services/sessions/**", "runtime/**", "static/js/projects_admin.js", "routes/work/projects.py", "services/work/projects.py", "routes/typologies.py", "services/work/dispatch.py", "services/work/file_messages.py", "services/work/launch_phase.py", "routes/tickets_api/**", "services/message_view.py", "services/message_render_helpers.py", "static/css/thread.css", "services/recap_service.py", "services/file_service.py")]


def _choisir_depot(page, depot=DEPOT):
    expect(page.locator("#ag-chip-repo")).not_to_contain_text("chargement")
    page.locator("#ag-chip-repo").click()
    page.locator(".menu__item", has_text=depot).first.click()
    expect(page.locator("#ag-chip-repo")).to_contain_text(depot)


# ---------------------------------------------------------------- lancement


def test_lancer_sans_depot_puis_avec_etapes_et_reponse_sans_recharger(pg):
    """U11 : aucun dépôt deviné ; bouton occupé ; onglet ouvert aussitôt ; étapes ; réponse sans F5."""
    page = pg.page
    page.goto(f"{BASE}/conversations")
    page.evaluate("localStorage.removeItem('bz.conv.project')")
    page.reload()
    expect(page.locator("#ag-chip-repo")).to_contain_text("choisir un dépôt")
    titre = uid("Lancement")
    page.fill("#conv-new-input", f"{titre}\n[scn:reply]")
    page.click("#conv-new-send")
    expect(page.locator("#conv-new-error")).to_contain_text("Choisis un dépôt")
    expect(page.locator("#conv-new-input")).to_have_value(f"{titre}\n[scn:reply]")
    expect(page.locator(".menu__list")).to_be_visible()
    page.locator(".menu__item", has_text=DEPOT).first.click()

    retenue = Retenue(page, "**/api/projects/*/tickets")
    page.click("#conv-new-send")
    # Signal immédiat : bouton occupé et champ verrouillé pendant l'aller-retour.
    expect(page.locator("#conv-new-send")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#conv-new-send")).to_contain_text("Lancement…")
    expect(page.locator("#conv-new-input")).to_have_attribute("aria-busy", "true")
    # Double clic ignoré (R5) : une seule requête partira.
    page.locator("#conv-new-send").click(force=True)
    retenue.relacher()
    # Onglet ouvert AUSSITÔT, sur la préparation, avec les étapes.
    expect(panneau(pg).locator(".ag-launching, .block")).to_be_visible(timeout=15000)
    expect(page.locator(TOAST_OK, has_text="Agent lancé")).to_be_visible()
    expect(page.locator("#conv-new-input")).to_have_value("")
    assert len(pg.appels(r"/api/projects/[^/]+/tickets$", "POST")) == 1
    # La réponse finale arrive sans recharger ; l'onglet dit « Terminé ».
    expect(panneau(pg).locator(".block.final-answer")).to_be_visible(timeout=60000)
    expect(panneau(pg).locator(".ag-head .badge")).to_contain_text("Terminé", timeout=20000)
    expect(page.locator(".ag-tab[aria-selected=true]")).to_contain_text(titre[:10])
    # La liste suit.
    expect(page.locator(".ag-group[data-group=termines] .ag-card", has_text=titre)).to_be_visible(timeout=30000)


def test_lancement_refuse_le_texte_reste_et_l_erreur_est_dite(pg):
    page = pg.page
    page.goto(f"{BASE}/conversations")
    _choisir_depot(page)
    pg.autoriser(r"status of 503")
    page.route("**/api/projects/*/tickets", lambda r: r.fulfill(status=503, body='{"error":{"code":"env_indisponible","message":"API injoignable (proxy)"}}', content_type="application/json"))
    page.fill("#conv-new-input", "Ne partira pas")
    page.click("#conv-new-send")
    expect(page.locator("#conv-new-error")).to_contain_text("API injoignable")
    expect(page.locator("#conv-new-input")).to_have_value("Ne partira pas")
    expect(page.locator("#conv-new-send")).to_be_enabled()


def test_profil_preselectionne_par_lien_utiliser_ce_profil(pg):
    page = pg.page
    profils = [t["name"] for t in api("GET", "/api/typologies")["typologies"]]
    cible = profils[-1]
    page.goto(f"{BASE}/conversations?profil={cible}")
    expect(page.locator("#ag-chip-profile")).to_contain_text(cible)
    expect(page.locator(TOAST_INFO, has_text=cible)).to_be_visible()
    assert "profil=" not in page.url
    # Profil inconnu : erreur dite.
    page.goto(f"{BASE}/conversations?profil=fantome-{uid()}")
    expect(page.locator(TOAST_ERR, has_text="introuvable")).to_be_visible()


def test_gerer_les_depots_erreur_puis_ajout_selectionne(pg, tmp_path):
    page = pg.page
    page.goto(f"{BASE}/conversations")
    page.locator("#ag-chip-repo").click()
    page.locator(".menu__item", has_text="Gérer les dépôts").click()
    dlg = page.locator("dialog.ag-repos")
    expect(dlg).to_be_visible()
    expect(dlg.locator(".ag-repo").first).to_be_visible()
    # Champs requis.
    dlg.locator("button[type=submit]").click()
    expect(dlg.locator(".ag-repos__add .field__error")).to_contain_text("requis")
    # Chemin inexistant : erreur serveur dite, saisie gardée.
    pg.autoriser(r"status of 400")
    nom = uid("depot")
    dlg.get_by_label("Nom").fill(nom)
    dlg.get_by_label("Chemin absolu du dépôt").fill("/chemin/qui/n/existe/pas")
    dlg.locator("button[type=submit]").click()
    expect(dlg.locator(".ag-repos__add .field__error")).not_to_be_empty()
    expect(dlg.get_by_label("Nom")).to_have_value(nom)
    # Chemin valide : ajouté, sélectionné dans le chip, surligné dans la liste.
    dossier = tmp_path / nom
    dossier.mkdir()
    dlg.get_by_label("Chemin absolu du dépôt").fill(str(dossier))
    dlg.locator("button[type=submit]").click()
    expect(page.locator(TOAST_OK, has_text="ajouté")).to_be_visible()
    expect(dlg.locator(".ag-repo", has_text=nom)).to_be_visible()
    dlg.locator(".ui-dialog__actions button", has_text="Fermer").click()
    expect(page.locator("#ag-chip-repo")).to_contain_text(nom)
    # Nettoyage : on retire le dépôt de test.
    for _ in range(40):  # la vue d'ensemble des dépôts est mémorisée quelques secondes
        slugs = [p["slug"] for p in api("GET", "/api/projects")["projects"] if p["name"] == nom]
        if slugs:
            api("DELETE", f"/api/projects/{slugs[0]}", attendu=200)
            break
        time.sleep(0.5)


# ---------------------------------------------------------------- suivre


def test_streaming_texte_qui_arrive_puis_nouveaux_messages(pg):
    key = cle_agent(lancer(uid("Lent"), "slow"))
    ouvrir_agent(pg, key)
    p = panneau(pg)
    # Le faux LLM streame surtout de la « réflexion » : l'un ou l'autre bloc provisoire grandit à l'écran.
    expect(p.locator(".streaming-block, .streaming-thinking").first).to_be_visible(timeout=30000)
    expect(p.locator(".ag-head .badge")).to_contain_text("En cours")
    # Le composeur annonce la mise en file pendant le travail.
    expect(p.locator(".ag-composer__send")).to_contain_text("Mettre en file")
    expect(p.locator(".block.final-answer")).to_be_visible(timeout=60000)
    expect(p.locator(".streaming-block, .streaming-thinking")).to_have_count(0)


def test_question_options_verrouillees_brouillon_intact_et_reprise(pg):
    titre = uid("Question")
    key = cle_agent(lancer(titre, "question"))
    attendre_etat(key, {"awaiting_input"})
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    q = p.locator(".ag-question")
    expect(q).to_contain_text("Quelle base de données")
    expect(p.locator(".ag-head .badge")).to_contain_text("Attend ta réponse")
    # La carte est dans « À traiter ».
    expect(page.locator(".ag-group[data-group=a_traiter] .ag-card", has_text=titre)).to_be_visible(timeout=30000)
    p.locator(".ag-composer__input").fill("brouillon à ne pas perdre")
    q.locator(".ag-question__option", has_text="SQLite").click()
    # Toutes les options sont verrouillées au premier clic ; le brouillon est intact.
    for b in q.locator(".ag-question__option").all():
        expect(b).to_be_disabled()
    expect(p.locator(".ag-composer__input")).to_have_value("brouillon à ne pas perdre")
    expect(p.locator(".ag-echo")).to_contain_text("SQLite")
    expect(p.locator(".block.final-answer")).to_contain_text("Choix pris en compte", timeout=60000)
    expect(q).to_be_hidden()


def test_tours_apres_une_question_s_empilent_pendant_la_reflexion(pg):
    """TODO 2026-09-25 §3 : après la réponse à une question (pause CHAUDE), le tour n+1
    remplaçait le tour n à l'écran jusqu'à la réponse finale, la reprise chaude n'écrivant
    plus la session. Pendant que le 3ᵉ tour réfléchit, les deux premiers sont dans le fil."""
    key = cle_agent(lancer(uid("Tours"), "question-reflexion"))
    attendre_etat(key, {"awaiting_input"})
    ouvrir_agent(pg, key)
    p = panneau(pg)
    p.locator(".ag-question__option", has_text="Oui").click()
    #  Le 3ᵉ tour est EN COURS (bloc provisoire), la réponse finale n'est pas là.
    expect(p.locator(".streaming-block, .streaming-thinking").filter(
        has_text=re.compile(r"tour 3", re.I)).first).to_be_visible(timeout=60000)
    fil = p.locator(".block:not(.streaming-block)")
    expect(fil.filter(has_text="Tour 1 sur 3")).not_to_have_count(0)
    expect(fil.filter(has_text="Tour 2 sur 3")).not_to_have_count(0)
    assert p.locator(".block.final-answer").count() == 0, "le 3ᵉ tour devait encore tourner"
    expect(p.locator(".block.final-answer")).to_contain_text("Trois tours après la réponse", timeout=60000)


def test_message_lu_en_fin_de_tour_jamais_annonce_perdu(pg):
    """TODO 2026-09-25 §2 : un message mis en file pendant la DERNIÈRE étape est relevé par
    l'agent, qui conclut et s'arrête entre deux lectures du fil. Sur plusieurs lignes, sa bulle
    (rendue en markdown) ne reprenait pas le texte brut : au bout de 15 s le panneau affirmait
    « n'a pas été lu par l'agent », alors que la session le contient."""
    key = cle_agent(lancer(uid("Lu"), "etapes"))
    ouvrir_agent(pg, key)
    p = panneau(pg)
    expect(p.locator(".block", has_text="Étape 4 sur 4").first).to_be_visible(timeout=60000)
    p.locator(".ag-composer__input").fill("première ligne de la précision\nseconde ligne de la précision")
    p.locator(".ag-composer__input").press("Enter")
    attendre_etat(key, {"finished", "idle"})
    blocs = api("GET", f"/api/sessions/{key}/blocks")["blocks"]
    assert any("seconde ligne de la précision" in str(b) for b in blocs), "le message n'a pas été lu"
    pg.page.wait_for_timeout(17000)  # au-delà des 15 s après lesquelles il était annoncé perdu
    expect(p.locator(".ag-queue__lost")).to_have_count(0)


def test_deux_agent_d_un_meme_message_partent_ensemble_sans_background():
    """TODO 2026-09-25 §4 : N `Agent` dans un même message, parent en pause (pas de
    `background`) : le dispatcher les lançait un par un, le second après la FIN du premier
    (~20 s ici, deux enfants `etapes`). Ils doivent naître ensemble, puis le parent reprend
    avec leurs deux rapports."""
    key = cle_agent(lancer(uid("Lot"), "lot-pause"))
    agent_id = key.split("/", 1)[1]
    naissances: dict[str, float] = {}
    fin = time.time() + 60
    while len(naissances) < 2 and time.time() < fin:
        for fiche in api("GET", f"/api/agents/{agent_id}/children").get("children", []):
            naissances.setdefault(fiche.get("ticket_id"), time.time())
        time.sleep(0.3)
    assert len(naissances) == 2, f"enfants vus : {naissances}"
    ecart = max(naissances.values()) - min(naissances.values())
    assert ecart < 8, f"le second enfant est né {ecart:.1f} s après le premier (lancés en file)"
    attendre_etat(key, {"finished", "idle"}, delai=90)
    blocs = api("GET", f"/api/sessions/{key}/blocks")["blocks"]
    assert any("Lot de deux parties terminé" in str(b) for b in blocs)


def test_plan_a_valider_affiche_le_plan_et_se_valide(pg):
    key = cle_agent(lancer(uid("Plan"), "plan"))
    attendre_etat(key, {"awaiting_plan_validation"})
    ouvrir_agent(pg, key)
    p = panneau(pg)
    expect(p.locator(".ag-head .badge")).to_contain_text("Plan à valider")
    expect(p.locator(".ag-question__plan")).to_contain_text("Écrire un test qui échoue")
    p.locator(".ag-question__option", has_text="Oui").click()
    expect(p.locator(".block.final-answer")).to_contain_text("Plan exécuté", timeout=60000)


def test_message_pendant_le_travail_mis_en_file_jamais_d_interruption(pg):
    key = cle_agent(lancer(uid("File"), "slow"))
    attendre_etat(key, {"running"}, delai=40)
    ouvrir_agent(pg, key)
    p = panneau(pg)
    expect(p.locator(".ag-composer__send")).to_contain_text("Mettre en file", timeout=20000)
    p.locator(".ag-composer__input").fill("et ajoute un test")
    p.locator(".ag-composer__send").click()
    expect(pg.page.locator(TOAST_INFO, has_text="à sa prochaine étape")).to_be_visible()
    expect(p.locator(".ag-queue")).to_contain_text("et ajoute un test")
    expect(p.locator(".ag-composer__input")).to_have_value("")
    # Jamais d'interruption implicite.
    assert pg.appels(r"/interruptions") == []
    # Lu à sa prochaine étape (ou à la fin du tour) : le message apparaît dans le fil. Si l'agent s'est arrêté avant
    # de le lire (course côté serveur : processus chaud évincé), l'écran le DIT et propose de
    # le renvoyer — jamais de message perdu en silence.
    livre = p.locator(".block.user", has_text="et ajoute un test")
    perdu = p.locator(".ag-queue__lost")
    expect(livre.or_(perdu)).to_be_visible(timeout=90000)
    if perdu.is_visible():
        perdu.locator("button", has_text="Renvoyer").click()
    expect(livre).to_be_visible(timeout=60000)
    expect(p.locator(".ag-queue")).to_be_hidden()


def test_message_en_file_annulable(pg):
    key = cle_agent(lancer(uid("FileAnnul"), "slow"))
    attendre_etat(key, {"running"}, delai=40)
    ouvrir_agent(pg, key)
    p = panneau(pg)
    expect(p.locator(".ag-composer__send")).to_contain_text("Mettre en file", timeout=20000)
    p.locator(".ag-composer__input").fill("finalement non")
    p.locator(".ag-composer__send").click()
    expect(p.locator(".ag-queue")).to_contain_text("finalement non")
    p.locator(".ag-queue__item button", has_text="Annuler").click()
    expect(pg.page.locator(TOAST_OK, has_text="retiré de la file")).to_be_visible()
    expect(p.locator(".ag-queue")).to_be_hidden()


def test_envoi_direct_echo_immediat_puis_reponse_et_erreur_d_envoi(pg):
    key = cle_agent(lancer(uid("Suite"), "reply"))
    attendre_etat(key, {"finished", "idle"})
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    # Erreur d'envoi : le texte reste, l'erreur est dite.
    pg.autoriser(r"status of 500")
    page.route("**/messages", lambda r: r.fulfill(status=500, body='{"error":"panne simulée"}', content_type="application/json"))
    p.locator(".ag-composer__input").fill("et après ?")
    p.locator(".ag-composer__input").press("Enter")
    expect(p.locator(".ag-composer__error")).to_contain_text("panne simulée")
    expect(p.locator(".ag-composer__input")).to_have_value("et après ?")
    page.unroute("**/messages")
    # Envoi réel : écho immédiat, puis nouvelle réponse sans recharger.
    nb = p.locator(".block.final-answer").count()
    p.locator(".ag-composer__send").click()
    expect(p.locator(".ag-echo")).to_be_visible()
    # Réponse sans recharger — ou, si le serveur a perdu le message (processus chaud évincé
    # pendant la remise), l'écran le signale et « Renvoyer » le fait aboutir.
    nouvelle = p.locator(".block.final-answer").nth(nb)
    perdu = p.locator(".ag-queue__lost")
    expect(nouvelle.or_(perdu)).to_be_visible(timeout=60000)
    if perdu.is_visible():
        perdu.locator("button", has_text="Renvoyer").click()
    expect(p.locator(".block.final-answer")).to_have_count(nb + 1, timeout=60000)


def test_arreter_confirmation_annulable_puis_arret(pg):
    key = cle_agent(lancer(uid("Stop"), "slow"))
    attendre_etat(key, {"running"}, delai=40)
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    stop = p.locator(".ag-head__actions button", has_text="Arrêter")
    expect(stop).to_be_visible(timeout=20000)
    stop.click()
    expect(page.locator("dialog.ui-dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("dialog.ui-dialog")).to_have_count(0)
    assert pg.appels(r"/interruptions") == []
    stop.click()
    page.locator("dialog.ui-dialog button", has_text="Arrêter").click()
    expect(page.locator(TOAST_OK, has_text="Agent arrêté")).to_be_visible(timeout=30000)
    expect(p.locator(".ag-head .badge")).not_to_contain_text("En cours", timeout=30000)


def test_agent_plante_raison_et_continuer(pg):
    titre = uid("Crash")
    key = cle_agent(lancer(titre, "crash"))
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    expect(p.locator(".ag-head .badge")).to_contain_text("Arrêté sans finir", timeout=60000)
    # L'explication des deux gestes est portée par leurs infobulles (plus de paragraphe permanent).
    expect(p.locator(".ag-head__actions button", has_text="Continuer")).to_have_attribute("title", re.compile("Même agent"))
    expect(p.locator(".ag-head__actions button", has_text="Relancer")).to_have_attribute("title", re.compile("Nouvel agent"))
    expect(p.locator(".ag-composer__send")).to_contain_text("Continuer avec ce message")
    expect(page.locator(".ag-group[data-group=a_traiter] .ag-card", has_text=titre)).to_be_visible(timeout=30000)
    # Continuer : bouton occupé, résultat dit, l'état bouge sans recharger.
    cont = p.locator(".ag-head__actions button", has_text="Continuer")
    cont.click()
    expect(page.locator(f"{TOAST_OK}, {TOAST_ERR}").first).to_be_visible(timeout=60000)
    expect(page.locator(TOAST_OK, has_text="reprend")).to_be_visible()


def test_agent_plante_relancer_ouvre_un_nouvel_agent(pg):
    titre = uid("CrashR")
    key = cle_agent(lancer(titre, "crash"))
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    relancer = p.locator(".ag-head__actions button", has_text="Relancer")
    expect(relancer).to_be_visible(timeout=60000)
    onglets = page.locator(".ag-tab").count()
    relancer.click()
    dlg = page.locator("dialog.ui-dialog")
    expect(dlg).to_contain_text("nouvel agent")
    dlg.locator("button", has_text="Relancer").click()
    expect(page.locator(TOAST_OK, has_text="relancé")).to_be_visible(timeout=120000)
    expect(page.locator(".ag-tab")).to_have_count(onglets + 1)


# ---------------------------------------------------------------- vues


def test_vues_recap_fichiers_couts_avec_erreur_et_reessayer(pg):
    key = cle_agent(lancer(uid("Vues"), "tools"))
    attendre_etat(key, {"finished", "idle"}, delai=90)
    ouvrir_agent(pg, key)
    page = pg.page
    p = panneau(pg)
    p.locator(".ag-views .tab", has_text="Récap").click()
    expect(p.locator(".ag-pane--recap")).to_contain_text("Modifications", timeout=20000)
    p.locator(".ag-views .tab", has_text="Fichiers modifiés").click()
    expect(p.locator(".ag-pane--files .recap-diff")).to_contain_text("NOTES.md", timeout=20000)
    # Coûts : erreur simulée → Réessayer.
    pg.autoriser(r"status of 500")
    page.route("**/costs*", lambda r: r.fulfill(status=500, body='{"error":"coûts indisponibles"}', content_type="application/json"))
    p.locator(".ag-views .tab", has_text="Coûts & tours").click()
    expect(p.locator(".ag-pane--costs .error-state")).to_contain_text("coûts indisponibles")
    page.unroute("**/costs*")
    p.locator(".ag-pane--costs .error-state button").click()
    expect(p.locator(".ag-pane--costs table").first).to_be_visible(timeout=20000)
    # Détail d'un tour : chargement puis contenu.
    p.locator(".ag-pane--costs .ag-table__clickable").first.click()
    expect(p.locator(".ag-turn-detail")).to_be_visible()
    expect(p.locator(".ag-turn-detail h3, .ag-turn-detail .error-state").first).to_be_visible(timeout=20000)
    # Navigation au clavier entre les vues.
    p.locator(".ag-views .tab[aria-selected=true]").focus()
    page.keyboard.press("ArrowLeft")
    expect(p.locator(".ag-views .tab[aria-selected=true]")).to_have_text("Fichiers modifiés")


# ---------------------------------------------------------------- onglets


def test_onglets_clavier_pastille_nouveau_lien_profond_et_restauration(pg):
    k1 = cle_agent(lancer(uid("Onglet1"), "reply"))
    attendre_etat(k1, {"finished", "idle"})
    k2 = cle_agent(lancer(uid("Onglet2"), "slow"))
    page = pg.page
    ouvrir_agent(pg, k2)
    page.goto(f"{BASE}/conversations?agent={k1.split('/')[1]}")
    expect(page.locator(".ag-tab")).to_have_count(2, timeout=20000)
    # L'onglet actif est dans l'URL (lien partageable).
    assert f"agent={k1.split('/')[1]}" in page.url
    # L'onglet inactif (agent lent) reçoit du contenu → pastille « nouveau ».
    expect(page.locator(".ag-tab.has-unread")).to_have_count(1, timeout=60000)
    # Clavier : flèches entre onglets, Suppr ferme.
    page.locator(".ag-tab[aria-selected=true]").focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator(".ag-tab.has-unread")).to_have_count(0)
    page.keyboard.press("Delete")
    expect(page.locator(".ag-tab")).to_have_count(1)
    # Rechargement : l'onglet restant est rouvert.
    page.reload()
    expect(page.locator(".ag-tab")).to_have_count(1, timeout=20000)


def test_agent_introuvable_le_dit(pg):
    page = pg.page
    pg.autoriser(r"status of 404")
    page.goto(f"{BASE}/conversations?agent=inexistant{uid('')}")
    expect(panneau(pg)).to_contain_text("Cet agent n'existe plus", timeout=20000)
    expect(panneau(pg).locator(".ag-composer__input")).to_be_disabled()
    panneau(pg).locator("button", has_text="Fermer l'onglet").click()
    expect(page.locator(".ag-tab")).to_have_count(0)
    expect(page.locator(".ag-empty")).to_be_visible()


def test_erreurs_429_absorbees_l_agent_termine(pg):
    key = cle_agent(lancer(uid("Quota"), "error429"))
    attendre_etat(key, {"finished", "idle"}, delai=120)
    ouvrir_agent(pg, key)
    expect(panneau(pg).locator(".ag-head .badge")).to_contain_text("Terminé")


# ---------------------------------------------------------------- fil compact


def test_les_tours_du_modele_forment_un_seul_groupe_separe_par_de_fines_lignes(pg):
    """Une conversation à plusieurs tours d'outils ne s'étale plus en une bulle par tour : un seul
    groupe pour la réponse du modèle, une fine ligne entre deux tours, les outils résumés sur une
    ligne (« N outils · noms »), la réflexion repliée, la réponse finale en fin de groupe."""
    key = cle_agent(lancer(uid("Fil compact"), "tools"))
    attendre_etat(key, {"finished", "idle"}, delai=90)
    ouvrir_agent(pg, key)
    fil = panneau(pg).locator(".conv-messages")
    expect(fil.locator(".block.final-answer")).to_be_visible(timeout=30000)
    groupes = fil.locator(":scope > .turn-group")
    expect(groupes).to_have_count(1)
    tours = groupes.first.locator(":scope > .block.assistant").count()
    assert tours >= 3, f"le scénario tools doit produire plusieurs tours, vu {tours}"
    expect(groupes.first.locator(":scope > hr.turn-sep")).to_have_count(tours - 1)
    expect(groupes.first.locator(":scope > .block.final-answer")).to_have_count(1)
    resume = groupes.first.locator("details.tools-group > summary").first
    expect(resume).to_have_text(__import__("re").compile(r"^\d+ outils? · \w"))
    # Aucune bulle par tour : les blocs internes n'ont ni cadre ni fond propres.
    bord = groupes.first.locator(":scope > .block.assistant").nth(1).evaluate("el => getComputedStyle(el).borderTopWidth")
    assert bord == "0px"
    # Déplier un outil, attendre un rafraîchissement : il reste déplié.
    resume.click()
    expect(groupes.first.locator("details.tools-group").first).to_have_attribute("open", "")
    pg.page.wait_for_timeout(2000)
    expect(groupes.first.locator("details.tools-group").first).to_have_attribute("open", "")
