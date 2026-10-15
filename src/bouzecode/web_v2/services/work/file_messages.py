# [desc] Livraison d'un message à un agent, et FILE d'attente des messages envoyés pendant qu'il travaille (SPEC §5.3). [/desc]
"""Deux choses, qui partagent la même règle de livraison :

* `envoyer(agent, texte)` — LE chemin de livraison d'un message à un agent qui ne joue pas de
  tour : réponse à une question (chaude ou froide), reprise chaude d'un agent oisif, ou
  respawn. C'est le corps historique de l'ancienne route `continue` (devenue `POST /api/agents/<id>/messages`), extrait pour que la
  file ci-dessous livre EXACTEMENT comme la route.
* la **file** : un message écrit pendant qu'un agent joue son tour n'interrompt plus rien. Il
  est rangé dans `<AGENTS_DIR>/queues/<agent_id>.json` et livré dès que le tour se termine —
  par le tick du watchdog (8 s) et, plus vite, par la lecture de `/blocks` que le front fait
  toutes les 1,5 s pendant qu'un agent tourne. Avant, l'UI interrompait l'agent d'office
  (audit conversations E3) : c'était perdre son tour pour une précision.

Plusieurs messages en file partent ENSEMBLE (un seul tour), séparés par une ligne vide.

Un message ne quitte la file qu'une fois LU. Livré à un process resté chaud, il est déposé dans
sa boîte (`runner._push_followup`, un seul dépôt pour le lot, nommé `depot` sur chacun de ses
messages) et reste en file au statut `en_livraison` jusqu'à ce que le process l'ait relevé. Si
le process s'arrête avant (éviction, arrêt, crash), le lot est repris de la boîte et passe
`non_livre` : l'UI le montre avec « Renvoyer » au lieu de le perdre en silence. Il n'est pas
renvoyé d'office : l'arrêt a pu être voulu. Un process de l'ANCIEN code, qui ne lit que
`followup.txt`, le reçoit là (`en_livraison` sans `depot` jusqu'à ce que le fichier soit vidé).

**Pendant le tour** (comme dans Claude Code) : un message écrit pendant que le process joue son
tour est aussitôt DÉPOSÉ dans sa boîte (`ipc.deposer_message`, drapeau `boite`). L'agent le
relève à sa prochaine frontière de tour — après le lot d'outils en cours — sans attendre la fin
de son travail. Cela vaut dès le lancement du process, avant même son premier `running` ; un
message écrit avant que le process soit connu est déposé par `livrer_si_pret` dès qu'il l'est.
S'il finit avant, sa boucle chaude le relève comme tour suivant. Un process qui
ne le lira plus (mort, ou en pause sur une question) le rend : le message repasse en file et part
par le chemin ordinaire ci-dessus, sauf si l'agent a été ARRÊTÉ à la main (`non_livre`).

`transmettre` est le geste complet : file + livraison immédiate si l'agent ne joue pas de tour,
et, en mode `interrompre`, coupure du tour en cours (`interruption.interrompre`). Un message
RELAYÉ (par l'assistant du Bureau, par un manager) porte un en-tête horodaté qui dit d'où il
vient et qu'il change la consigne. Une précision de tâche transmise (`precision_id`) signale sa
lecture au Bureau (`micros.marquer_transmission`).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from bouzecode.web_v2.services.horodatage import maintenant_iso

_verrou = threading.Lock()

ETATS_OCCUPES = ("running", "starting")
EN_LIVRAISON = "en_livraison"
NON_LIVRE = "non_livre"

#  D'où vient un message relayé : l'agent doit le voir comme une consigne de l'utilisateur (ou
#  de son parent), datée, et savoir qu'elle prime sur son brief.
ENTETES = {
    "assistant": "[Précision de l'utilisateur, relayée par l'assistant du Bureau — {heure}]",
    "bureau": "[Précision de l'utilisateur, ajoutée depuis le Bureau — {heure}]",
    "parent": "[Message de ton agent parent — {heure}]",
}
CONSIGNE_RELAYEE = ("C'est un CHANGEMENT DE CONSIGNE : il prime sur ton brief initial. Reporte-le "
                    "dans ta note Methodology, puis adapte ton travail en cours.")


#  Les files vivent dans un SOUS-DOSSIER : à la racine d'AGENTS_DIR, `<id>.queue.json` tombait
#  dans le glob `*.json` de `runner.list_agents`, qui prenait cette LISTE pour une fiche d'agent
#  (500 sur /api/lignes tant qu'un message attendait). Ancien emplacement migré à la lecture.
DOSSIER = "queues"
_ANCIEN_SUFFIXE = ".queue.json"


def _dossier() -> Path:
    from bouzecode.web_v2.runtime.runner import agent_fiche
    return Path(agent_fiche.AGENTS_DIR) / DOSSIER


_migre_pour: set[str] = set()


def _migrer_anciennes_files() -> None:
    """Une fois par dossier d'agents et par process : l'ancien emplacement ne se remplit plus."""
    from bouzecode.web_v2.runtime.runner import agent_fiche
    racine = str(agent_fiche.AGENTS_DIR)
    if racine in _migre_pour:
        return
    _migre_pour.add(racine)
    for ancien in Path(agent_fiche.AGENTS_DIR).glob(f"*{_ANCIEN_SUFFIXE}"):
        agent_id = ancien.name[:-len(_ANCIEN_SUFFIXE)]
        cible = _dossier() / f"{agent_id}.json"
        try:
            cible.parent.mkdir(parents=True, exist_ok=True)
            if cible.exists():
                ancien.unlink()
            else:
                ancien.replace(cible)
        except OSError:
            continue


def _chemin(agent_id: str) -> Path:
    return _dossier() / f"{agent_id}.json"


def _lire(agent_id: str) -> list[dict]:
    _migrer_anciennes_files()
    chemin = _chemin(agent_id)
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _ecrire(agent_id: str, items: list[dict]) -> None:
    chemin = _chemin(agent_id)
    if not items:
        chemin.unlink(missing_ok=True)
        return
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(".json.tmp")
    temporaire.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    temporaire.replace(chemin)


def _followup(agent) -> Path | None:
    ipc_dir = getattr(agent, "ipc_dir", "") or ""
    return Path(ipc_dir) / "followup.txt" if ipc_dir else None


def _boite(agent):
    from bouzecode.web_v2.runtime import ipc
    ipc_dir = getattr(agent, "ipc_dir", "") or ""
    return ipc.from_dir(ipc_dir) if ipc_dir else None


def message_non_lu(agent) -> bool:
    """Le process de l'agent a-t-il un message poussé qu'il n'a pas encore lu ?"""
    from bouzecode.web_v2.runtime import ipc
    chemin = _followup(agent)
    paths = _boite(agent)
    return bool(chemin and chemin.is_file()) or bool(paths and ipc.a_du_courrier(paths))


