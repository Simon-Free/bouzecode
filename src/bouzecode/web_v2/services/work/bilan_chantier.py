# [desc] Vision d'ensemble d'un chantier pour l'assistant du Bureau : chaque tâche avec son statut, qui l'a créée et quand (utilisateur, assistant, clôture de tel agent), son brief, ses agents, le récap de ses livraisons, ses précisions — et les rapprochements évidents (doublons, suites d'une tâche reprise depuis). [/desc]
"""« Fais-moi le point sur le chantier X : quelles suites restent vraiment à faire ? »

Cas réel (Portail des énigmes, 2026-09-25) : 9 tâches ouvertes, dont une faite par la tâche
principale lors de son tour de retours, une qui doublait la carte « À vérifier », trois
« Étendre le scraping » et deux décisions Q25/Q26 identiques. Pour le voir, l'assistant devait
croiser `Taches(lister)`, les récaps de passage et la provenance de chaque ligne — il ne le
faisait pas, et proposait d'en lancer la moitié.

Un seul appel rend tout, en texte compact (le modèle lit du texte ; un JSON profond coûte trois
fois plus de jetons pour la même information). Les rapprochements ne sont que des SIGNAUX : c'est
l'assistant qui juge, avec l'utilisateur, ce qui est fait, en double ou caduc.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from bouzecode.web_v2.services.horodatage import cle_chrono

from . import classement, micros

BRIEF_MAX = 220
ITEM_MAX = 110
ITEMS_MAX = 6
ARCHIVEES_MAX = 15
_CLASSES = ("faite", "abandonnee")
_ID_TACHE = re.compile(r"(?<![0-9a-f])([0-9a-f]{8})(?![0-9a-f])")
_RELECTURE = re.compile(r"^\W*(relire|v[ée]rifier|valider|tester|recetter)\b", re.IGNORECASE)
_VIDES = {"les", "des", "une", "dans", "pour", "avec", "que", "qui", "sur", "par", "sans", "est",
          "aux", "the", "and", "plus", "pas", "tout", "tous", "cette", "ces", "son", "ses", "leur",
          "apres", "avant", "entre", "comme", "faire", "tache", "agent"}


# ------------------------------------------------------------------------------ outils texte


def _court(texte: object, maximum: int) -> str:
    plat = " ".join(str(texte or "").split())
    return plat if len(plat) <= maximum else plat[: maximum - 1].rstrip() + "…"


def _quand(iso: object) -> str:
    instant = _epoch(iso)
    return datetime.fromtimestamp(instant).strftime("%d/%m %H:%M") if instant else "?"


def _epoch(iso: object) -> float:
    return cle_chrono(iso)


def _mots(texte: str) -> set[str]:
    """Mots porteurs, sans accents ni pluriel : « Étendre le scraping aux sites » ≈ « site »."""
    plat = "".join(c for c in unicodedata.normalize("NFD", texte.casefold())
                   if unicodedata.category(c) != "Mn")
    mots = set()
    for mot in re.findall(r"[a-z0-9]+", plat):
        if (len(mot) >= 4 or any(c.isdigit() for c in mot)) and mot not in _VIDES:
            mots.add(mot.rstrip("s")[:7])
    return mots


def _liste(items: list, maximum: int = ITEMS_MAX) -> str:
    textes = [_court(i, ITEM_MAX) for i in items[:maximum]]
    reste = len(items) - maximum
    return " ; ".join(textes) + (f" (+{reste})" if reste > 0 else "")


# ------------------------------------------------------------------------------ index


def _tickets_des_agents(tickets: dict[str, dict]) -> dict[str, str]:
    """`{agent_id: ticket_id}` : le ticket sur lequel chaque agent a tourné."""
    return {str(run.get("agent_id") or ""): ident for ident, ticket in tickets.items()
            for run in ticket.get("runs") or [] if isinstance(run, dict)}


def _taches_des_tickets(lignes: list[dict]) -> dict[str, str]:
    """`{ticket_id: micro_id}` : la tâche du Bureau qui a lancé chaque ticket."""
    return {lien["ticket_id"]: ligne["id"] for ligne in lignes
            for lien in ligne.get("tickets") or [] if lien.get("ticket_id")}


def _lire_suites_et_provenances() -> tuple[list, list]:
    with micros._tx() as conn:
        suites = conn.execute("SELECT ticket_id, micro_id, lien, at FROM micro_suites").fetchall()
        provenances = conn.execute("SELECT micro_id, session_id, at FROM micro_provenance"
                                   " WHERE session_id != ''").fetchall()
    return suites, provenances


class _Index:
    """Tout ce qui se lit UNE fois pour le chantier : tickets, suites, provenances."""

    def __init__(self, lignes: list[dict]):
        from . import _persistence
        self.lignes = {l["id"]: l for l in lignes}
        self.tickets = {str(t.get("id") or ""): t for _slug, t in _persistence.all_tickets()}
        self.tache_du_ticket = _taches_des_tickets(lignes)
        self.ticket_de_l_agent = _tickets_des_agents(self.tickets)
        suites, provenances = _lire_suites_et_provenances()
        self.suite_de = {micro_id: (ticket_id, lien, at) for ticket_id, micro_id, lien, at in suites
                         if lien in ("creee", "manuelle")}
        self.session_de = {micro_id: session for micro_id, session, _at in provenances}
        self._completer_par_session()
        self.clotures = self._clotures(suites, provenances)

    def _completer_par_session(self) -> None:
        """Clôtures antérieures à `micro_suites` : une autre ligne de la MÊME session, elle
        reliée à son ticket, dit de quel passage elles viennent."""
        ticket_de_session = {self.session_de[m]: s[0] for m, s in self.suite_de.items()
                             if m in self.session_de}
        for micro_id, session in self.session_de.items():
            if micro_id not in self.suite_de and session in ticket_de_session:
                self.suite_de[micro_id] = (ticket_de_session[session], "session", "")

    def _clotures(self, suites, provenances) -> dict[str, list[float]]:
        """`{ticket_id: [instants de clôture]}`, lus dans les suites que chaque clôture a
        ouvertes ou reliées (une clôture sans suite ne laisse aucune trace ici)."""
        instants: dict[str, set[float]] = {}
        for ticket_id, _micro, _lien, at in suites:
            instants.setdefault(ticket_id, set()).add(int(_epoch(at) // 60))
        for micro_id, _session, at in provenances:
            ticket_id = (self.suite_de.get(micro_id) or ("",))[0]
            if ticket_id:
                instants.setdefault(ticket_id, set()).add(int(_epoch(at) // 60))
        return {t: sorted(m * 60.0 for m in minutes if m) for t, minutes in instants.items()}

    def agent_du_ticket(self, ticket_id: str) -> str:
        for run in (self.tickets.get(ticket_id) or {}).get("runs") or []:
            if isinstance(run, dict) and run.get("kind", "work") == "work" and run.get("agent_id"):
                return str(run["agent_id"])
        return ""

    def tache_racine(self, ticket_id: str, profondeur: int = 4) -> str:
        """La tâche du Bureau d'où part ce ticket : la sienne, ou celle de son parent délégant."""
        for _ in range(profondeur):
            if ticket_id in self.tache_du_ticket:
                return self.tache_du_ticket[ticket_id]
            parent = str((self.tickets.get(ticket_id) or {}).get("parent") or "")
            ticket_id = self.ticket_de_l_agent.get(parent, "")
            if not ticket_id:
                return ""
        return ""


