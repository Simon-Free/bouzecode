"""Ce que l'agent distant doit recevoir pour parler au LLM : le modele et les variables de SON fournisseur.

Mesure du 2026-10-06 (execution 257420) : le modele par defaut (claude-opus-5-5) est servi par le
gateway PREPROD (fournisseur `gateway_preprod`, cle OPENAI_API_KEY_PP, URL PREPROD_ENDPOINT) ; n'envoyer que
les variables ANTHROPIC_* faisait echouer l'agent sur « No internal LLM gateway preprod key found ». On lit donc
les variables dans le registre des fournisseurs, pour le modele effectivement lance.
Les valeurs ne sont jamais journalisees : seules les NOMS sortent d'ici dans un message.
"""
import os

PREFIXE_OPTION = "LLM_"


def modele_par_defaut() -> str:
    from bouzecode.backend.core.config import load_config
    return str(load_config().get("model") or "")


def noms_variables(modele: str) -> tuple[list[str], str]:
    """(variables de cle candidates, variable d'URL) du fournisseur qui sert `modele`."""
    from bouzecode.backend.agent.providers.registry import PROVIDERS, resolve_provider
    fournisseur = PROVIDERS[resolve_provider(modele)[0]]
    return list(fournisseur.get("key_envs") or [fournisseur.get("api_key_env")]), fournisseur.get("base_url_env") or ""


def variables_pour(modele: str) -> tuple[dict[str, str], list[str]]:
    """(variables presentes a transmettre, noms manquants). Manquant = aucune cle, ou URL absente."""
    cles, url = noms_variables(modele)
    presentes = {nom: os.environ[nom] for nom in [*cles, url] if nom and os.environ.get(nom)}
    manquants = [] if any(nom in presentes for nom in cles) else cles
    if url and url not in presentes:
        manquants.append(url)
    return presentes, manquants