def texte_pour_l_agent(item: dict) -> str:
    """Ce que l'agent lira : l'en-tête d'un message relayé, puis le texte."""
    entete = str(item.get("entete") or "")
    return f"{entete}\n{item.get('text') or ''}" if entete else str(item.get("text") or "")


def _entete(origine: str) -> str:
    modele = ENTETES.get(origine or "")
    if not modele:
        return ""
    return modele.format(heure=datetime.now().strftime("%H:%M")) + "\n" + CONSIGNE_RELAYEE


def _signaler(items: list[dict], statut: str) -> None:
    """Une précision de tâche transmise dit au Bureau si l'agent l'a lue."""
    for item in items:
        if item.get("precision_id"):
            from . import micros
            micros.marquer_transmission(str(item.get("id") or ""), statut)


def _process_vivant(agent) -> bool:
    from ...runtime.runner import agent_vivacite
    return bool(getattr(agent, "pid", None)) and not agent_vivacite.processus_absent(agent)


#  Dans la boîte : déposé pendant le tour (`boite`, que le front montre en attente et annulable)
#  ou livré à un process chaud (`depot` seul : en route, le front ne le montre pas).
def _en_followup(item: dict) -> bool:
    return item.get("statut") == EN_LIVRAISON and not (item.get("boite") or item.get("depot"))


def _en_boite(item: dict) -> bool:
    return item.get("statut") == EN_LIVRAISON and bool(item.get("boite") or item.get("depot"))


def _sauf(items: list[dict], critere) -> list[dict]:
    return [item for item in items if not critere(item)]


def _non_livres(items: list[dict]) -> list[dict]:
    return [{**item, "statut": NON_LIVRE} if _en_followup(item) else item for item in items]


