# [desc] Implements /doctor command combining session status summary with environment health checks. [/desc]
"""Diagnostic command: /doctor = session status + environment checks.

Le test de connectivité passe par la VOIE COMMUNE des appels LLM (`get_streamer()` →
`dispatch.stream`), avec le modèle de la session (`modele_annexe`) : il teste donc le
fournisseur, l'URL (ANTHROPIC_BASE_URL, PREPROD_ENDPOINT…) et la clé que les agents
utilisent réellement. L'ancien POST écrit à la main vers api.anthropic.com ignorait
ANTHROPIC_BASE_URL et testait un endpoint que la session n'utilise pas.
"""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from bouzecode.ui.ansi import clr
except ImportError:
    from bouzecode import clr

# Au-delà, le test rend la main : les retries du transport (connexion, 5xx) peuvent durer
# plusieurs minutes, et /doctor doit répondre même quand le réseau ne répond pas.
PROBE_DEADLINE_S = 45.0
_PROBE_MAX_TOKENS = 32


def _appel_minimal(model: str, config: dict, resultat: dict) -> None:
    """Un appel d'une ligne par la voie commune ; remplit `resultat` (reponse ou erreur)."""
    from ...agent.providers import AssistantTurn
    from ...agent.stream_interceptor import get_streamer

    side = {**config, "_depth": 1, "_context_state": None, "max_tokens": _PROBE_MAX_TOKENS,
            "thinking_mode": "off", "task_classification": False, "_call_label": "doctor"}
    side.pop("_tool_choice", None)
    try:
        for event in get_streamer()(
            model=model, system="Réponds uniquement : OK",
            messages=[{"role": "user", "content": "ping"}], tool_schemas=[], config=side,
        ):
            if isinstance(event, AssistantTurn):
                resultat["reponse"] = event.text or ""
    except Exception as exc:  # noqa: BLE001 — le diagnostic rapporte l'erreur, il ne plante pas
        resultat["erreur"] = f"{type(exc).__name__}: {exc}"


def sonder_fournisseur(config: dict, deadline: float = PROBE_DEADLINE_S) -> dict:
    """Teste le fournisseur de la session par un appel minimal.

    Rend {"fournisseur", "modele", "latence_s", "reponse", "erreur"} ; `erreur` est None
    si et seulement si le fournisseur a répondu."""
    from ...agent.providers.registry import resolve_provider
    from ...agent.providers.side_model import modele_annexe

    model = modele_annexe(config)
    resultat: dict = {"fournisseur": resolve_provider(model)[0], "modele": model,
                      "reponse": None, "erreur": None}
    debut = time.monotonic()
    worker = threading.Thread(target=_appel_minimal, args=(model, config, resultat),
                              name="doctor-probe", daemon=True)
    worker.start()
    worker.join(deadline)
    bilan = dict(resultat)
    bilan["latence_s"] = time.monotonic() - debut
    if worker.is_alive():
        bilan["erreur"] = f"pas de réponse en {deadline:.0f} s (réseau, proxy ou retries en cours)"
    elif bilan["erreur"] is None and bilan["reponse"] is None:
        bilan["erreur"] = "le flux s'est terminé sans réponse"
    return bilan


class _Bilan:
    """Compteurs et affichage des vérifications."""

    def __init__(self) -> None:
        self.ok = self.warn = self.fail = 0

    @staticmethod
    def _print(s: str) -> None:
        try:
            print(s)
        except UnicodeEncodeError:
            print(s.encode("ascii", errors="replace").decode())

    def passe(self, msg: str) -> None:
        self.ok += 1
        self._print(clr("  [PASS] ", "green") + msg)

    def avertit(self, msg: str) -> None:
        self.warn += 1
        self._print(clr("  [WARN] ", "yellow") + msg)

    def echoue(self, msg: str) -> None:
        self.fail += 1
        self._print(clr("  [FAIL] ", "red") + msg)

    def resume(self) -> None:
        total = self.ok + self.warn + self.fail
        texte = f"  {self.ok} passed, {self.warn} warnings, {self.fail} failures ({total} checks)"
        couleur = "red" if self.fail else "yellow" if self.warn else "green"
        self._print(clr(texte, couleur))


