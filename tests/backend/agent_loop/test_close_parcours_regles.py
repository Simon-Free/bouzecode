# [desc] Unit tests of the « parcours vérifiés » gate rules: what counts as an interface write, when a requirement ACTS, what a green run is. [/desc]
"""Règles de la porte des parcours, au niveau unitaire (journal simulé)."""
from __future__ import annotations

import pytest

from bouzecode.backend.agent import close_parcours as cp


def _session(*appels: tuple[str, dict, str | None], demande: str = "Corrige la page.") -> list:
    messages = [{"role": "user", "content": demande}]
    for i, (nom, entree, resultat) in enumerate(appels):
        messages.append({"role": "assistant",
                         "tool_calls": [{"id": f"c{i}", "name": nom, "input": entree}]})
        if resultat is not None:
            messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": resultat})
    return messages


def _write(chemin: str) -> tuple[str, dict, str]:
    return "Write", {"file_path": chemin, "content": "x"}, f"Created {chemin}"


def _bash(commande: str, sortie: str = "ok") -> tuple[str, dict, str]:
    return "Bash", {"command": commande}, sortie


E2E = "npx playwright test tests/e2e/page.spec.ts"


# ── Écriture d'interface : hors dépôt, ce n'est pas l'interface ───────────────────────────

@pytest.mark.parametrize("chemin", [
    "/tmp/pe-pw/smoke.js",
    "/tmp/bouzecode_scratch/260042cc/diag.js",
    "C:\\Users\\me\\AppData\\Local\\Temp\\pe-pw\\smoke.js",
    "C:/Windows/Temp/figures.js",
])
def test_un_script_ecrit_dans_un_repertoire_temporaire_n_est_pas_l_interface(chemin):
    appel = cp.journal(_session(_write(chemin)))[0]
    assert not cp._ecriture_interface(appel)


@pytest.mark.parametrize("chemin", ["/home/x/portail/index.html", "C:\\proj\\assets\\tinder.js"])
def test_un_fichier_front_du_depot_reste_l_interface(chemin):
    appel = cp.journal(_session(_write(chemin)))[0]
    assert cp._ecriture_interface(appel)


def test_un_script_playwright_retouche_dans_tmp_apres_le_navigateur_ne_force_pas_a_rejouer():
    """6bafe9cd t114 : `/tmp/pe-pw/diag.js` écrit après la dernière recette navigateur."""
    messages = _session(_write("/home/x/portail/index.html"),
                        _bash(E2E, "5 passed"),
                        _write("/tmp/pe-pw/diag.js"))
    parcours = [{"exigence": "afficher la carte", "parcours": "ouvrir la page", "preuve": E2E}]
    assert cp.manques(parcours, messages) == []


# ── Exigence qui AGIT : des verbes, pas des états ─────────────────────────────────────────

@pytest.mark.parametrize("exigence", [
    "Modifier tous les éléments de l'énigme",
    "Niveau de difficulté estimé et modifiable",
    "L'utilisateur accepte ou refuse une énigme",
    "Édition d'un choix A-E",
    "Save the edited puzzle",
])
def test_une_exigence_avec_un_verbe_d_action_agit(exigence):
    assert cp._EXIGENCE_ACTION_RE.search(exigence)


@pytest.mark.parametrize("exigence", [
    "Au rechargement, onglet Tinder actif, compteur conservé, énigme acceptée non reproposée",
    "Les énigmes acceptées sont listées",
    "Zéro erreur console ; changelog affiché",
    "Le bouton onclick est câblé",
])
def test_un_participe_d_etat_n_agit_pas(exigence):
    assert not cp._EXIGENCE_ACTION_RE.search(exigence)


def _navigateur(nom: str, entree: dict, rendu: str = "ok") -> tuple[str, dict, str]:
    return f"mcp__chrome-devtools__{nom}", entree, rendu


GESTE_PUIS_CONSTAT = (_navigateur("click", {"uid": "1_31"}, "Successfully clicked"),
                      _navigateur("navigate_page", {"type": "reload"}, "Successfully reloaded"),
                      _navigateur("take_snapshot", {}, "uid=1_0 RootWebArea"))


def _verifier(item: dict, *appels, tous: list | None = None) -> str:
    return cp._verifier(0, item, cp.journal(_session(*appels)), tous or [item])[0]


def test_le_geste_peut_etre_decrit_dans_le_parcours():
    """6bafe9cd t63 : « cliquer l'étoile 4 » dans le parcours, l'instantané en preuve."""
    item = {"exigence": "Niveau de difficulté estimé et modifiable",
            "parcours": "lire le niveau estimé, cliquer l'étoile 4, vérifier le libellé",
            "preuve": "take_snapshot : étoile 4 → aria-pressed=4, libellé « Avancé »"}
    assert _verifier(item, *GESTE_PUIS_CONSTAT) == ""