def _suivre_followup(agent, items: list[dict]) -> list[dict]:
    """Messages poussés dans followup.txt : lus (fichier vidé) ou `non_livre` (process arrêté)."""
    en_cours = [item for item in items if _en_followup(item)]
    if not en_cours:
        return items
    chemin = _followup(agent) if agent is not None else None
    if not (chemin and chemin.is_file()):
        _signaler(en_cours, "lue")
        return _sauf(items, _en_followup)
    if _process_vivant(agent):
        return items
    chemin.unlink(missing_ok=True)
    _signaler(en_cours, "non_lue")
    return _non_livres(items)


def _lira_encore(agent, paths) -> bool:
    """Le process relèvera-t-il sa boîte ? Vivant, et ni en pause sur une question ni arrêté."""
    from bouzecode.web_v2.runtime import ipc
    statut = str(ipc.read_state(paths).get("status") or "")
    return _process_vivant(agent) and statut not in (
        "awaiting_input", "awaiting_plan_validation",
        ipc.STATUS_KILLED_BY_SERVER, ipc.STATUS_INTERRUPTED_BY_SERVER)


def _depot(item: dict) -> str:
    """Nom du fichier déposé qui porte ce message : le sien, ou celui du lot livré ensemble."""
    return str(item.get("depot") or item.get("id") or "")


def _remis_en_file(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("statut", "boite", "depot")}


#  Ce qu'il advient d'un dépôt : lu, en attente, repris (remis en file) ou non livré.
LU, ATTENTE, REPRIS = "lu", "attente", "repris"


def _sort_du_depot(agent, paths, depot: str, chaud: bool) -> str:
    """Un dépôt que personne ne relèvera est repris de la boîte. Déposé pendant le tour, il
    repart en file ; livré à un process chaud qui s'est arrêté depuis, ou à un agent ARRÊTÉ à
    la main, il ne relance rien tout seul : `non_livre`."""
    from bouzecode.web_v2.runtime import ipc
    if not ipc.message_en_boite(paths, depot):
        return LU
    if _lira_encore(agent, paths):
        return ATTENTE
    if not ipc.reprendre_message(paths, depot):
        return LU                                   # relevé entre-temps
    if chaud or ipc.read_state(paths).get("status") == ipc.STATUS_KILLED_BY_SERVER:
        return NON_LIVRE
    return REPRIS


def _suivre_boite(agent, items: list[dict]) -> list[dict]:
    """Messages déposés dans la boîte : lus (quittent la file), en attente, ou repris."""
    if not any(_en_boite(item) for item in items):
        return items
    paths = _boite(agent) if agent is not None else None
    if paths is None:
        return _sauf(items, _en_boite)
    sorts: dict[str, str] = {}
    suivis: list[dict] = []
    for item in items:
        if not _en_boite(item):
            suivis.append(item)
            continue
        depot = _depot(item)
        if depot not in sorts:
            sorts[depot] = _sort_du_depot(agent, paths, depot, not item.get("boite"))
        sort = sorts[depot]
        if sort == LU:
            _signaler([item], "lue")
        elif sort == NON_LIVRE:
            _signaler([item], "non_lue")
            suivis.append({**_remis_en_file(item), "statut": NON_LIVRE})
        elif sort == REPRIS:
            suivis.append(_remis_en_file(item))
        else:
            suivis.append(item)
    return suivis


def _suivre_livraisons(agent_id: str, items: list[dict]) -> list[dict]:
    """Retire les messages lus, marque `non_livre` ceux qu'un process arrêté ne lira jamais."""
    if not any(item.get("statut") == EN_LIVRAISON for item in items):
        return items
    from bouzecode.web_v2.runtime.runner import agent_fiche
    agent = agent_fiche.load_agent(agent_id)
    return _suivre_followup(agent, _suivre_boite(agent, items))


def lister(agent_id: str) -> list[dict]:
    with _verrou:
        items = _lire(agent_id)
        suivis = _suivre_livraisons(agent_id, items)
        if suivis != items:
            _ecrire(agent_id, suivis)
    return suivis


def nouvel_id() -> str:
    return uuid.uuid4().hex[:10]


#  Statuts IPC d'un process qui JOUE son tour. `unknown` = pas encore d'état : le process vient
#  d'être lancé et n'a pas écrit son premier `running` (quelques dizaines de ms, pendant
#  lesquelles l'UI le montre déjà au travail). Il va jouer ce tour et relever sa boîte à chaque
#  frontière ; s'il s'arrête avant, `_suivre_un_depot` reprend le message.
STATUTS_EN_TOUR = ("running", "unknown")


