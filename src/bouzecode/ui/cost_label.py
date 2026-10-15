"""Label du coût en $ affiché dans le récapitulatif de fin de tour du REPL."""
from __future__ import annotations

from bouzecode.backend.agent.providers.registry import calc_cost, is_priced


def session_cost_label(model: str | None, input_tokens: int, output_tokens: int,
                       cache_read: int = 0, cache_write: int = 0) -> str:
    """Coût cumulé de la session, ex. ``"$0.1234"``.

    ``input_tokens`` suit la convention de la chaîne : écriture de cache COMPRISE,
    lecture de cache à part (voir ``registry.calc_cost``).
    Modèle sans tarif connu : ``"cost n/a (<model> unpriced)"`` plutôt qu'un faux $0.
    """
    if not model or not is_priced(model):
        return f"cost n/a ({model or 'unknown model'} unpriced)"
    cost = calc_cost(model, input_tokens, output_tokens, cache_read, cache_write)
    return f"${cost:,.4f}"


def total_session_label(model: str | None, input_tokens: int, output_tokens: int,
                        cache_read: int = 0, cache_write: int = 0, registre=None) -> str:
    """Coût de l'agent principal ET total de la session (principal + sous-agents).

    Sans sous-agent : identique à ``session_cost_label``.
    Avec sous-agents : ``"main $0.1000 · total $0.3500"`` ; un sous-agent dont le
    modèle n'a pas de tarif connu rend le total ``(partiel)`` plutôt que faux.
    """
    main_label = session_cost_label(model, input_tokens, output_tokens, cache_read, cache_write)
    sous_agents = registre.sous_agents() if registre is not None else []
    if not sous_agents:
        return main_label
    main_priced = bool(model) and is_priced(model)
    total = calc_cost(model, input_tokens, output_tokens, cache_read, cache_write) if main_priced else 0.0
    partiel = not main_priced
    for fiche in sous_agents:
        cout = fiche.cout()
        if cout is None:
            partiel = True
        else:
            total += cout
    suffixe = " (partiel)" if partiel else ""
    return f"main {main_label} · total ${total:,.4f}{suffixe} ({len(sous_agents)} sous-agents)"
