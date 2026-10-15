# [desc] Invariants de cohérence de l'interface vérifiés PENDANT chaque E2E : fonctions pures sur un instantané (arbre, tâches, boîte, compteurs) + surveillant en fond qui ne signale qu'une violation qui DURE. [/desc]
"""Vérificateur d'invariants des E2E du bac à sable.

Les tests E2E vérifient ce qu'on a pensé à vérifier. Les bugs trouvés en recette avec un vrai
modèle (manager « Attend ses sous-agents » alors qu'il travaille, agent tué par sa propre
intégration, sous-agent crashé compté comme vivant) venaient d'ENCHAÎNEMENTS que personne
n'avait écrits. Ce module interroge le serveur en fond pendant chaque test et fait échouer le
test si une règle de cohérence est violée — quel que soit le parcours joué.

`violations(instantane)` est PURE (testée avec des arbres construits à la main) ; `Surveillant`
la rejoue toutes les ~0,5 s et ne retient qu'une violation qui persiste `PERSISTANCE` secondes :
l'arbre, la boîte et les compteurs sont servis par des caches distincts, un écart de quelques
secondes entre deux lectures n'est pas un bug d'interface.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field

PERSISTANCE = float(os.environ.get("BZ_INVARIANTS_PERSISTANCE", "6"))
#  Les pastilles avaient droit à 30 s : elles passaient par une mémoire à elles, recalculée en
#  fond sur une AUTRE page d'arbre que la page Agents, et l'écart (jusqu'à 15 s mesurées) était
#  pris pour de la charge. Elles lisent désormais la boîte et l'état montré par l'arbre
#  (`fleet_vue`) : un écart qui dure est un bug comme un autre.
PERSISTANCE_COMPTEURS = float(os.environ.get("BZ_INVARIANTS_PERSISTANCE_COMPTEURS", str(PERSISTANCE)))
PERIODE = 0.5

ACTIFS = {"running", "thinking", "preparing", "orchestrating", "awaiting_input", "awaiting_plan_validation"}
TRAVAILLE = {"running", "thinking"}
#  « idle » = process CHAUD vivant (warm pool) : une relance lui est livrée sans respawn.
PROCESS_VIVANT = {"running", "awaiting_input", "idle"}
#  SPEC §1 : mots bannis de l'interface.
MOTS_BANNIS = ("ticket", "micro", "macro", "puce", "to-do", "todo", "run", "typologie", "manager",
               "cli", "chaud", "shared", "worktree")
_BANNI_RE = re.compile(r"\b(" + "|".join(re.escape(m) for m in MOTS_BANNIS) + r")\b", re.I)


@dataclass(frozen=True)
class Violation:
    regle: str
    cle: str          # identifie la violation d'un instantané à l'autre (même agent, même règle)
    preuve: str


# ─────────────────────────────── lecture de l'instantané ───────────────────────────────

def _noeuds(inst: dict) -> list[dict]:
    return [n for n in (inst.get("arbre") or {}).get("nodes") or [] if isinstance(n, dict)]


def _id(n: dict) -> str:
    return str(n.get("agent_id") or str(n.get("key") or "").replace("agent/", ""))


def _parent(n: dict) -> str:
    return str(n.get("parent") or "").replace("agent/", "")


def _taches(inst: dict) -> list[dict]:
    lignes = inst.get("lignes") or {}
    out = [t for c in lignes.get("chantiers") or [] for t in c.get("lignes") or []]
    return out + list(lignes.get("non_rattachees") or [])


def _descendants(racine: str, noeuds: list[dict]) -> list[dict]:
    enfants = {}
    for n in noeuds:
        enfants.setdefault(_parent(n), []).append(n)
    vus, pile, out = {racine}, [racine], []
    while pile:
        for e in enfants.get(pile.pop(), []):
            if _id(e) not in vus:
                vus.add(_id(e))
                out.append(e)
                pile.append(_id(e))
    return out


# ─────────────────────────────── règles (pures) ───────────────────────────────

def orchestration_sans_enfant_actif(inst: dict) -> list[Violation]:
    """« Attend ses sous-agents » ⇒ au moins un descendant réellement actif (un enfant crashé
    ou fini n'est jamais « vivant »)."""
    noeuds, out = _noeuds(inst), []
    for n in noeuds:
        if n.get("etat") != "orchestrating":
            continue
        actifs = [_id(d) for d in _descendants(_id(n), noeuds) if d.get("etat") in ACTIFS - {"orchestrating"}]
        if not actifs:
            etats = {_id(d): d.get("etat") for d in _descendants(_id(n), noeuds)}
            out.append(Violation("orchestration_sans_enfant_actif", _id(n),
                                 f"{_id(n)} affiché « Attend ses sous-agents » ; descendants : {etats or 'aucun'}"))
    return out


def travaille_sans_process(inst: dict) -> list[Violation]:
    """Un agent affiché « En cours » / « Le modèle lit… » a un process vivant."""
    return [Violation("travaille_sans_process", _id(n),
                      f"{_id(n)} affiché {n.get('etat')!r} mais liveness={n.get('liveness')!r}")
            for n in _noeuds(inst)
            if n.get("etat") in TRAVAILLE and n.get("liveness") not in PROCESS_VIVANT]


def _dernier_appel_sans_resultat(session_path: str) -> str:
    try:
        with open(session_path, encoding="utf-8") as f:
            messages = json.load(f).get("messages") or []
    except (OSError, ValueError):
        return ""
    for i in range(len(messages) - 1, -1, -1):
        appels = messages[i].get("tool_calls") or []
        if messages[i].get("role") == "assistant" and appels:
            resultats = {m.get("tool_call_id") for m in messages[i + 1:] if m.get("role") == "tool"}
            for a in appels:
                if a.get("id") not in resultats:
                    return f"{a.get('name')}({json.dumps(a.get('input'), ensure_ascii=False)[:60]})"
            return ""
    return ""


def tue_par_son_propre_outil(inst: dict) -> list[Violation]:
    """Un agent mort par signal (returncode -9/-15) en plein appel d'Environment (intégration,
    nettoyage) a été tué par sa propre action."""
    out = []
    for n in _noeuds(inst):
        if n.get("returncode") not in (-9, -15) or not n.get("session_path"):
            continue
        appel = _dernier_appel_sans_resultat(str(n["session_path"]))
        if appel.startswith("Environment"):
            out.append(Violation("tue_par_son_propre_outil", _id(n),
                                 f"{_id(n)} mort (returncode {n.get('returncode')}) pendant {appel}"))
    return out


def passages_incoherents(inst: dict) -> list[Violation]:
    """Travail intégré ⇒ jamais « En échec » ni « Arrêté sans finir » ; jamais deux agents
    actifs sur la même tâche ; récap lisible (pas découpé caractère par caractère)."""
    out = []
    for t in _taches(inst):
        passages = t.get("passages") or []
        actifs = [p.get("agent_id") for p in passages if p.get("etat") in ACTIFS]
        if len(actifs) > 1:
            out.append(Violation("deux_agents_actifs", str(t.get("id")),
                                 f"tâche {t.get('id')} : agents actifs {actifs}"))
        if passages and passages[0].get("integre") is True and t.get("statut_ui") == "en_echec":
            out.append(Violation("integre_mais_en_echec", str(t.get("id")),
                                 f"tâche {t.get('id')} « En échec » alors que son dernier passage est intégré"))
        for p in passages:
            if p.get("integre") is True and p.get("etat") == "crashed":
                out.append(Violation("integre_mais_arrete", str(p.get("agent_id")),
                                     f"passage {p.get('agent_id')} « Arrêté sans finir » alors que son travail est intégré"))
            for cle in ("fait", "reste", "a_decider"):
                items = (p.get("recap") or {}).get(cle) or []
                if len(items) > 2 and all(isinstance(i, str) and len(i) <= 1 for i in items):
                    out.append(Violation("recap_decoupe", f"{p.get('agent_id')}:{cle}",
                                         f"passage {p.get('agent_id')} : recap.{cle} découpé en caractères {items[:6]}…"))
    return out


def compteurs_incoherents(inst: dict) -> list[Violation]:
    """Pastilles de navigation = ce que montrent la boîte et l'arbre.

    Chaque pastille est comparée à la page qu'elle résume lue JUSTE avant elle (`nav_arbre` après
    l'arbre, `nav` après la boîte), comme le navigateur les montre côte à côte : entre l'arbre
    et la fin de l'instantané, /api/lignes et /api/inbox prennent des centaines de ms, pendant
    lesquelles un agent du bac naît ou finit — un écart de LECTURE, pas d'interface."""
    nav, boite = inst.get("nav") or {}, inst.get("boite") or {}
    out = []
    if "a_moi" in nav and "compte" in boite and nav["a_moi"] != boite["compte"]:
        out.append(Violation("compteur_a_moi", "a_moi", f"nav a_moi={nav['a_moi']} ≠ boîte {boite['compte']}"))
    nav = inst.get("nav_arbre") or nav
    if "en_cours" in nav and inst.get("arbre"):
        travaillent = sorted(_id(n) for n in _noeuds(inst) if n.get("etat") in TRAVAILLE | {"preparing"})
        if nav["en_cours"] != len(travaillent):
            out.append(Violation("compteur_en_cours", "en_cours",
                                 f"nav en_cours={nav['en_cours']} ≠ agents affichés au travail {travaillent}"))
    return out


def mots_bannis(inst: dict) -> list[Violation]:
    """SPEC §1 : aucun mot technique banni dans les libellés servis."""
    out = []
    textes = [(f"agent {_id(n)}.libelle_etat", n.get("libelle_etat")) for n in _noeuds(inst)]
    for t in _taches(inst):
        textes += [(f"tâche {t.get('id')}.libelle_statut", t.get("libelle_statut")),
                   (f"tâche {t.get('id')}.raison_echec", t.get("raison_echec"))]
        textes += [(f"passage {p.get('agent_id')}.libelle_etat", p.get("libelle_etat")) for p in t.get("passages") or []]
    for ou, texte in textes:
        m = _BANNI_RE.search(str(texte or ""))
        if m:
            out.append(Violation("mot_banni", f"{ou}:{m.group(1).lower()}", f"{ou} = {str(texte)[:120]!r} (« {m.group(1)} »)"))
    return out


REGLES = (orchestration_sans_enfant_actif, travaille_sans_process, tue_par_son_propre_outil,
          passages_incoherents, compteurs_incoherents, mots_bannis)


def violations(inst: dict) -> list[Violation]:
    return [v for regle in REGLES for v in regle(inst)]


def a_signaler_au_depart(vues: list[Violation]) -> list[Violation]:
    """Ce que le relevé « déjà violés au début des tests » (UN instantané) peut affirmer : pas
    les pastilles. Globales et recalculées à chaque lecture, elles ne s'« héritent » d'aucune
    donnée ; un écart d'un instant entre deux lectures n'est pas une violation (règle du module :
    seule compte celle qui DURE), et la surveillance fait échouer le test si l'écart dure."""
    return [v for v in vues if not v.regle.startswith("compteur_")]


# ─────────────────────────────── surveillance en fond ───────────────────────────────

def _lire(base: str, chemin: str):
    with urllib.request.urlopen(f"{base}{chemin}", timeout=20) as r:
        return json.loads(r.read().decode())


def instantane(base: str) -> dict:
    inst = {"t": time.time()}
    #  Chaque pastille est lue juste après la page qu'elle résume (cf. `compteurs_incoherents`).
    for cle, chemin in (("arbre", "/api/agents/tree?offset=0&limit=500"),
                        ("nav_arbre", "/api/nav/counts"), ("lignes", "/api/lignes?complet=1"),
                        ("boite", "/api/inbox"), ("nav", "/api/nav/counts")):
        try:
            inst[cle] = _lire(base, chemin)
        except Exception:  # noqa: BLE001 — un endpoint absent (serveur Profils) n'est pas une violation
            inst[cle] = None
    return inst


@dataclass
class Surveillant:
    """Rejoue `violations` en fond ; ne retient que celles qui DURENT `persistance` secondes."""
    bases: list[str]
    persistance: float = PERSISTANCE
    ignorer: set = field(default_factory=set)
    _debut: dict = field(default_factory=dict)
    retenues: dict = field(default_factory=dict)
    _stop: threading.Event = field(default_factory=threading.Event)
    _fil: threading.Thread | None = None

    def observer(self, base: str, inst: dict) -> None:
        maintenant = inst.get("t", time.time())
        vues = {(base, v.regle, v.cle): v for v in violations(inst)
                if (base, v.regle, v.cle) not in self.ignorer}
        for cle, v in vues.items():
            debut = self._debut.setdefault(cle, maintenant)
            seuil = max(self.persistance, PERSISTANCE_COMPTEURS) if v.regle.startswith("compteur_") \
                else self.persistance
            if maintenant - debut >= seuil:
                self.retenues[cle] = (debut, maintenant, v)
        for cle in list(self._debut):
            if cle not in vues:
                del self._debut[cle]

    def _boucle(self) -> None:
        while not self._stop.is_set():
            for base in self.bases:
                self.observer(base, instantane(base))
            self._stop.wait(PERIODE)

    def demarrer(self) -> "Surveillant":
        self._fil = threading.Thread(target=self._boucle, daemon=True)
        self._fil.start()
        return self

    def arreter(self) -> list[str]:
        self._stop.set()
        if self._fil:
            self._fil.join(timeout=30)
        return [f"[{v.regle}] {time.strftime('%H:%M:%S', time.localtime(debut))}→"
                f"{time.strftime('%H:%M:%S', time.localtime(fin))} ({fin - debut:.0f} s) {v.preuve}"
                for debut, fin, v in self.retenues.values()]