# ------------------------------------------------------------------------------ une tâche


def _titre(index: _Index, micro_id: str) -> str:
    ligne = index.lignes.get(micro_id)
    return f"{micro_id} « {_court(ligne['titre'], 70)} »" if ligne else micro_id


def _origine_cloture(index: _Index, ligne: dict) -> str:
    suite = index.suite_de.get(ligne["id"])
    if suite is None:
        return "par la clôture d'un agent (passage inconnu)"
    ticket_id, lien, _at = suite
    agent = index.agent_du_ticket(ticket_id)[:8] or "?"
    racine = index.tache_racine(ticket_id)
    if index.tache_du_ticket.get(ticket_id):
        ou = f"passage de la tâche {_titre(index, racine)}"
    elif racine:
        ou = f"sous-agent délégué par la tâche {_titre(index, racine)}"
    else:
        titre = (index.tickets.get(ticket_id) or {}).get("title") or ""
        ou = f"lancé hors tâche : « {_court(titre, 60)} »"
    verbe = "depuis le récap (« Créer la tâche »)" if lien == "manuelle" else "par la clôture"
    return f"{verbe} de l'agent {agent} (ticket {ticket_id}, {ou})"


def _provenance(index: _Index, ligne: dict) -> str:
    origine = ligne.get("origine") or ""
    qui = {"humain": "par l'utilisateur", "assistant": "par l'assistant",
           "point_ouvert": "depuis un point ouvert d'agent"}.get(origine)
    texte = qui or _origine_cloture(index, ligne)
    session = index.session_de.get(ligne["id"])
    return f"créée {_quand(ligne.get('created_at'))} {texte}" + (f" ; session {session}" if session else "")