def _deposer_si_en_tour(agent_id: str, item: dict) -> bool:
    """L'agent joue son tour, process vivant : le message part DANS sa boîte, tout de suite."""
    from bouzecode.web_v2.runtime import ipc
    from bouzecode.web_v2.runtime.runner import agent_fiche
    agent = agent_fiche.load_agent(agent_id)
    paths = _boite(agent) if agent is not None else None
    if paths is None or not _process_vivant(agent):
        return False
    if ipc.read_state(paths).get("status") not in STATUTS_EN_TOUR:
        return False
    ipc.deposer_message(paths, item["id"], texte_pour_l_agent(item))
    return True


def _deposer_les_attentes(agent_id: str, items: list[dict]) -> list[dict]:
    """Messages restés en file ordinaire (écrits avant que le process soit connu) alors que
    l'agent joue maintenant son tour : déposés dans sa boîte, lus à sa prochaine étape au
    lieu d'attendre la fin de tout son travail."""
    return [{**item, "statut": EN_LIVRAISON, "boite": True}
            if not item.get("statut") and _deposer_si_en_tour(agent_id, item) else item
            for item in items]


def mettre_en_file(agent_id: str, texte: str, origine: str = "", precision_id: str = "",
                   message_id: str = "") -> dict:
    """Range le message ; si l'agent est en plein tour, il est aussi déposé dans sa boîte et
    sera lu à sa prochaine frontière de tour (`statut: en_livraison`, `boite: true`)."""
    item = {"id": message_id or nouvel_id(), "text": texte,
            "created_at": maintenant_iso()}
    item.update({k: v for k, v in (("entete", _entete(origine)),
                                   ("precision_id", precision_id)) if v})
    with _verrou:
        items = _lire(agent_id)
        if _deposer_si_en_tour(agent_id, item):
            item.update(statut=EN_LIVRAISON, boite=True)
        items.append(item)
        _ecrire(agent_id, items)
    return {**item, "position": len(items)}


def _retirable(agent_id: str, item: dict) -> bool:
    """Un message déposé dans la boîte ne s'annule que s'il n'a pas encore été relevé."""
    if not _en_boite(item):
        return True
    from bouzecode.web_v2.runtime import ipc
    from bouzecode.web_v2.runtime.runner import agent_fiche
    agent = agent_fiche.load_agent(agent_id)
    paths = _boite(agent) if agent is not None else None
    return bool(paths and ipc.reprendre_message(paths, _depot(item)))


def annuler(agent_id: str, item_id: str) -> bool:
    """Retire un message pas encore lu. Livré en lot avec d'autres, tout le lot est repris de
    la boîte : les autres messages du lot repartent en file et seront livrés sans lui."""
    with _verrou:
        items = _lire(agent_id)
        cible = next((item for item in items if item.get("id") == item_id), None)
        if cible is None or not _retirable(agent_id, cible):
            return False
        repris = _depot(cible) if _en_boite(cible) else None
        _ecrire(agent_id, [_remis_en_file(item) if repris and _en_boite(item)
                           and _depot(item) == repris else item
                           for item in items if item is not cible])
    return True


def envoyer(agent, texte: str, depot: str = "") -> dict:
    """Livre `texte` à un agent qui NE joue PAS de tour. `{ok}` ou `{ok:False, reason, code, error}`.

    `depot` nomme le message déposé dans la boîte d'un process resté chaud, pour que la file
    suive sa lecture."""
    from bouzecode.web_v2.runtime import pending
    from bouzecode.web_v2.runtime.runner import agent_reprise

    from ..sessions import store
    from . import awaiting, delivery, dispatch

    statut = store.agent_status(agent)
    if statut.get("state") == "running":
        return {"ok": False, "reason": "running", "code": 409,
                "error": "l'agent tourne encore — attends la fin du tour"}
    if statut.get("state") != "idle":
        dispatch.rehome_agent_cwd(agent)
    delivery.reopen_for_new_work(getattr(agent, "ticket_slug", "") or "",
                                 getattr(agent, "ticket_id", "") or "")
    if statut.get("state") in awaiting.AWAITING_STATES or pending.exists(agent.session_path):
        livre = agent_reprise.resume_pending_agent(agent, texte)
    else:
        livre = agent_reprise.continue_agent(agent, texte, **({"message_id": depot} if depot else {}))
    if livre is None:
        return {"ok": False, "reason": "not_delivered", "code": 409,
                "error": "un process tourne déjà pour cette session : le message n'a PAS été "
                         "transmis. Arrête l'agent puis réessaie."}
    store.invalidate_status(agent.agent_id)
    return {"ok": True}