def _afficher_session(state, config) -> None:
    from ...agent.providers import detect_provider
    from bouzecode.backend.agent.compaction import estimate_tokens, get_context_limit
    from bouzecode import VERSION

    model = config.get("model", "unknown")
    messages = getattr(state, "messages", [])
    est_ctx = estimate_tokens(messages)
    ctx_limit = get_context_limit(model)
    ctx_pct = (est_ctx / ctx_limit * 100) if ctx_limit else 0
    print()
    print(clr("  ── Session ──", "bold"))
    print(f"  Version:     {VERSION}")
    print(f"  Model:       {model} ({detect_provider(model)})")
    print(f"  Permissions: {config.get('permission_mode', 'auto')}")
    print(f"  Session:     {config.get('_session_id', 'N/A')}")
    print(f"  Turns:       {getattr(state, 'turn_count', 0)}  |  Messages: {len(messages)}")
    print(f"  Tokens:      {getattr(state, 'total_input_tokens', 0):,} in / "
          f"{getattr(state, 'total_output_tokens', 0):,} out")
    print(f"  Context:     ~{est_ctx:,} / {ctx_limit:,} ({ctx_pct:.0f}%)")
    print()


def _git(args: list[str]) -> bool | None:
    """True/False selon le code retour ; None si git est introuvable."""
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              timeout=5).returncode == 0
    except Exception:  # noqa: BLE001
        return None


def _verifier_outils(b: _Bilan) -> None:
    v = sys.version_info
    version = f"Python {v.major}.{v.minor}.{v.micro}"
    b.passe(version) if v >= (3, 10) else b.echoue(f"{version} (need >=3.10)")
    git_ok = _git(["--version"])
    if git_ok is None:
        b.echoue("Git: not found")
    else:
        b.passe("Git: available") if git_ok else b.echoue("Git: not working")
    b.passe("Inside a git repository") if _git(["rev-parse", "--is-inside-work-tree"]) \
        else b.avertit("Not inside a git repository")


def _verifier_fournisseur(b: _Bilan, config: dict) -> None:
    """Clé du fournisseur de la session, puis un vrai appel minimal par la voie commune."""
    from ...agent.providers.registry import get_provider_key, resolve_provider
    from ...agent.providers.side_model import modele_annexe

    provider = resolve_provider(modele_annexe(config))[0]
    if not get_provider_key(provider, config):
        b.echoue(f"API key for {provider}: NOT SET")
        return
    b.passe(f"API key for {provider}: set")
    print(f"  ... testing {provider} API (one minimal call)...")
    r = sonder_fournisseur(config)
    ligne = f"{r['fournisseur']} / {r['modele']} ({r['latence_s']:.1f} s)"
    if r["erreur"]:
        b.echoue(f"LLM call {ligne}: {r['erreur']}")
    else:
        b.passe(f"LLM call {ligne}: answered")


def _verifier_autres_cles(b: _Bilan, config: dict) -> None:
    from ...agent.providers import PROVIDERS, detect_provider

    session = detect_provider(config.get("model", ""))
    for pname, pdata in PROVIDERS.items():
        env_var = pdata.get("api_key_env")
        if pname != session and env_var and os.environ.get(env_var, ""):
            b.passe(f"{pname} key ({env_var}): set")


def _verifier_modules(b: _Bilan) -> None:
    for mod, desc in [
        ("rich", "Rich (live markdown rendering)"),
        ("PIL", "Pillow (clipboard image)"),
        ("sounddevice", "sounddevice (voice recording)"),
        ("faster_whisper", "faster-whisper (local STT)"),
    ]:
        try:
            __import__(mod)
            b.passe(desc)
        except ImportError:
            b.avertit(f"{desc}: not installed")