def _branche(p: dict, meta: dict) -> str:
    """« branche agent/x intégrée 25/09 02:14 · commit livré 1255b5d » ("" sans branche)."""
    if not p.get("branche"):
        return ""
    integre = {True: "intégrée", False: "NON intégrée"}.get(p.get("integre"), "")
    quand = f" {_quand(meta['integrated_at'])}" if meta.get("integrated_at") else ""
    commit = f" · commit livré {str(meta['delivered_head'])[:7]}" if meta.get("delivered_head") else ""
    return f"branche {p['branche']} {integre}{quand}".rstrip() + commit


def _passage(index: _Index, p: dict) -> str:
    ticket = index.tickets.get(p["ticket_id"]) or {}
    meta = ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}
    morceaux = [f"#{p['numero']} ticket {p['ticket_id']}", f"agent {str(p.get('agent_id') or '?')[:8]}",
                p.get("libelle_etat") or p.get("etat") or "",
                f"fin constatée par le serveur {_quand(p['finished_at'])}" if p.get("finished_at") else "",
                _branche(p, meta)]
    return " · ".join(m for m in morceaux if m)


def _suites_du_passage(recap: dict) -> str:
    suites = recap.get("suites") or {}
    liens = [s for liste in ("reste", "a_decider") for s in suites.get(liste) or [] if s]
    return ", ".join(f"{s['id']} ({s.get('libelle_statut') or s.get('statut_ui')})" for s in liens)


def _recap(p: dict) -> list[str]:
    recap = p.get("recap") or {}
    lignes = [f"{nom} : {_liste(recap[cle])}" for cle, nom in
              (("fait", "fait"), ("reste", "reste à faire"), ("a_decider", "à décider"))
              if recap.get(cle)]
    suites = _suites_du_passage(recap)
    if suites:
        lignes.append(f"suites ouvertes par ce passage : {suites}")
    return [f"    livré #{p['numero']} — {l}" for l in lignes]


def _agents(index: _Index, ligne: dict) -> list[str]:
    passages = ligne.get("passages") or []
    if not passages:
        return ["  agents : aucun (jamais lancée)"]
    sortie = []
    for p in passages:
        sortie.append(f"  agent {_passage(index, p)}")
        sortie.extend(_recap(p))
    return sortie


def _precisions(ligne: dict) -> list[str]:
    sortie = [f"  précision ({p.get('auteur')}, {_quand(p.get('created_at'))}) : "
              f"{_court(p.get('texte'), 160)}"
              for p in ligne.get("precisions") or [] if p.get("auteur") != "bureau"]
    sortie += [f"  retour envoyé {_quand(r.get('created_at'))} : {_court(r.get('texte'), 160)}"
               for r in ligne.get("retours") or []]
    return sortie


def _statut(ligne: dict) -> str:
    statut = ligne.get("libelle_statut") or ligne.get("statut_ui") or ""
    categorie = ligne.get("categorie") or ""
    return f"{statut}{' · attention : ' + categorie if categorie else ''}"


def _tache(index: _Index, ligne: dict, signaux: list[str]) -> list[str]:
    sortie = [f"▸ {ligne['id']} « {_court(ligne['titre'], 120)} » — {_statut(ligne)}"
              + (" · DÉCISION" if ligne.get("decision") else ""),
              f"  {_provenance(index, ligne)}"]
    brief = str(ligne.get("corps") or "").strip()
    if brief and _court(brief, 400) != _court(ligne["titre"], 400):
        sortie.append(f"  brief : {_court(brief, BRIEF_MAX)}")
    sortie += _agents(index, ligne) + _precisions(ligne)
    sortie += [f"  ⚑ {s}" for s in signaux]
    return sortie


