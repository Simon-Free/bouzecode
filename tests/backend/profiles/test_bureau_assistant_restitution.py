"""L'assistant du Bureau parle a l'humain en TACHES et TICKETS, pas en commits ni branches.

Un SHA de commit ou un nom de branche `agent/...` est du bruit pour l'humain : le prompt du
profil `bureau-assistant` doit l'interdire, exiger le francais, et ne contenir aucune
consigne contraire (citer un commit). On lit la prose telle que l'agent la recoit, via le
mecanisme de composition du depot (`context.get_agent_profile_extra`).
"""
import re
import unicodedata

from bouzecode.backend.core import context, profile_extra


def _prose(monkeypatch, tmp_path) -> str:
    monkeypatch.chdir(tmp_path)  # aucun profil de projet ne vient surcharger le builtin
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    txt = context.get_agent_profile_extra("bureau-assistant") or ""
    # insensible aux accents et a la casse
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return txt.lower()


_NEGATION = re.compile(r"\b(jamais|ni|pas|interdit|sans)\b")


def test_livraison_designee_par_tache_et_ticket_pas_par_commit(monkeypatch, tmp_path):
    prose = _prose(monkeypatch, tmp_path)
    assert prose, "prompt bureau-assistant introuvable"
    assert "francais" in prose
    lignes = [l for l in prose.splitlines() if "commit" in l or "sha" in l.split()]
    assert lignes, "aucune consigne sur les commits dans le prompt"
    # la consigne qui parle de commit designe la livraison par tache + ticket
    bloc = " ".join(prose.split())
    assert re.search(r"livraison[^.]*tache[^.]*ticket[^.]*jamais[^.]*commit", bloc), bloc


def test_aucune_consigne_ne_demande_de_citer_un_commit_ou_une_branche(monkeypatch, tmp_path):
    prose = _prose(monkeypatch, tmp_path)
    phrases = re.split(r"(?<=[.;:])\s+|\n\s*-\s+", " \n".join(prose.splitlines()))
    for ph in phrases:
        if re.search(r"\bcommits?\b|\bsha\b|\bbranches? git\b|agent/", ph):
            assert _NEGATION.search(ph), f"consigne positive sur commit/branche : {ph!r}"