def _verifier_fichiers(b: _Bilan, config: dict) -> None:
    claude_md = Path.cwd() / "CLAUDE.md"
    global_md = Path.home() / ".claude" / "CLAUDE.md"
    b.passe(f"Project CLAUDE.md: {claude_md}") if claude_md.exists() \
        else b.avertit("No project CLAUDE.md in current directory")
    if global_md.exists():
        b.passe(f"Global CLAUDE.md: {global_md}")
    ckpt_root = Path.home() / ".nano_claude" / "checkpoints"
    if ckpt_root.exists():
        mb = sum(f.stat().st_size for f in ckpt_root.rglob("*") if f.is_file()) / (1024 * 1024)
        sessions = sum(1 for d in ckpt_root.iterdir() if d.is_dir())
        (b.avertit if mb > 100 else b.passe)(f"Checkpoints: {mb:.1f} MB ({sessions} sessions)")
    perm = config.get("permission_mode", "auto")
    b.avertit(f"Permission mode: {perm} (all operations auto-approved)") \
        if perm == "accept-all" else b.passe(f"Permission mode: {perm}")


def conseil_defender(exclusions: list[str] | None, dossiers: list[str]) -> str:
    """Conseil d'exclusion Windows Defender pour `dossiers`, "" si tous sont déjà couverts.

    Mesure (session 1f5b8d96) : `git worktree add` = 1784 fichiers en ~28 s à froid, ~16 ms par
    fichier, contre 2,2 s à chaud — l'inspection temps réel taxe chaque écriture ; c'est ce
    qui fait durer `Environment(action='worktree')` ~30 s. `exclusions` = None quand la liste
    est illisible (sans droits administrateur, Defender la masque). Pur : testable partout."""
    import ntpath

    def _couvert(dossier: str) -> bool:
        d = ntpath.normcase(ntpath.normpath(dossier))
        for ex in exclusions or []:
            e = ntpath.normcase(ntpath.normpath(ex)).rstrip("\\")
            if d == e or d.startswith(e + "\\"):
                return True
        return False

    manquants = [d for d in dossiers if not _couvert(d)]
    if not manquants:
        return ""
    commandes = "\n".join(f'    Add-MpPreference -ExclusionPath "{d}"' for d in manquants)
    entete = ("Exclusions Defender illisibles (il faut les droits administrateur pour "
              "`Get-MpPreference`). " if exclusions is None else
              "Dossiers non exclus de Windows Defender. ")
    return (entete + "Chaque worktree d'agent écrit ~1800 fichiers : ~16 ms par fichier "
            "inspecté, soit ~30 s par Environment(action='worktree'). Dans un PowerShell "
            "lancé en administrateur :\n" + commandes +
            "\n  (Poste géré par GPO : demander l'exclusion au support.)")


def _verifier_antivirus(b: _Bilan) -> None:
    """Windows seulement : les dossiers où s'écrivent les worktrees sont-ils exclus ?"""
    if sys.platform != "win32":
        return
    from ...core.context import harness_repo
    dossiers = [str(bouzecode_data_dir() / "worktrees")]
    racine, depot = harness_repo()
    dossiers += [str(p) for p in (depot or racine,) if p]
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-MpPreference).ExclusionPath"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        lignes = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        exclusions = None if (out.returncode != 0 or any("N/A" in ln for ln in lignes)) \
            else lignes
    except Exception:  # noqa: BLE001 — Defender absent/indisponible : on conseille quand même
        exclusions = None
    conseil = conseil_defender(exclusions, dossiers)
    b.avertit(conseil) if conseil else b.passe("Windows Defender : worktrees exclus")


def cmd_doctor(args: str, state, config) -> bool:
    """Show session status and run installation health checks."""
    _afficher_session(state, config)
    b = _Bilan()
    print(clr("  ── Environment ──", "bold"))
    _verifier_outils(b)
    _verifier_antivirus(b)
    _verifier_fournisseur(b, config)
    print()
    _verifier_autres_cles(b, config)
    print()
    _verifier_modules(b)
    print()
    _verifier_fichiers(b, config)
    print()
    b.resume()
    return True