def _archivee(ligne: dict) -> str:
    raison = classement.texte(ligne.get("classement")) or \
        ((ligne.get("archive_auto") or {}).get("texte") or "")
    return (f"  {ligne['id']} « {_court(ligne['titre'], 90)} » — "
            f"{ligne.get('libelle_statut') or ligne.get('statut_ui')}"
            + (f" : {_court(raison, 180)}" if raison else ""))


# ------------------------------------------------------------------------------ signaux


def _reprise(index: _Index, racine: dict, depuis: float) -> str:
    """Ce que la tâche `racine` a reçu ou livré APRÈS `depuis` (epoch) : retour envoyé, nouveau
    passage, nouvelle clôture de l'un de ses passages. "" sinon.

    Pas la fin constatée d'un agent (`finished_at`) : c'est l'heure où le serveur a vu son process
    mort, souvent des heures après sa dernière réponse."""
    faits = [f"retour envoyé {_quand(r['created_at'])}" for r in racine.get("retours") or []
             if _epoch(r.get("created_at")) > depuis]
    faits += [f"passage #{p['numero']} lancé {_quand(p['started_at'])}"
              for p in racine.get("passages") or [] if _epoch(p.get("started_at")) > depuis]
    return ", ".join(faits + _clotures_apres(index, racine, depuis + 60))


def _clotures_apres(index: _Index, racine: dict, depuis: float) -> list[str]:
    clotures = sorted({c for lien in racine.get("tickets") or []
                       for c in index.clotures.get(lien.get("ticket_id") or "", []) if c > depuis})
    if not clotures:
        return []
    return ["clôturée de nouveau " + ", ".join(
        datetime.fromtimestamp(c).strftime("%d/%m %H:%M") for c in clotures[-4:])]


def _signal_racine(index: _Index, ligne: dict, racine_id: str, depuis: float, cite: bool) -> str:
    racine = index.lignes.get(racine_id)
    if racine is None or racine_id == ligne["id"]:
        return ""
    reprise = _reprise(index, racine, depuis)
    statut = racine.get("libelle_statut") or racine.get("statut_ui")
    if _RELECTURE.search(ligne["titre"]) and racine.get("statut_ui") == "a_relire":
        return (f"relecture demandée alors que la tâche {_titre(index, racine_id)} attend déjà ta "
                f"vérification ({statut}) : probable doublon de cette carte")
    if not reprise:
        return ""
    verbe = "cite" if cite else "est une suite de"
    return (f"{verbe} la tâche {_titre(index, racine_id)} ({statut}), reprise APRÈS la création de "
            f"celle-ci ({reprise}) : vérifier si c'est fait dans cette reprise")


def _signaux(index: _Index, ligne: dict) -> list[str]:
    depuis = _epoch(ligne.get("created_at"))
    suite = index.suite_de.get(ligne["id"])
    racines = []
    if suite is not None:
        racines.append((index.tache_racine(suite[0]), False))
    texte = f"{ligne['titre']}\n{ligne.get('corps') or ''}"
    racines += [(ident, True) for ident in _ID_TACHE.findall(texte) if ident in index.lignes]
    signaux, vus = [], set()
    for racine_id, cite in racines:
        if racine_id and racine_id not in vus:
            vus.add(racine_id)
            signal = _signal_racine(index, ligne, racine_id, depuis, cite)
            if signal:
                signaux.append(signal)
    return signaux


def _proches(lignes: list[dict]) -> list[str]:
    """Titres (et débuts de brief) très proches : au moins 2 mots porteurs communs et la moitié
    des mots du plus court."""
    mots = {l["id"]: _mots(l["titre"]) | _mots(_court(l.get("corps"), 160)) for l in lignes}
    sortie = []
    for i, a in enumerate(lignes):
        for b in lignes[i + 1:]:
            communs = mots[a["id"]] & mots[b["id"]]
            plus_court = min(len(mots[a["id"]]), len(mots[b["id"]])) or 1
            if len(communs) >= 2 and len(communs) / plus_court >= 0.5:
                sortie.append(f"≈ {a['id']} « {_court(a['titre'], 60)} » / {b['id']} "
                              f"« {_court(b['titre'], 60)} » (mots communs : "
                              f"{', '.join(sorted(communs)[:6])})")
    return sortie


