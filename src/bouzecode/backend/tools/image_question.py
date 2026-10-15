# [desc] Outil ImageQuestion : une question fermée sur des images, posée à un modèle dans un appel annexe (sans la note ni le prompt de l'agent) ; seule la réponse texte revient. [/desc]
"""ImageQuestion(paths, question) — regarder une image sans la faire entrer dans le contexte.

Rapport docs/reduction_tokens §4.3. L'agent ne reçoit jamais l'image : un appel annexe par
image, par la voie commune des appels LLM (`get_streamer` → `dispatch.stream`, reprises,
diagnostic et comptage de tokens compris), reçoit un system court, la question et l'image
(bloc `image` pour Anthropic, `image_url` en data URI pour OpenAI/OpenRouter, cf.
`openrouter_native.user_content`), et rend une réponse courte. Pas de note Methodology, pas
de prompt d'agent, raisonnement API coupé et `max_tokens` de 4096 (≥ 2048 : un budget plus
petit se fait manger par la réflexion — réponse vide, cf. audit de compaction).

Modèle : `vision_model` de la config s'il est posé (repli pour un modèle de session sans
vision), sinon le modèle de la session (`side_model.modele_annexe`).
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_SYSTEM = (
    "Tu examines une image pour un agent de code qui ne peut pas la voir. Réponds à sa question "
    "en français, en 1 à 3 phrases : d'abord OUI, NON ou la valeur demandée, puis ce que tu vois "
    "qui le justifie. N'invente rien : si l'image ne permet pas de répondre, dis-le."
)
_MAX_TOKENS = 4096
_IMAGES_MAX = 12
_PARALLELE = 4

SCHEMA = {
    "name": "ImageQuestion",
    "description": (
        "Pose une question sur des images (captures, figures) à un modèle qui les voit ; tu ne "
        "reçois que sa réponse texte, une par image. Question fermée et vérifiable (« Le bouton "
        "Valider est-il visible en bas à droite ? », « Combien de barres ? »), pas « Décris l'image »."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "Chemins des images (png, jpg, gif, webp)."},
            "question": {"type": "string"},
        },
        "required": ["paths", "question"],
    },
}


def _modele(config: dict) -> str:
    from ..agent.providers.side_model import modele_annexe
    return str(config.get("vision_model") or "") or modele_annexe(config)


def _config_annexe(config: dict) -> dict:
    """Copie de la config de la boucle, comme les autres appels annexes (thinking_summary,
    compact_judge) : ni note (`_context_state`), ni profil d'agent (`_depth` > 0), pas d'outil
    forcé, raisonnement API coupé (`thinking_level` pour Anthropic, `native_reasoning` pour
    OpenRouter), budget de sortie de 4096."""
    side = dict(config)
    side["_depth"] = config.get("_depth", 0) + 1
    side["_context_state"] = None
    side["max_tokens"] = _MAX_TOKENS
    side["thinking_level"] = "none"
    side["native_reasoning"] = False
    side["_call_label"] = "image_question"
    side.pop("_tool_choice", None)
    return side


def _une_image(chemin: str, question: str, model: str, config: dict) -> str:
    """Un appel annexe par la voie commune (`get_streamer` → `dispatch.stream`) : le provider
    reçoit un bloc image (Anthropic) ou une partie `image_url` (OpenAI), selon sa famille."""
    from ..agent.providers import AssistantTurn
    from ..agent.providers.side_model import signaler_echec
    from ..agent.stream_interceptor import get_streamer
    from .ops.image_ref import MIMES

    p = Path(chemin)
    mime = MIMES.get(p.suffix.lower())
    if mime is None or not p.is_file():
        return f"{chemin} : introuvable ou pas une image (png, jpg, gif, webp, bmp)."
    image = {"type": "image", "source": {"type": "base64", "media_type": mime,
                                         "data": base64.b64encode(p.read_bytes()).decode("ascii")}}
    texte = ""
    try:
        for ev in get_streamer()(model=model, system=_SYSTEM, tool_schemas=[],
                                 messages=[{"role": "user", "content": [image, {"type": "text", "text": question}]}],
                                 config=_config_annexe(config)):
            if isinstance(ev, AssistantTurn):
                texte = ev.text or ""
    except Exception as exc:  # noqa: BLE001 — une image en échec ne tue ni les autres ni la session
        signaler_echec("ImageQuestion", model, exc)
        return f"{chemin} : échec de l'appel ({type(exc).__name__}: {str(exc)[:200]})."
    return f"{chemin} : {texte.strip() or '(réponse vide)'}"


def image_question(params: dict, config: dict) -> str:
    chemins = [c for c in params.get("paths") or [] if isinstance(c, str) and c.strip()]
    question = str(params.get("question") or "").strip()
    if not chemins or not question:
        return "Error: ImageQuestion attend paths (liste non vide) et question."
    model = _modele(config)
    #  Au-delà de `_IMAGES_MAX`, découpées ici en lots plutôt que refusées : un appel annexe
    #  par image de toute façon, et l'agent n'a rien à gagner à refaire le découpage lui-même.
    #  Essai du 2026-09-25 : « 15 images, 12 au plus par appel » a coûté un tour à la racine,
    #  qui a ensuite mal refait ses lots (réponses vides).
    reponses: list[str] = []
    for debut in range(0, len(chemins), _IMAGES_MAX):
        lot = chemins[debut:debut + _IMAGES_MAX]
        with ThreadPoolExecutor(max_workers=min(_PARALLELE, len(lot))) as pool:
            reponses += pool.map(lambda c: _une_image(c, question, model, config), lot)
    return "\n".join(reponses)
