"""Le profil `default` PACKAGÉ porte aussi la matière frontend/UI.

Migration voulue par l'utilisateur : les instructions spécifiques des anciens profils
`coder`, `manager` et `frontend` vivent désormais dans l'agent par défaut, pour que la
notion de profil devienne obsolète. Ces tests verrouillent la partie frontend : ce sont
les savoirs qu'on a payés cher (chromium derrière proxy NTLM, E2E tués par `-n auto`,
page morte que vitest ne voit pas) et qu'une réécriture du prompt ne doit pas perdre.
"""
from bouzecode.backend.profiles import load_system_profiles


def _prose() -> str:
    profiles = load_system_profiles()
    assert "default" in profiles, "le profil default doit être PACKAGÉ dans profiles/builtin/"
    return profiles["default"].system_prompt_extra


def test_ui_section_exists():
    assert "## UI / Frontend" in _prose(), (
        "la matière frontend doit être une section du profil par défaut")


def test_chrome_devtools_must_be_enabled_before_use():
    """Les outils mcp__chrome-devtools__* n'existent qu'APRÈS EnableChromeDevtools.

    Sans cette consigne l'agent code à l'aveugle ou se plaint d'un outil absent.
    """
    prose = _prose()
    assert "EnableChromeDevtools" in prose
    assert "mcp__chrome-devtools__" in prose


def test_chromium_proxy_install_script_is_named():
    """Derrière le proxy NTLM, `playwright install` boucle : le script maison est la voie."""
    assert "install-chromium-proxy.ps1" in _prose()


def test_e2e_must_not_run_with_xdist():
    """Cas réel : 173 s en séquentiel, >600 s puis tué avec `-n auto`."""
    prose = _prose()
    assert "-n auto" in prose
    ui = prose.split("## UI / Frontend")[1]
    assert "-n auto" in ui, "l'interdit xdist doit être rappelé dans la section UI"


def test_boot_smoke_is_required():
    """Le smoke §0 (page chargée, zéro pageerror) est ce que vitest ne voit jamais."""
    ui = _prose().split("## UI / Frontend")[1]
    assert "pageerror" in ui


def test_visual_proof_required():
    """Un critère visuel se prouve, pas par une affirmation : contenu et géométrie par
    take_snapshot / evaluate, rendu purement visuel par capture puis ImageQuestion (l'image
    n'entre plus dans le contexte, cf. docs/reduction_tokens/correctifs.md)."""
    ui = _prose().split("## UI / Frontend")[1]
    assert "take_snapshot" in ui and "getBoundingClientRect" in ui
    assert "ImageQuestion" in ui