def _vagues(index: _Index, lignes: list[dict]) -> list[str]:
    """Une même session qui a ouvert des suites à plusieurs clôtures : ses points reformulés
    d'une clôture à l'autre sont souvent les mêmes."""
    par_session: dict[str, list[dict]] = {}
    for ligne in lignes:
        session = index.session_de.get(ligne["id"])
        if session:
            par_session.setdefault(session, []).append(ligne)
    sortie = []
    for session, groupe in par_session.items():
        moments = sorted({_quand(l.get("created_at")) for l in groupe})
        if len(moments) >= 2 and len(groupe) >= 2:
            sortie.append(f"session {session} : suites ouvertes à {len(moments)} clôtures "
                          f"({', '.join(moments)}) — {', '.join(l['id'] for l in groupe)}")
    return sortie


# ------------------------------------------------------------------------------ entrée


def trouver_chantier(reference: str, chantiers: list[dict]) -> dict | None:
    """Par id, titre exact, puis titre contenant la référence (sans casse ni accents)."""
    ref = str(reference or "").strip()
    if not ref:
        return None
    mots = _mots(ref)
    for critere in (lambda c: c["macro_id"] == ref,
                    lambda c: c["titre"].casefold() == ref.casefold(),
                    lambda c: bool(mots) and mots == _mots(c["titre"]),
                    lambda c: bool(mots) and mots <= _mots(c["titre"])):
        trouves = [c for c in chantiers if critere(c)]
        if len(trouves) == 1:
            return trouves[0]
    return None


def _entete(chantier: dict, ouvertes: list, archivees: list) -> list[str]:
    return [f"CHANTIER {chantier['macro_id']} « {chantier['titre']} » — {len(ouvertes)} tâche(s) "
            f"ouverte(s), {len(archivees)} archivée(s). Dépôts : "
            f"{', '.join(chantier.get('projets') or []) or 'aucun'}.",
            "Dates en heure locale. ⚑ = signal à vérifier, pas une conclusion.", ""]


def _rapprochements(index: _Index, ouvertes: list, archivees: list) -> list[str]:
    faites = [l for l in archivees if l.get("statut_ui") == "faite"]
    lignes = _proches(ouvertes + faites) + _vagues(index, ouvertes)
    return ["", "RAPPROCHEMENTS :"] + [f"  {l}" for l in lignes] if lignes else []


def vue_ensemble(reference: str) -> dict:
    """La vision d'ensemble du chantier `reference` (id ou titre), en texte compact."""
    from . import bureau_lignes
    chantiers = bureau_lignes.collect_lignes().get("chantiers") or []
    chantier = trouver_chantier(reference, chantiers)
    if chantier is None:
        return {"ok": False, "erreur": "chantier_inconnu", "reference": reference,
                "chantiers": [{"id": c["macro_id"], "titre": c["titre"]} for c in chantiers]}
    lignes = chantier.get("lignes") or []
    ouvertes = [l for l in lignes if l.get("statut_ui") not in _CLASSES]
    archivees = sorted((l for l in lignes if l.get("statut_ui") in _CLASSES),
                       key=lambda l: str(l.get("updated_at") or ""), reverse=True)
    return {"ok": True, "chantier": {"id": chantier["macro_id"], "titre": chantier["titre"]},
            "ouvertes": len(ouvertes), "archivees": len(archivees),
            "texte": "\n".join(_rendu(chantier, _Index(lignes), ouvertes, archivees))}


def _rendu(chantier: dict, index: _Index, ouvertes: list, archivees: list) -> list[str]:
    texte = _entete(chantier, ouvertes, archivees)
    for ligne in ouvertes:
        texte += _tache(index, ligne, _signaux(index, ligne))
    texte += _rapprochements(index, ouvertes, archivees)
    if archivees:
        texte += ["", f"ARCHIVÉES (les {min(len(archivees), ARCHIVEES_MAX)} plus récentes) :"]
        texte += [_archivee(l) for l in archivees[:ARCHIVEES_MAX]]
    return texte
