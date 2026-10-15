# [desc] Garde-fou : aucun client LLM (SDK Anthropic/OpenAI, POST vers /v1/messages ou /chat/completions) n'est construit hors de backend/agent/providers/. [/desc]
"""Tout appel LLM passe par la voie commune (`get_streamer()` → `dispatch.stream`, modèle de la
session via `side_model.modele_annexe`). Un client construit ailleurs ignore le fournisseur,
l'URL et la clé de la session, et casse au premier changement du SDK : c'était le cas de
`/doctor` (POST en dur vers api.anthropic.com) et de `readme_sync` (TypeError httpx).

Le test lit le CODE (AST) de src/bouzecode : les commentaires et docstrings ne comptent pas,
seuls les appels et les chaînes réellement utilisées.
"""
from __future__ import annotations

import ast
from pathlib import Path

import bouzecode

SRC = Path(bouzecode.__file__).resolve().parent
VOIE_COMMUNE = "backend/agent/providers/"

# Exclusions TEMPORAIRES, à retirer dès que le code concerné passe par la voie commune.
# Vide : agents_map (dernier client en dur) a été supprimé au profit de FindCode.
LISTE_BLANCHE: set[str] = set()

_CONSTRUCTEURS = {"Anthropic", "AsyncAnthropic", "OpenAI", "AsyncOpenAI", "AnthropicBedrock"}
_MARQUEURS_URL = ("/v1/messages", "/chat/completions", "api.anthropic.com", "openrouter.ai/api")


def _nom_appele(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _docstrings(tree: ast.AST) -> set[int]:
    """id() des constantes qui sont des docstrings (texte, pas du code)."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            ids.add(id(node.value))
    return ids


def violations(source: str) -> list[str]:
    """Les constructions de client LLM du source, sous forme lisible « ligne: motif »."""
    tree = ast.parse(source)
    textes = _docstrings(tree)
    trouve = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _nom_appele(node) in _CONSTRUCTEURS:
            trouve.append(f"{node.lineno}: {_nom_appele(node)}(...)")
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in textes):
            for marqueur in _MARQUEURS_URL:
                if marqueur in node.value:
                    trouve.append(f"{node.lineno}: URL LLM {node.value!r}")
    return trouve


def _hors_perimetre(rel: str) -> bool:
    nom = rel.rsplit("/", 1)[-1]
    return (rel.startswith(VOIE_COMMUNE) or "/tests/" in f"/{rel}"
            or nom.startswith("test_") or nom == "conftest.py"
            or any(rel.startswith(p) for p in LISTE_BLANCHE))


def test_le_detecteur_voit_les_constructions_et_ignore_la_prose():
    code = (
        'import anthropic, openai, urllib.request\n'
        '"""Doc : on appelait https://api.anthropic.com/v1/messages ici."""\n'
        '# commentaire : openai.OpenAI(...)\n'
        'c = anthropic.Anthropic(api_key="k")\n'
        'o = openai.OpenAI()\n'
        'urllib.request.Request("https://h/v1/messages", data=b"{}")\n'
        'u = f"{base}/chat/completions"\n'
    )
    assert [v.split(":")[0] for v in violations(code)] == ["4", "5", "6", "7"]


def test_aucun_client_llm_hors_de_la_voie_commune():
    fautifs = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if _hors_perimetre(rel):
            continue
        trouve = violations(path.read_text(encoding="utf-8"))
        if trouve:
            fautifs[rel] = trouve
    assert not fautifs, (
        "Client LLM construit hors de backend/agent/providers/ — passer par get_streamer() "
        f"et side_model.modele_annexe(config) : {fautifs}"
    )

