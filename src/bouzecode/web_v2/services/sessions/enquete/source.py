# [desc] Charge UNE fois (et met en cache) tout ce qu'il faut pour enquêter sur une session : appels annotés, payloads, réponses. [/desc]
"""La matière de l'enquête, lue une fois par version des fichiers.

Une session longue (500 tours, note de 400 000 caractères) coûte cher à replier : on garde
le résultat en mémoire, indexé par (chemin, version de la session et du journal des payloads
— cf. `context_viewer.builder`). Une écriture de l'agent change une version → rechargement au
prochain appel.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field


from ....runtime.context_viewer.builder import extraire_avec_session, version_de_session
from .. import store

_MAX_SESSIONS = 4
_cache: "OrderedDict[tuple, Enquete]" = OrderedDict()
_verrou = threading.Lock()


@dataclass
class Enquete:
    agent_id: str
    session_path: str
    data: dict
    calls: list[dict]
    dumps: dict
    reponses: list[dict] = field(default_factory=list)   # une entrée par appel, dans l'ordre
    memo: dict = field(default_factory=dict)             # vues coûteuses déjà calculées

    def memoise(self, cle: str, calcul):
        if cle not in self.memo:
            self.memo[cle] = calcul()
        return self.memo[cle]

    def appel(self, tour: int) -> dict | None:
        return next((c for c in self.calls if c.get("turn") == tour), None)

    def indice(self, tour: int) -> int | None:
        return next((i for i, c in enumerate(self.calls) if c.get("turn") == tour), None)




def _reponses(messages: list[dict]) -> list[dict]:
    """Découpe l'historique en réponses : un message assistant + les résultats d'outils qui
    le suivent. La n-ième réponse correspond au n-ième appel LLM (convention de `analysis`)."""
    reponses: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            reponses.append({"assistant": msg, "resultats": []})
        elif role == "tool" and reponses:
            reponses[-1]["resultats"].append(msg)
    return reponses


def _cle(session_path: str) -> tuple:
    """(chemin, version de la session et du journal) — sans décoder la session : la version
    vient de `builder`, qui connaît le session_id depuis la dernière lecture. Avant, chaque
    requête de l'enquête décodait la session entière rien que pour construire cette clé."""
    return (session_path, version_de_session(session_path))



# Champs du journal `llm_call` que la vue par appel du context_viewer ne reprend pas.
_CHAMPS_DU_JOURNAL = ("provider", "prefixe_change", "note_allongee", "note_divergence",
                      "note_perdue", "note_extrait", "note_extrait_nouveau")


def _phases_par_appel(journal: list[dict]) -> dict:
    """``{tour: [phases]}`` : passes du harnais (compaction, purge d'extraits, filet…)
    journalisées entre l'appel principal précédent et celui de ce tour."""
    phases, courantes = {}, []
    for entree in journal:
        if entree.get("event") == "llm_call":
            phases[entree.get("turn")] = courantes
            courantes = []
        elif entree.get("phase"):
            courantes.append(entree["phase"])
    return phases


def _avec_journal(calls: list[dict], journal: list[dict]) -> list[dict]:
    """Chaque appel reçoit fournisseur, première partie du préfixe changée (et le détail de la
    note), lus au journal, plus les passes qui ont réécrit la note depuis l'appel précédent."""
    par_tour = {e.get("turn"): e for e in journal if e.get("event") == "llm_call"}
    phases = _phases_par_appel(journal)
    sortie = []
    for appel in calls:
        entree = par_tour.get(appel.get("turn")) or {}
        sortie.append({**appel, **{k: entree[k] for k in _CHAMPS_DU_JOURNAL if k in entree},
                       "phases_note": phases.get(appel.get("turn"), [])})
    return sortie


def _construire(agent_id: str, session_path: str) -> tuple[Enquete | None, tuple | None]:
    """L'enquête et la version des fichiers d'où elle vient : UNE lecture de la session et
    UNE du journal (avant : trois décodages de la session et deux replis du journal)."""
    extrait, data, dumps, version = extraire_avec_session(session_path)
    if extrait is None or extrait.get("missing_dumps"):
        return None, None
    enquete = Enquete(agent_id=agent_id, session_path=session_path, data=data,
                      calls=_avec_journal(extrait["calls"], data.get("compaction_log") or []),
                      dumps=dumps,
                      reponses=_reponses(data.get("messages") or []))
    return enquete, version


def _chemin_de_session(agent_id: str) -> str | None:
    ref = store.resolve(f"agent/{agent_id}")
    return str(ref.path) if ref is not None else None


def charger(agent_id: str) -> Enquete | None:
    """L'enquête d'un agent, ou None (agent inconnu, ou session sans journal de payloads)."""
    session_path = _chemin_de_session(agent_id)
    if session_path is None:
        return None
    cle = _cle(session_path)
    with _verrou:
        if cle in _cache:
            _cache.move_to_end(cle)
            return _cache[cle]
    enquete, version = _construire(agent_id, session_path)
    if enquete is None:
        return None
    with _verrou:
        _cache[(session_path, version)] = enquete
        while len(_cache) > _MAX_SESSIONS:
            _cache.popitem(last=False)
    return enquete


def oublier() -> None:
    """Vide le cache (tests)."""
    with _verrou:
        _cache.clear()