def livrer_si_pret(agent_id: str) -> dict | None:
    """Livre la file de l'agent si son tour est fini. None = rien à faire / pas encore."""
    from bouzecode.web_v2.runtime.runner import agent_fiche

    from ..sessions import store
    with _verrou:
        items = _suivre_livraisons(agent_id, _lire(agent_id))
        _ecrire(agent_id, items)
        a_livrer = [item for item in items if not item.get("statut")]
        if not a_livrer:
            return None
        agent = agent_fiche.load_agent(agent_id)
        if agent is None:
            _ecrire(agent_id, [])
            return {"ok": False, "reason": "agent_missing"}
        store.invalidate_status(agent_id)
        if str((store.agent_status(agent) or {}).get("state") or "") in ETATS_OCCUPES:
            _ecrire(agent_id, _deposer_les_attentes(agent_id, items))
            return None
        texte = "\n\n".join(texte_pour_l_agent(item) for item in a_livrer).strip()
        depot = nouvel_id()
        resultat = envoyer(agent, texte, depot)
        if resultat.get("ok"):
            _ecrire(agent_id, _apres_envoi(agent, items, depot))
        return resultat


def _apres_envoi(agent, items: list[dict], depot: str = "") -> list[dict]:
    """Déposés chez un process chaud : en file jusqu'à lecture (`depot`). Poussés dans le
    followup.txt d'un process de l'ancien code : idem, sans `depot`. Relancés à froid, ou
    déjà relevés : lus."""
    from bouzecode.web_v2.runtime import ipc
    paths = _boite(agent)
    if depot and paths is not None and ipc.message_en_boite(paths, depot):
        marque = {"statut": EN_LIVRAISON, "depot": depot}
    elif (chemin := _followup(agent)) and chemin.is_file():
        marque = {"statut": EN_LIVRAISON}
    else:
        _signaler([item for item in items if not item.get("statut")], "lue")
        return [item for item in items if item.get("statut")]
    return [item if item.get("statut") else {**item, **marque} for item in items]


def transmettre(agent_id: str, texte: str, interrompre: bool = False, origine: str = "",
                precision_id: str = "", message_id: str = "") -> dict:
    """Le geste complet « donner un élément à un agent » (utilisateur, assistant, manager).

    * **ajout** (défaut) : en plein tour, déposé dans sa boîte → lu à la prochaine frontière
      de tour ; sinon livré tout de suite (réveil à chaud, réponse à une question, respawn).
    * **interrompre** : en plus, le tour en cours est coupé ; l'agent repart aussitôt avec
      le message (sa boucle chaude le relève), sans rien perdre de ce qu'il a déjà obtenu.

    Rend `{ok, queue_id, en_tour, interruption?}` ou l'échec de livraison (`reason`, `error`)."""
    from bouzecode.web_v2.runtime.runner import agent_fiche

    from . import interruption
    item = mettre_en_file(agent_id, texte, origine, precision_id, message_id)
    rendu = {"ok": True, "queue_id": item["id"], "en_tour": bool(item.get("boite"))}
    if item.get("boite"):
        agent = agent_fiche.load_agent(agent_id)
        if interrompre and agent is not None:
            rendu["interruption"] = interruption.interrompre(agent)
        return rendu
    livraison = livrer_si_pret(agent_id)
    if livraison is not None and not livraison.get("ok"):
        return {**livraison, "queue_id": item["id"]}
    return rendu


def livrer_prets() -> int:
    """Pour le watchdog : livre toutes les files dont l'agent a fini son tour."""
    livres = 0
    _migrer_anciennes_files()
    for chemin in _dossier().glob("*.json"):
        agent_id = chemin.stem
        try:
            resultat = livrer_si_pret(agent_id)
        except Exception:  # noqa: BLE001 — une file cassée ne bloque pas les autres
            continue
        if resultat and resultat.get("ok"):
            livres += 1
    return livres


def livrer_en_fond(agent_id: str) -> None:
    """Déclenché par une lecture (`/blocks`) : la livraison ne ralentit jamais la réponse."""
    if not _chemin(agent_id).exists():
        return
    threading.Thread(target=livrer_si_pret, args=(agent_id,), daemon=True,
                     name=f"file-{agent_id[:8]}").start()