def test_modifier_tous_les_elements_ne_se_prouve_toujours_pas_par_un_instantane():
    """6bafe9cd t40 : formulaire d'édition regardé, jamais joué — même si un AUTRE parcours
    déclaré a cliqué ailleurs (Accepter)."""
    accepter = {"exigence": "Accepter une énigme", "parcours": "clic sur Accepter",
                "preuve": "mcp__chrome-devtools__click puis take_snapshot"}
    modifier = {"exigence": "Modifier tous les éléments de l'énigme",
                "parcours": "Ouvrir « Modifier cette énigme » → champs + boutons Enregistrer",
                "preuve": "mcp__chrome-devtools__take_snapshot (formulaire rendu)"}
    probleme = _verifier(modifier, *GESTE_PUIS_CONSTAT, tous=[accepter, modifier])
    assert "AGIT" in probleme


def test_une_exigence_de_persistance_reprend_le_geste_d_un_autre_parcours():
    """6bafe9cd t65 : « Les choix (accepter/refuser) sont conservés après rechargement » — le
    clic Accepter est prouvé dans un autre parcours déclaré, celui-ci recharge et relit."""
    accepter = {"exigence": "Accepter une énigme", "parcours": "clic sur Accepter",
                "preuve": "mcp__chrome-devtools__click puis take_snapshot"}
    conserves = {"exigence": "Les choix (accepter/refuser) sont conservés après rechargement",
                 "parcours": "Recharger la page et relire l'état affiché",
                 "preuve": "navigate_page (reload) puis take_snapshot : « 1 acceptée »"}
    assert _verifier(conserves, *GESTE_PUIS_CONSTAT, tous=[accepter, conserves]) == ""


# ── Une exécution verte : pas de ligne FAIL, pas de k/n incomplet ─────────────────────────

@pytest.mark.parametrize("sortie", [
    "OK   desktop 1280x800\nFAIL filtre « Toutes » : Accepter avance\nOK   vue LISTE",
    "  ✘  1 [chromium] › tinder.spec.ts:3:1 › accepter (5.1s)\n  1 failed",
    "  ✗ la carte suivante s'affiche",
    "FAILED tests/test_server.py::test_git_refuse - AssertionError",
    "FIGURES: 6/7 OK ; CHOICES: 5/5 OK",
    "smoke : 19/20 passed",
])
def test_une_sortie_qui_signale_un_echec_n_est_pas_verte(sortie):
    appel = cp.journal(_session(_bash("node /tmp/pe-pw/smoke.js", sortie)))[0]
    assert not appel.vert()


@pytest.mark.parametrize("sortie", [
    "OK   desktop\nOK   filtre\n20/20 OK",
    "FIGURES: 7/7 OK ; CHOICES: 5/5 OK",
    "compteur « 1 / 310 », carte 2/310",
    "0 failed, 38 passed",
    "Le mot FAILURE apparaît dans un titre, pas en tête de ligne : test FAIL",
])
def test_une_sortie_reussie_reste_verte(sortie):
    appel = cp.journal(_session(_bash("node /tmp/pe-pw/smoke.js", sortie)))[0]
    assert appel.vert()


def test_une_recette_modifiee_pour_forcer_exit_0_apres_un_refus_est_signalee():
    """6bafe9cd t140 → t142 : après un refus, `exit 0` ajouté en fin de all.sh. Le code de
    sortie ne prouve plus rien : la clôture passe (la sortie est verte) mais on le DIT."""
    parcours = [{"exigence": "afficher la carte", "parcours": "ouvrir la page",
                 "preuve": "bash /tmp/pe-pw/all.sh 8803"}]
    messages = _session(
        _write("/home/x/portail/index.html"),
        _bash("bash /tmp/pe-pw/all.sh 8802", "OK smoke 20/20 OK\n[exited code=143]"),
        ("FinalAnswer", {"parcours_verifies": parcours}, "CLÔTURE REFUSÉE par le validateur"),
        ("Edit", {"file_path": "/tmp/pe-pw/all.sh", "old_string": 'echo "--- fin ---"',
                  "new_string": 'echo "--- fin ---"\nexit 0'}, "Changes applied to all.sh"),
        _bash("bash /tmp/pe-pw/all.sh 8803", "OK smoke 20/20 OK (playwright)"),
    )
    signalements = cp.signalements(parcours, messages)
    assert len(signalements) == 1
    assert "all.sh" in signalements[0] and "exit 0" in signalements[0]


def test_une_recette_ecrite_avec_exit_0_des_le_depart_n_est_pas_signalee():
    parcours = [{"exigence": "afficher la carte", "parcours": "ouvrir la page",
                 "preuve": "bash /tmp/pe-pw/all.sh 8803"}]
    messages = _session(
        _write("/home/x/portail/index.html"),
        ("Write", {"file_path": "/tmp/pe-pw/all.sh", "content": "node smoke.js\nexit 0"}, "ok"),
        _bash("bash /tmp/pe-pw/all.sh 8803", "OK smoke 20/20 OK (playwright)"),
    )
    assert cp.signalements(parcours, messages) == []
