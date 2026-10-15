# [desc] Lot d'appels vides (`{}`) sur claude-opus-5-5 : le flux le porte tel quel, et le fil minimal ne doit plus montrer au modèle un historique d'appels vides à imiter. [/desc]
"""Session dfd07836 (2026-10-05), tour 20 : `Methodology {}` et `Bash {}`.

`gateway_preprod_sse/` contient deux réponses SSE RÉELLES du rejeu de ce tour sur la préprod :
- `lot_vide_opus55.sse` : le modèle émet bien `arguments: "{}"` pour les deux appels. Rien
  n'est perdu entre le flux et la boucle : la cause est en amont, dans ce que le modèle VOIT.
- `lot_plein_opus55.sse` : le même tour, réussi.

Ce qu'il voyait : le fil minimal retire le message assistant du lot précédent, et les
convertisseurs natifs le redéclaraient depuis les résultats avec `input: {}`. Le modèle
recopiait ce lot vide (5 lots vides sur 22 rejeux ; 0 sur 12 avec les vrais arguments).
"""
from __future__ import annotations

import json
from pathlib import Path

from bouzecode.backend.agent.minimal_payload import build_minimal_payload
from bouzecode.backend.agent.providers.backends.anthropic_native import messages_to_anthropic_native
from bouzecode.backend.agent.providers.backends.openrouter_native import messages_to_openai_native
from bouzecode.backend.agent.providers.backends.openrouter_stream import stream_openrouter
from bouzecode.backend.agent.providers.types import AssistantTurn

SSE = Path(__file__).parent.parent / "gateway_preprod_sse"

NOTE = {"content": "T20 : skill azure-deployment lue ; vérifier l'épinglage de bouzecode."}
COMMANDE = {"command": "cd demo_application; type startup.sh"}
HISTORIQUE = [
    {"role": "user", "content": "Déploie demo_application."},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "tooluse_m", "name": "Methodology", "input": NOTE},
        {"id": "tooluse_b", "name": "Bash", "input": COMMANDE},
    ]},
    {"role": "tool", "tool_call_id": "tooluse_m", "name": "Methodology",
     "content": "methodology append: now 30198 chars"},
    {"role": "tool", "tool_call_id": "tooluse_b", "name": "Bash", "content": "gunicorn ..."},
]


class _Reponse:
    status_code, ok, encoding, text = 200, True, "utf-8", ""

    def __init__(self, lignes: list[str]) -> None:
        self.lignes = lignes

    def iter_lines(self, decode_unicode=False):
        return iter(self.lignes)


class _GatewayEnregistre:
    def __init__(self, fichier: str) -> None:
        self.lignes = (SSE / fichier).read_text(encoding="utf-8").splitlines()

    def post(self, url, **kw):
        return _Reponse(self.lignes)


def _appels_rejoues(fichier: str) -> list[dict]:
    evenements = stream_openrouter(
        "cle-de-test", "claude-opus-5-5", "Tu es un agent.", [{"role": "user", "content": "go"}],
        [], {"max_tokens": 8192}, base_url="https://gateway.test/v1",
        session_factory=lambda: _GatewayEnregistre(fichier), send_reasoning=False)
    tour = next(e for e in evenements if isinstance(e, AssistantTurn))
    return tour.tool_calls


def test_le_flux_fautif_porte_deja_des_arguments_vides():
    appels = _appels_rejoues("lot_vide_opus55.sse")
    assert [(a["name"], a["input"]) for a in appels] == [("Methodology", {}), ("Bash", {})]


def test_le_flux_reussi_rend_ses_arguments_entiers():
    appels = _appels_rejoues("lot_plein_opus55.sse")
    assert [a["name"] for a in appels] == ["Methodology", "Bash"]
    assert appels[0]["input"]["content"] and appels[1]["input"]["command"]


def test_fil_openai_redeclare_le_lot_precedent_avec_ses_vrais_arguments():
    fil = messages_to_openai_native(build_minimal_payload(HISTORIQUE), "system")
    appels = next(m for m in fil if m["role"] == "assistant")["tool_calls"]
    # Methodology n'est plus redéclaré du tout (test_methodology_hors_fil) : reste Bash, entier.
    assert [(a["function"]["name"], json.loads(a["function"]["arguments"])) for a in appels] == [
        ("Bash", COMMANDE)]
    assert all(set(m) <= {"role", "tool_call_id", "content"} for m in fil if m["role"] == "tool")


def test_fil_anthropic_redeclare_le_lot_precedent_avec_ses_vrais_arguments():
    fil = messages_to_anthropic_native(build_minimal_payload(HISTORIQUE), cache_last=False)
    blocs = [b for b in fil[0]["content"] if b.get("type") == "tool_use"]
    assert [(b["name"], b["input"]) for b in blocs] == [("Bash", COMMANDE)]
