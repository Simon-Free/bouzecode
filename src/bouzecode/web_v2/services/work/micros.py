# [desc] Store SQLite des macro/micro-tâches : 5 tables additives, cycle de vie fermé, précisions append-only. [/desc]
"""Cinq tables ADDITIVES dans la base SQLite des tickets — le modèle cible de `docs/bureau-todo-modele-et-api.md` §8.

Ce module existe parce que, jusqu'ici, une micro-tâche n'existait NULLE PART : la page TO-DO la
recalculait à la volée depuis les clôtures d'agents, et la « macro » n'était qu'une chaîne libre
recopiée (donc mal orthographiée) par chaque agent. Trois conséquences dictent la forme du module :

- **Un état, pas un objet à part.** Le brouillon est une valeur d'`etat`, pas une table de
  brouillons : c'est ce qui permet de revenir dessus autant qu'on veut sans déplacer la ligne.
- **Le cycle de vie est un dict FERMÉ** (`TRANSITIONS`). L'invariant de tout le modèle est
  « rien ne part sans brief » : un dict permissif le viderait de son sens, donc toute transition
  non listée est refusée par une `EtatRefuse`, jamais silencieusement acceptée.
- **Les précisions sont append-only.** On n'écrase jamais un texte : un retour de clôture d'agent
  ou un point ouvert arrive en `en_attente_de_validation`, et l'humain le garde, le corrige ou le
  jette. Une précision non validée n'entre PAS dans le prompt — c'est là que se joue l'arbitrage.

Deux règles maison reprises de `tasks.py`/`bureau_meta.py` : **aucun `ALTER TABLE`** (on ne rejoue
que des `CREATE TABLE IF NOT EXISTS`, une donnée neuve va dans une table neuve), et le chemin de la
base est **ré-dérivé** à chaque transaction, jamais mémorisé — c'est ce qui rend l'isolation des
tests gratuite.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager

from bouzecode.web_v2.services.horodatage import heure_locale, maintenant_iso

from . import _persistence
from ._store_connection import transaction

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS macros (
      id         TEXT PRIMARY KEY,
      titre      TEXT NOT NULL,
      corps      TEXT NOT NULL DEFAULT '',
      etat       TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )""",
    #  Ordre d'affichage des chantiers, dans une table À PART : le module s'interdit les
    #  ALTER TABLE (cf. docstring), donc une colonne neuve sur `macros` ne migrerait jamais
    #  les bases déjà créées, alors qu'une table neuve se crée d'elle-même partout.
    """CREATE TABLE IF NOT EXISTS macro_positions (
      macro_id TEXT PRIMARY KEY,
      position INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS macro_projets (
      macro_id TEXT NOT NULL, slug TEXT NOT NULL,
      PRIMARY KEY (macro_id, slug)
    )""",
    """CREATE TABLE IF NOT EXISTS micros (
      id          TEXT PRIMARY KEY,
      macro_id    TEXT NOT NULL DEFAULT '',
      titre       TEXT NOT NULL,
      corps       TEXT NOT NULL DEFAULT '',
      projet_slug TEXT NOT NULL DEFAULT '',
      etat        TEXT NOT NULL DEFAULT 'brouillon',
      origine     TEXT NOT NULL DEFAULT 'humain',
      decision    INTEGER NOT NULL DEFAULT 0,
      pourquoi    TEXT NOT NULL DEFAULT '',
      created_at  TEXT NOT NULL,
      updated_at  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS micro_precisions (
      id         TEXT PRIMARY KEY,
      micro_id   TEXT NOT NULL,
      auteur     TEXT NOT NULL DEFAULT 'humain',
      texte      TEXT NOT NULL,
      statut     TEXT NOT NULL DEFAULT 'validee',
      created_at TEXT NOT NULL,
      rang       INTEGER NOT NULL DEFAULT 0
    )""",
    #  Provenance TECHNIQUE d'une ligne : quelle session l'a fabriquée, par quel point
    #  d'entrée. Table À PART pour la même raison que `macro_positions` (cf. docstring : pas
    #  d'ALTER TABLE), et surtout parce qu'elle est FACULTATIVE — les lignes déjà en base
    #  n'ont pas de provenance connue, et inventer une valeur par défaut mentirait. Absence
    #  de ligne ici = « on ne sait pas », jamais « créée à la main ».
    #  `source` est le point d'entrée technique (`final_answer`…), distinct de
    #  `micros.origine` qui reste la lecture MÉTIER (humain / cloture_agent / assistant).
    """CREATE TABLE IF NOT EXISTS micro_provenance (
      micro_id   TEXT PRIMARY KEY,
      session_id TEXT NOT NULL DEFAULT '',
      source     TEXT NOT NULL DEFAULT '',
      at         TEXT NOT NULL DEFAULT ''
    )""",
    #  Une tâche ROUVERTE (retour explicite en brouillon depuis un autre état) : ses vieux
    #  passages ne la font pas passer « À vérifier » / « En échec », c'est un geste voulu.
    #  Sans cette trace, une tâche restée brouillon AVEC des tickets (tâche v1 migrée avec
    #  ses tickets) ne se distinguait pas d'une tâche rouverte. Table à part (pas d'ALTER).
    """CREATE TABLE IF NOT EXISTS micro_reouvertures (
      micro_id TEXT PRIMARY KEY,
      at       TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS micro_tickets (
      micro_id TEXT NOT NULL, slug TEXT NOT NULL, ticket_id TEXT NOT NULL,
      at       TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (micro_id, slug, ticket_id)
    )""",
    #  Les RETOURS humains donnés en relançant une tâche (SPEC §4.7). Table à part (pas
    #  d'ALTER TABLE) : un retour n'est pas une précision du brief, il juge un PASSAGE. Il porte
    #  le ticket qu'il a lancé (`ticket_id`, vide tant que le lancement n'a pas abouti ou quand
    #  le retour a été envoyé à l'agent déjà en place, auquel cas c'est SON ticket).
    """CREATE TABLE IF NOT EXISTS micro_retours (
      id         TEXT PRIMARY KEY,
      micro_id   TEXT NOT NULL,
      texte      TEXT NOT NULL,
      ticket_id  TEXT NOT NULL DEFAULT '',
      mode       TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    )""",
    #  Un titre SAISI (et non dérivé de la 1re ligne du brief) ne doit plus être réécrit quand
    #  le brief change (audit Bureau F-11). Présence d'une ligne = titre explicite.
    """CREATE TABLE IF NOT EXISTS micro_titres_explicites (
      micro_id TEXT PRIMARY KEY
    )""",
    #  Une précision TRANSMISSE à un agent en cours (assistant du Bureau, consigne) : à qui,
    #  comment (ajout / interruption) et si l'agent l'a LUE. Une ligne par agent destinataire
    #  (`queue_id` = le message de sa file). Table à part : la précision reste la trace du
    #  brief, la transmission celle d'une livraison.
    """CREATE TABLE IF NOT EXISTS micro_transmissions (
      queue_id     TEXT PRIMARY KEY,
      precision_id TEXT NOT NULL,
      agent_id     TEXT NOT NULL,
      mode         TEXT NOT NULL DEFAULT 'ajout',
      statut       TEXT NOT NULL DEFAULT 'en_attente',
      created_at   TEXT NOT NULL,
      lu_at        TEXT NOT NULL DEFAULT ''
    )""",
    #  Ce qu'est devenu chaque point « reste à faire » / « à décider » déclaré à la clôture d'un
    #  passage (ticket) : la tâche qui le porte. Écrit par le pont de clôture ou par « Créer la
    #  tâche », jamais deviné. `cle` = le libellé déclaré, normalisé (`suites_cloture.cle`) ;
    #  `lien` = creee | existante (point déjà ouvert ailleurs) | manuelle.
    """CREATE TABLE IF NOT EXISTS micro_suites (
      ticket_id TEXT NOT NULL,
      cle       TEXT NOT NULL,
      micro_id  TEXT NOT NULL,
      lien      TEXT NOT NULL DEFAULT 'creee',
      at        TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (ticket_id, cle)
    )""",
    #  La branche (et son ticket) qu'un brouillon « Fusionner / Intégrer la branche … » vise,
    #  posée À LA CRÉATION (cf. `brouillons_integres`). Présence d'une ligne = cible connue.
    """CREATE TABLE IF NOT EXISTS micro_cibles (
      micro_id  TEXT PRIMARY KEY,
      ticket_id TEXT NOT NULL DEFAULT '',
      branche   TEXT NOT NULL DEFAULT ''
    )""",
    #  Trace d'un archivage AUTOMATIQUE (branche visée intégrée). Une tâche rouverte garde sa
    #  ligne : elle n'est jamais archivée une seconde fois dans le dos de l'utilisateur.
    """CREATE TABLE IF NOT EXISTS micro_archivages_auto (
      micro_id  TEXT PRIMARY KEY,
      ticket_id TEXT NOT NULL DEFAULT '',
      branche   TEXT NOT NULL DEFAULT '',
      texte     TEXT NOT NULL DEFAULT '',
      at        TEXT NOT NULL
    )""",
    #  Pourquoi une tâche a été classée sans être lancée : faite ailleurs, doublon, caduque
    #  (`classement.py`). Append-only : « Rouvrir » date la ligne (`rouvert_at`), ne l'efface pas.
    """CREATE TABLE IF NOT EXISTS micro_classements (
      id          TEXT PRIMARY KEY,
      micro_id    TEXT NOT NULL,
      motif       TEXT NOT NULL,
      commentaire TEXT NOT NULL DEFAULT '',
      lien_id     TEXT NOT NULL DEFAULT '',
      auteur      TEXT NOT NULL DEFAULT 'humain',
      at          TEXT NOT NULL,
      rouvert_at  TEXT NOT NULL DEFAULT '',
      rouvert_par TEXT NOT NULL DEFAULT ''
    )""",
    #  Trace d'un rattachement AUTOMATIQUE d'une tâche orpheline au chantier de son ancêtre
    #  (`orphelins.balayer`). Présence d'une ligne = déjà fait une fois : une tâche que
    #  l'utilisateur remet « Sans chantier » n'est jamais reprise dans son dos.
    """CREATE TABLE IF NOT EXISTS micro_rattachements_auto (
      micro_id  TEXT PRIMARY KEY,
      macro_id  TEXT NOT NULL DEFAULT '',
      ticket_id TEXT NOT NULL DEFAULT '',
      at        TEXT NOT NULL
    )""",
)

#  Le diagramme §8.5, écrit une fois. `lancee -> brouillon` est volontaire : un échec ne PERD pas le
#  brief, il l'enrichit — c'est la boucle d'auto-dégradation actuelle, inversée.
TRANSITIONS = {
    #  `brouillon -> lancee` est VOLONTAIRE : marquer `prete` est une commodité, pas une
    #  porte. Une ligne qu'on vient d'écrire et qui a son dépôt part directement — le brief
    #  est vérifié au lancement (titre + dépôt), pas par un clic rituel de plus.
    #  `faite` depuis brouillon/prete : ARCHIVER N'EST PAS LANCER. Une ligne qu'on ne lancera
    #  jamais (doublon, déjà traité ailleurs, idée abandonnée mais aboutie) n'avait aucune sortie
    #  vers l'archive alors que `abandonnee` était, lui, déjà ouvert — asymétrie non voulue, qui
    #  se payait en 409 sur le clic « Faite » du Bureau (09/09, « erreurs quand j'essaie de
    #  marquer des tickets comme faits »). L'invariant « rien ne part sans brief » protège le
    #  LANCEMENT (titre + dépôt vérifiés par api_micro_lancer), pas la clôture.
    "brouillon": ("prete", "lancee", "faite", "abandonnee"),
    "prete": ("brouillon", "lancee", "faite", "abandonnee"),
    #  `lancee -> abandonnee` : « Abandonner » une tâche lancée arrête d'abord son agent (route)
    #  puis la classe. `faite|abandonnee -> brouillon` : « Rouvrir » (SPEC §4.6) — l'historique
    #  des passages est conservé, rien n'est effacé.
    "lancee": ("faite", "brouillon", "abandonnee"),
    "faite": ("brouillon",),
    "abandonnee": ("brouillon",),
}

ETATS_MICRO = tuple(TRANSITIONS)
ETATS_MACRO = ("active", "en_pause", "terminee", "abandonnee")
ORIGINES = ("humain", "cloture_agent", "assistant", "point_ouvert")
EN_ATTENTE = "en_attente_de_validation"


class EtatRefuse(Exception):
    """Une transition que le cycle de vie n'autorise pas. Portée telle quelle en 409 par la route."""


class BriefInsuffisant(Exception):
    """Le passage à `prete` exige un titre et un rattachement. Portée en 400 par la route."""


def _now() -> str:
    return maintenant_iso()


#  Compteur d'écritures du PROCESS : la vue du Bureau (`taches_vue`) se mémorise quelques
#  secondes et se jette dès qu'une écriture passe par ce module. Un simple entier suffit —
#  le serveur est mono-process, et une écriture faite par un AUTRE process (outil d'assistant)
#  est rattrapée par le TTL de la vue.
_generation = 0


def _touch() -> None:
    global _generation
    _generation += 1


def generation() -> int:
    return _generation


def _id() -> str:
    return uuid.uuid4().hex[:8]


@contextmanager
def _tx():
    """Transaction sur la base des tickets, schéma des micros garanti présent.

    Les `CREATE TABLE IF NOT EXISTS` sont rejoués à chaque bloc : sans écriture quand les tables
    existent, et sans drapeau « déjà migré » de process — le genre de souvenir qui ment dès que la
    base change sous les pieds (les tests, justement, la changent)."""
    path = _persistence._db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with transaction(path) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        avant = conn.total_changes
        yield conn
        #  Toute écriture (INSERT/UPDATE/DELETE) invalide la vue mémorisée du Bureau. La
        #  connexion est réutilisée par thread : on compare donc AVANT/APRÈS ce bloc.
        if conn.total_changes != avant:
            _touch()


def _rows(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# --------------------------------------------------------------------------- macros


def create_macro(titre: str, corps: str = "", projets: list[str] | None = None) -> dict:
    """Une macro-tâche : un CHANTIER qui traverse plusieurs dépôts, pas un projet."""
    titre = (titre or "").strip()
    if not titre:
        raise BriefInsuffisant("le titre d'une macro-tâche est obligatoire")
    macro_id, maintenant = _id(), _now()
    with _tx() as conn:
        conn.execute(
            "INSERT INTO macros (id, titre, corps, etat, created_at, updated_at)"
            " VALUES (?, ?, ?, 'active', ?, ?)",
            (macro_id, titre, corps or "", maintenant, maintenant),
        )
        for slug in _slugs(projets):
            conn.execute("INSERT OR IGNORE INTO macro_projets (macro_id, slug) VALUES (?, ?)",
                         (macro_id, slug))
    return get_macro(macro_id)


def _slugs(projets) -> list[str]:
    if not projets:
        return []
    if isinstance(projets, str):
        projets = [projets]
    vus, propres = set(), []
    for slug in projets:
        slug = str(slug or "").strip()
        if slug and slug not in vus:
            vus.add(slug)
            propres.append(slug)
    return propres


def get_macro(macro_id: str) -> dict | None:
    with _tx() as conn:
        lignes = _rows(conn.execute("SELECT * FROM macros WHERE id = ?", (macro_id,)))
        if not lignes:
            return None
        macro = lignes[0]
        macro["projets"] = [row["slug"] for row in _rows(conn.execute(
            "SELECT slug FROM macro_projets WHERE macro_id = ? ORDER BY slug", (macro_id,)))]
    return macro


def list_macros(etat: str = "") -> list[dict]:
    with _tx() as conn:
        #  L'ordre d'affichage est celui que l'utilisateur a glissé (`macro_positions`) ; une
        #  macro jamais déplacée n'a pas de position et garde son rang d'ancienneté.
        requete = ("SELECT macros.* FROM macros"
                   " LEFT JOIN macro_positions ON macro_positions.macro_id = macros.id")
        params: tuple = ()
        if etat:
            requete += " WHERE macros.etat = ?"
            params = (etat,)
        macros = _rows(conn.execute(
            requete + " ORDER BY COALESCE(macro_positions.position, 999999), macros.created_at",
            params))
        rattachements: dict[str, list[str]] = {}
        for row in _rows(conn.execute("SELECT macro_id, slug FROM macro_projets ORDER BY slug")):
            rattachements.setdefault(row["macro_id"], []).append(row["slug"])
        etats: dict[str, dict[str, int]] = {}
        for row in _rows(conn.execute(
                "SELECT macro_id, etat, COUNT(*) AS n FROM micros GROUP BY macro_id, etat")):
            etats.setdefault(row["macro_id"], {})[row["etat"]] = row["n"]
    for macro in macros:
        macro["projets"] = rattachements.get(macro["id"], [])
        macro["micros_par_etat"] = etats.get(macro["id"], {})
    return macros


def _verifier_macro(modifiables: dict) -> None:
    if "etat" in modifiables and modifiables["etat"] not in ETATS_MACRO:
        raise EtatRefuse(f"état de macro inconnu : {modifiables['etat']!r}")
    if "titre" in modifiables and not str(modifiables["titre"] or "").strip():
        raise BriefInsuffisant("le titre d'une macro-tâche ne peut pas devenir vide")


def update_macro(macro_id: str, **champs) -> dict | None:
    """Renommer, décrire, mettre en pause — sans casser un seul rattachement (l'id ne bouge pas)."""
    modifiables = {clef: champs[clef] for clef in ("titre", "corps", "etat") if clef in champs}
    _verifier_macro(modifiables)
    if "titre" in modifiables:
        modifiables["titre"] = str(modifiables["titre"]).strip()
    if modifiables:
        with _tx() as conn:
            assignations = ", ".join(f"{clef} = ?" for clef in modifiables)
            conn.execute(f"UPDATE macros SET {assignations}, updated_at = ? WHERE id = ?",
                         (*modifiables.values(), _now(), macro_id))
    return get_macro(macro_id)


def reorder_macros(ordre: list[str]) -> list[dict]:
    """Fixe l'ordre d'affichage des chantiers : `ordre` est la liste des ids, de haut en bas.

    Les ids inconnus sont ignorés (un chantier supprimé pendant le glisser ne doit pas faire
    échouer le geste), et une macro absente de la liste garde sa position précédente."""
    ids = [str(macro_id).strip() for macro_id in (ordre or []) if str(macro_id).strip()]
    if not ids:
        raise BriefInsuffisant("l'ordre des chantiers ne peut pas être vide")
    with _tx() as conn:
        connus = {row["id"] for row in _rows(conn.execute("SELECT id FROM macros"))}
        for position, macro_id in enumerate(ids):
            if macro_id not in connus:
                continue
            conn.execute(
                "INSERT INTO macro_positions (macro_id, position) VALUES (?, ?)"
                " ON CONFLICT(macro_id) DO UPDATE SET position = excluded.position",
                (macro_id, position))
    return list_macros()


def delete_macro(macro_id: str) -> dict | None:
    """Supprime un chantier SANS emporter ses tickets : ils sont DÉTACHÉS, pas détruits.

    Supprimer un rangement ne doit jamais détruire ce qui était rangé dedans. Les micros
    retombent donc dans « non rattachées », d'où on peut les replacer ailleurs.
    """
    macro = get_macro(macro_id)
    if macro is None:
        return None
    with _tx() as conn:
        curseur = conn.execute(
            "UPDATE micros SET macro_id = '', updated_at = ? WHERE macro_id = ?",
            (_now(), macro_id))
        detachees = curseur.rowcount if curseur.rowcount and curseur.rowcount > 0 else 0
        conn.execute("DELETE FROM macros WHERE id = ?", (macro_id,))
    return {"supprime": macro_id, "titre": macro.get("titre"), "detachees": detachees}


def add_projet(macro_id: str, slug: str) -> dict | None:
    """Ajouter un dépôt EN COURS DE ROUTE : c'est le cas normal d'un chantier, pas l'exception."""
    slug = (slug or "").strip()
    if not slug:
        raise BriefInsuffisant("slug de projet vide")
    if get_macro(macro_id) is None:
        return None
    with _tx() as conn:
        conn.execute("INSERT OR IGNORE INTO macro_projets (macro_id, slug) VALUES (?, ?)",
                     (macro_id, slug))
        conn.execute("UPDATE macros SET updated_at = ? WHERE id = ?", (_now(), macro_id))
    return get_macro(macro_id)


def remove_projet(macro_id: str, slug: str) -> dict | None:
    """Retirer un dépôt d'un chantier. Ne touche à AUCUNE tâche : leur `projet_slug` propre
    reste tel quel (le dépôt d'un chantier n'est qu'un DÉFAUT de lancement)."""
    if get_macro(macro_id) is None:
        return None
    with _tx() as conn:
        conn.execute("DELETE FROM macro_projets WHERE macro_id = ? AND slug = ?",
                     (macro_id, (slug or "").strip()))
        conn.execute("UPDATE macros SET updated_at = ? WHERE id = ?", (_now(), macro_id))
    return get_macro(macro_id)


def macro_par_titre(titre: str) -> dict | None:
    """Le pont avec l'ancien monde : une chaîne libre de clôture retrouve SON id, au lieu d'en
    fabriquer une variante orthographique de plus."""
    cible = _normalise(titre)
    if not cible:
        return None
    for macro in list_macros():
        if _normalise(macro["titre"]) == cible:
            return macro
    return None


def ensure_macro(titre: str) -> dict:
    """Retrouve la macro nommée, ou la crée. Idempotent sur le titre normalisé."""
    return macro_par_titre(titre) or create_macro(titre)


def macro_du_ticket(ticket_id: str) -> str:
    """Le chantier d'où vient un ticket, ou `""` s'il ne vient d'aucune micro-tâche.

    `micro_tickets` se lisait jusqu'ici dans un seul sens (une micro → ses tickets lancés).
    La remontée inverse est ce qui permet à une clôture d'agent de rattacher ses restes AU
    MÊME chantier que le ticket qu'ils prolongent, sans que personne n'ait à le renommer.
    """
    ticket_id = (ticket_id or "").strip()
    vus: set[str] = set()
    #  Un sous-agent n'a pas de tâche : c'est son ANCÊTRE qui en a une. On remonte les parents
    #  (ticket → agent parent → ticket où cet agent a tourné), bornés et sans boucle. Cas réel
    #  (2026-09-25) : les 5 suites des enfants de l'agent 6bafe9cd naissaient « Sans chantier ».
    while ticket_id and ticket_id not in vus and len(vus) < _PROFONDEUR_MAX:
        vus.add(ticket_id)
        with _tx() as conn:
            #  `_tx()` ne pose pas de `row_factory` (tout le module passe par `_rows`), donc la
            #  ligne est un TUPLE : indexer par nom de colonne lèverait un TypeError.
            ligne = conn.execute(
                "SELECT m.macro_id FROM micro_tickets t"
                " JOIN micros m ON m.id = t.micro_id"
                " WHERE t.ticket_id = ? AND m.macro_id <> ''"
                " ORDER BY t.at LIMIT 1",
                (ticket_id,),
            ).fetchone()
            if ligne is not None:
                return str(ligne[0])
            ticket_id = _ticket_du_parent(conn, ticket_id)
    return ""


_PROFONDEUR_MAX = 8


def _ticket_du_parent(conn, ticket_id: str) -> str:
    """Le ticket où a tourné l'agent PARENT de `ticket_id` (`""` si aucun : parent humain,
    assistant sans ticket, ticket inconnu). Même base que les micros : une requête JSON."""
    parent = conn.execute("SELECT json_extract(data, '$.parent') FROM tickets WHERE id = ?"
                          " LIMIT 1", (ticket_id,)).fetchone()
    agent = str(parent[0] or "") if parent is not None else ""
    if not agent or ":" in agent:  # « dispatcher:manual » : lancé à la main
        return ""
    #  Les runs vivent dans la table `runs` depuis le lot L2 (plus dans le JSON du ticket).
    ligne = conn.execute("SELECT ticket_id FROM runs WHERE agent_id = ? LIMIT 1",
                         (agent,)).fetchone()
    return str(ligne[0]) if ligne is not None else ""


def _normalise(texte: str) -> str:
    return " ".join(str(texte or "").split()).casefold()


#  Un titre plus long qu'une ligne de liste ne sert personne : on coupe, on ne tronçonne pas
#  la phrase au milieu d'un mot si on peut l'éviter.
TITRE_MAX = 120


def titre_depuis_corps(corps: str) -> str:
    """Le titre DÉRIVÉ du corps : sa première ligne non vide, coupée à `TITRE_MAX`.

    Demande utilisateur du 2026-09-08 : « dans le ticket, je ne veux pas un titre + un
    contenu, juste un contenu ». Le titre reste stocké — `POST /api/micros/<id>/lancer` et
    `/pret` refusent une ligne sans titre, et la liste repliée du Bureau a besoin d'UNE ligne
    à afficher — mais il n'est plus SAISI : il se déduit de ce que l'utilisateur a écrit.
    """
    for ligne in str(corps or "").splitlines():
        texte = ligne.strip().lstrip("#").strip()
        if texte:
            return _coupe(texte)
    return ""


def _coupe(texte: str) -> str:
    """Une 1re ligne trop longue (brief tapé d'un trait) s'arrête à sa 1re phrase si elle tient,
    sinon au dernier mot entier, avec « … ». Couper à 120 caractères tranchait en plein mot :
    « … des sites. Par exemple, commence » (essai du 2026-09-24)."""
    if len(texte) <= TITRE_MAX:
        return texte
    fin = re.search(r"[.!?](?=\s)", texte)
    if fin and 20 <= fin.start() < TITRE_MAX:
        return texte[:fin.start()].strip()
    coupe = texte[:TITRE_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    #  Un « mot » géant (chemin, URL) : on coupe dedans plutôt que de garder trois mots.
    return (coupe if len(coupe) >= TITRE_MAX // 2 else texte[:TITRE_MAX - 1].rstrip()) + "…"


# --------------------------------------------------------------------------- micros


def _titre_initial(titre: str, corps: str) -> tuple[str, bool]:
    """(titre, explicite) : le titre saisi, sinon DÉRIVÉ du corps. `explicite` = saisi ET
    différent de la 1re ligne du corps (un tel titre ne sera jamais écrasé par le brief)."""
    saisi = (titre or "").strip()
    derive = titre_depuis_corps(corps)
    final = saisi or derive
    if not final:
        raise BriefInsuffisant("le titre d'une micro-tâche est obligatoire")
    return final, bool(saisi) and saisi != derive


def create_micro(titre: str, corps: str = "", macro_id: str = "", projet_slug: str = "",
                 origine: str = "humain", decision: bool = False,
                 session_id: str = "", source: str = "", branche_cible: str = "") -> dict:
    """Naît en `brouillon` et ne dispatche RIEN. Un titre seul suffit pour commencer ; omis, il
    est dérivé du corps.

    `session_id`/`source` sont la provenance TECHNIQUE (cf. `micro_provenance`) : écrite dans
    LA MÊME transaction que la ligne, et seulement si on la connaît.
    `branche_cible` : la branche qu'un brouillon d'intégration vise ; à défaut, lue dans son
    titre / brief (`brouillons_integres.cible_de`) — posée ici, une fois pour toutes.
    """
    from . import brouillons_integres
    titre, explicite = _titre_initial(titre, corps)
    cible = brouillons_integres.cible_de(titre, corps, branche_cible)
    origine = origine if origine in ORIGINES else "humain"
    micro_id, maintenant = _id(), _now()
    session_id, source = (session_id or "").strip(), (source or "").strip()
    with _tx() as conn:
        conn.execute(
            "INSERT INTO micros (id, macro_id, titre, corps, projet_slug, etat, origine,"
            " decision, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'brouillon', ?, ?, ?, ?)",
            (micro_id, (macro_id or "").strip(), titre, corps or "", (projet_slug or "").strip(),
             origine, 1 if decision else 0, maintenant, maintenant),
        )
        if explicite:
            conn.execute("INSERT OR IGNORE INTO micro_titres_explicites (micro_id) VALUES (?)",
                         (micro_id,))
        if session_id or source:
            conn.execute(
                "INSERT OR REPLACE INTO micro_provenance (micro_id, session_id, source, at)"
                " VALUES (?, ?, ?, ?)",
                (micro_id, session_id, source, maintenant),
            )
        _poser_cible(conn, micro_id, cible)
    return get_micro(micro_id)


def _poser_cible(conn, micro_id: str, cible: dict) -> None:
    if cible:
        conn.execute("INSERT OR REPLACE INTO micro_cibles (micro_id, ticket_id, branche)"
                     " VALUES (?, ?, ?)", (micro_id, cible["ticket_id"], cible["branche"]))


# --------------------------------------------------------------------- provenance
#  Pourquoi ces trois lectures existent : mesuré le 2026-09-21, 323 des 353 micros de la base
#  réelle viennent d'une clôture d'agent, et retrouver LA session qui avait fabriqué une ligne
#  absurde a demandé de corréler `task_events` à la seconde. Une ligne du Bureau doit pouvoir
#  dire d'où elle vient, et une vague entière doit pouvoir être auditée ou purgée en bloc.


def enregistrer_provenance(micro_id: str, session_id: str = "", source: str = "") -> None:
    """Estampille une ligne APRÈS coup (ligne créée par un autre chemin que `create_micro`).

    Idempotent (`INSERT OR REPLACE`) : ré-estampiller corrige, ça n'empile pas. Une estampille
    entièrement vide est ignorée — elle ne vaudrait pas mieux que l'absence de ligne.
    """
    micro_id = (micro_id or "").strip()
    session_id, source = (session_id or "").strip(), (source or "").strip()
    if not micro_id or not (session_id or source):
        return
    with _tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO micro_provenance (micro_id, session_id, source, at)"
            " VALUES (?, ?, ?, ?)",
            (micro_id, session_id, source, _now()),
        )


def provenance_de(micro_id: str) -> dict:
    """Rend `{}` quand on ne sait pas — jamais une provenance inventée.

    Toutes les lignes antérieures à cette table sont dans ce cas : leur session est
    définitivement inconnue, et un défaut du genre `origine='humain'` serait un mensonge.
    """
    micro_id = (micro_id or "").strip()
    if not micro_id:
        return {}
    with _tx() as conn:
        ligne = conn.execute(
            "SELECT micro_id, session_id, source, at FROM micro_provenance WHERE micro_id = ?",
            (micro_id,),
        ).fetchone()
    if ligne is None:
        return {}
    #  Index numériques : le module ne fixe pas de `row_factory`, et ça marche dans les deux cas.
    return {"micro_id": ligne[0], "session_id": ligne[1], "source": ligne[2], "at": ligne[3]}


def provenances(micro_ids: object = None) -> dict:
    """Toutes les provenances connues, indexées par `micro_id` — pour annoter une liste
    sans faire une requête par ligne. `micro_ids=None` ⇒ tout."""
    with _tx() as conn:
        lignes = conn.execute(
            "SELECT micro_id, session_id, source, at FROM micro_provenance"
        ).fetchall()
    voulus = None if micro_ids is None else {str(identifiant) for identifiant in micro_ids}
    return {
        ligne[0]: {"micro_id": ligne[0], "session_id": ligne[1],
                   "source": ligne[2], "at": ligne[3]}
        for ligne in lignes
        if voulus is None or ligne[0] in voulus
    }


def micros_de_session(session_id: str) -> list[dict]:
    """La VAGUE : toutes les lignes fabriquées par une même session, du plus ancien au plus
    récent. C'est l'unité d'audit et de purge (« supprime tout ce qu'a produit ce parsing »).

    Une session vide rend `[]` : sinon une purge lancée avec un identifiant manquant
    emporterait tout le Bureau historique, qui n'a justement aucune provenance.
    """
    session_id = (session_id or "").strip()
    if not session_id:
        return []
    with _tx() as conn:
        lignes = conn.execute(
            "SELECT micro_id FROM micro_provenance WHERE session_id = ? ORDER BY at, micro_id",
            (session_id,),
        ).fetchall()
    trouvees = [get_micro(ligne[0]) for ligne in lignes]
    #  Une provenance peut survivre à sa ligne (suppression de micro) : on ne rend que du réel.
    return [micro for micro in trouvees if micro]


def get_micro(micro_id: str) -> dict | None:
    with _tx() as conn:
        lignes = _rows(conn.execute("SELECT * FROM micros WHERE id = ?", (micro_id,)))
        if not lignes:
            return None
        micro = lignes[0]
        micro["precisions"] = _avec_transmissions(conn, _rows(conn.execute(
            "SELECT * FROM micro_precisions WHERE micro_id = ? ORDER BY rang, created_at",
            (micro_id,))))
        micro["tickets"] = _rows(conn.execute(
            "SELECT slug, ticket_id, at FROM micro_tickets WHERE micro_id = ? ORDER BY at",
            (micro_id,)))
        macro = None
        if micro["macro_id"]:
            macros = _rows(conn.execute("SELECT * FROM macros WHERE id = ?", (micro["macro_id"],)))
            macro = macros[0] if macros else None
            if macro is not None:
                macro["projets"] = [row["slug"] for row in _rows(conn.execute(
                    "SELECT slug FROM macro_projets WHERE macro_id = ? ORDER BY slug",
                    (micro["macro_id"],)))]
    return _vue(micro, macro)


def _vue(micro: dict, macro: dict | None) -> dict:
    """La forme rendue au front. `texte` est le titre : l'ancienne TO-DO en dépend, et une micro
    reste identifiable d'une ligne. `prompt` est assemblé ici, jamais bricolé par l'appelant."""
    micro["decision"] = bool(micro.get("decision"))
    micro["macro"] = macro
    micro["texte"] = micro["titre"]
    micro["prompt"] = prompt_de(micro)
    #  CALCULÉ, pas un état à conquérir : une ligne est lançable dès qu'on sait QUOI faire
    #  (un titre) et OÙ (un dépôt). `prete` reste un marqueur d'intention, jamais un péage.
    micro["lancable"] = bool((micro.get("titre") or "").strip()
                             and (micro.get("projet_slug") or "").strip()
                             and micro["etat"] not in ("faite", "abandonnee"))
    micro["transitions"] = list(TRANSITIONS.get(micro["etat"], ()))
    return micro


def _titre_du_brief(titre: str, corps: str) -> str:
    """La 1re ligne du prompt EST le titre, sans étiquette (le fil et la liste des agents la
    montrent comme sujet) — sauf s'il n'est que la 1re ligne du corps, qui suit aussitôt."""
    if titre and not _titre_deja_en_tete(titre, corps):
        return titre
    return ""


def _titre_deja_en_tete(titre: str, corps: str) -> bool:
    """Le titre EST-il déjà la 1re ligne du brief (tronquée ou non) ? Brief seul : le titre
    en est dérivé, le répéter au-dessus dupliquait le paragraphe dans le prompt."""
    tete = titre_depuis_corps(corps)
    if not tete:
        return False
    court = titre.rstrip("…. ").strip()
    premiere = next((l.strip().lstrip("#").strip() for l in corps.splitlines() if l.strip()), "")
    return titre == tete or bool(court) and (premiere.startswith(court) or court.startswith(tete))


def _section_chantier(macro: dict | None) -> list[str]:
    """Le chantier et ses informations communes, écrites une fois pour TOUTES ses tâches."""
    if not macro:
        return []
    #  L'id permet à l'agent de rattacher ses tâches restantes (taches_restantes.macro_id).
    ident = str(macro.get("id") or "").strip()
    morceaux = [f"Chantier : {macro.get('titre') or ''}".strip()
                + (f" (id {ident})" if ident else "")]
    commun = str(macro.get("corps") or "").strip()
    if commun:
        morceaux.append(f"Informations communes au chantier :\n{commun}")
    return morceaux


def _ligne_precision(p: dict) -> str:
    quand = heure_locale(p.get("created_at"), "%Y-%m-%d %H:%M")
    source = ", ".join(x for x in (str(p.get("auteur") or "humain"), quand) if x)
    return f"- ({source}) {p.get('texte') or ''}".rstrip()


def _section_precisions(precisions: list[dict]) -> str:
    """Ce qui a été ajouté au brief APRÈS coup (humain, assistant, décision) : une relance
    future le reçoit, daté, sous un titre qui dit que c'est venu compléter la consigne."""
    validees = [p for p in precisions if p.get("statut") != EN_ATTENTE]
    if not validees:
        return ""
    return "Précisions ajoutées :\n" + "\n".join(_ligne_precision(p) for p in validees)


def prompt_de(micro: dict) -> str:
    """Le brief envoyé à l'agent : titre + chantier + corps + précisions VALIDÉES.

    Une précision encore `en_attente_de_validation` est EXCLUE : un retour d'agent n'entre pas
    dans le prompt sans être passé par l'humain."""
    titre = str(micro.get("titre") or "").strip()
    corps = str(micro.get("corps") or "").strip()
    morceaux = [_titre_du_brief(titre, corps), *_section_chantier(micro.get("macro")), corps,
                _section_precisions(micro.get("precisions") or [])]
    return "\n\n".join(morceau for morceau in morceaux if morceau)


def _filtre_micros(macro_id, etat, projet, decision) -> tuple[str, tuple]:
    conditions, params = [], []
    for colonne, valeur, actif in (("macro_id", macro_id, macro_id is not None),
                                   ("etat", etat, bool(etat)),
                                   ("projet_slug", projet, bool(projet)),
                                   ("decision", 1 if decision else 0, decision is not None)):
        if actif:
            conditions.append(f"{colonne} = ?")
            params.append(valeur)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, tuple(params)


def _par_micro(conn, requete: str, ligne=lambda row: row) -> dict[str, list]:
    index: dict[str, list] = {}
    for row in _rows(conn.execute(requete)):
        index.setdefault(row["micro_id"], []).append(ligne(row))
    return index


def _macros_avec_projets(conn) -> dict[str, dict]:
    macros = {row["id"]: {**row, "projets": []} for row in _rows(conn.execute("SELECT * FROM macros"))}
    for row in _rows(conn.execute("SELECT macro_id, slug FROM macro_projets ORDER BY slug")):
        if row["macro_id"] in macros:
            macros[row["macro_id"]]["projets"].append(row["slug"])
    return macros


def list_micros(macro_id: str | None = None, etat: str = "", projet: str = "",
                decision: bool | None = None) -> list[dict]:
    where, params = _filtre_micros(macro_id, etat, projet, decision)
    with _tx() as conn:
        micros = _rows(conn.execute(f"SELECT * FROM micros{where} ORDER BY created_at", params))
        precisions = _par_micro(conn, "SELECT * FROM micro_precisions ORDER BY rang, created_at")
        tickets = _par_micro(
            conn, "SELECT micro_id, slug, ticket_id, at FROM micro_tickets ORDER BY at",
            lambda row: {"slug": row["slug"], "ticket_id": row["ticket_id"], "at": row["at"]})
        macros = _macros_avec_projets(conn)
        transmissions = _transmissions(conn)
    vues = []
    for micro in micros:
        micro["precisions"] = [{**p, "transmissions": transmissions.get(p["id"], [])}
                               for p in precisions.get(micro["id"], [])]
        micro["tickets"] = tickets.get(micro["id"], [])
        vues.append(_vue(micro, macros.get(micro["macro_id"])))
    return vues


_MODIFIABLES = ("titre", "corps", "macro_id", "projet_slug", "decision")


def _renommage(micro_id: str, champs: dict, modifiables: dict) -> bool:
    """Applique la règle du titre ; renvoie True si le titre devient EXPLICITE.

    Une tâche n'a qu'UN champ, le brief (demande utilisateur du 2026-09-24) : éditer le corps
    SANS titre recalcule TOUJOURS le titre (1re ligne non vide du brief), même s'il avait été
    posé à la main par un agent ou l'assistant — l'écran montre ce titre en tête du brief, donc
    le brief édité le contient. Seul un appelant qui envoie `titre` le fixe explicitement."""
    if "corps" in modifiables and "titre" not in modifiables:
        #  Brief vidé → titre vide aussi : garder l'ancien le faisait revenir en tête du brief
        #  affiché, le brief était impossible à vider. Lancer une tâche sans titre reste refusé.
        modifiables["titre"] = titre_depuis_corps(modifiables["corps"])
        return False
    if "titre" not in champs:
        return False
    corps_ref = modifiables.get("corps")
    if corps_ref is None:
        corps_ref = (get_micro(micro_id) or {}).get("corps") or ""
    return str(champs["titre"] or "").strip() != titre_depuis_corps(corps_ref)


def update_micro(micro_id: str, **champs) -> dict | None:
    """On revient dessus autant de fois qu'on veut : le corps est long, markdown, et jamais figé."""
    if get_micro(micro_id) is None:
        return None
    modifiables = {clef: champs[clef] for clef in _MODIFIABLES if clef in champs}
    marquer_explicite = _renommage(micro_id, champs, modifiables)
    oublier_explicite = "corps" in modifiables and "titre" not in champs
    if "titre" in modifiables:
        modifiables["titre"] = str(modifiables["titre"] or "").strip()
        if not modifiables["titre"] and "titre" in champs:
            raise BriefInsuffisant("le titre d'une micro-tâche ne peut pas devenir vide")
    if "decision" in modifiables:
        modifiables["decision"] = 1 if modifiables["decision"] else 0
    if modifiables:
        with _tx() as conn:
            assignations = ", ".join(f"{clef} = ?" for clef in modifiables)
            conn.execute(f"UPDATE micros SET {assignations}, updated_at = ? WHERE id = ?",
                         (*modifiables.values(), _now(), micro_id))
            if marquer_explicite:
                conn.execute("INSERT OR IGNORE INTO micro_titres_explicites (micro_id)"
                             " VALUES (?)", (micro_id,))
            elif oublier_explicite:
                conn.execute("DELETE FROM micro_titres_explicites WHERE micro_id = ?", (micro_id,))
    return get_micro(micro_id)


def titre_explicite(micro_id: str) -> bool:
    """Le titre a-t-il été SAISI (et non dérivé de la 1re ligne du brief) ?"""
    with _tx() as conn:
        return conn.execute("SELECT 1 FROM micro_titres_explicites WHERE micro_id = ?",
                            (micro_id,)).fetchone() is not None


def add_precision(micro_id: str, texte: str, auteur: str = "humain",
                  statut: str = "validee") -> dict | None:
    """Append-only : on AJOUTE, on n'écrase jamais. Trace qui a précisé quoi, et quand."""
    texte = str(texte or "").strip()
    if not texte:
        raise BriefInsuffisant("une précision vide n'apporte rien")
    if get_micro(micro_id) is None:
        return None
    ligne = {"id": _id(), "micro_id": micro_id, "auteur": auteur or "humain",
             "texte": texte, "statut": statut, "created_at": _now()}
    with _tx() as conn:
        rangs = _rows(conn.execute(
            "SELECT COALESCE(MAX(rang), 0) AS dernier FROM micro_precisions WHERE micro_id = ?",
            (micro_id,)))
        ligne["rang"] = int(rangs[0]["dernier"]) + 1
        conn.execute(
            "INSERT INTO micro_precisions (id, micro_id, auteur, texte, statut, created_at, rang)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ligne["id"], micro_id, ligne["auteur"], texte, statut, ligne["created_at"],
             ligne["rang"]),
        )
        conn.execute("UPDATE micros SET updated_at = ? WHERE id = ?", (_now(), micro_id))
    #  On rend la PRÉCISION, pas la micro : l'appelant qui veut la micro rappelle `get_micro`.
    #  Rendre la micro ici faisait répondre `{"precision": <micro>}` aux routes — d'où l'absence
    #  de la clé `statut` que l'humain doit justement arbitrer.
    return ligne


def _transmissions(conn) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for row in _rows(conn.execute("SELECT * FROM micro_transmissions ORDER BY created_at")):
        index.setdefault(row["precision_id"], []).append(row)
    return index


def _avec_transmissions(conn, precisions: list[dict]) -> list[dict]:
    if not precisions:
        return precisions
    index = _transmissions(conn)
    return [{**p, "transmissions": index.get(p["id"], [])} for p in precisions]


def enregistrer_transmission(precision_id: str, agent_id: str, queue_id: str,
                             mode: str = "ajout") -> None:
    """La précision `precision_id` est partie dans la file de `agent_id` (message `queue_id`)."""
    with _tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO micro_transmissions"
            " (queue_id, precision_id, agent_id, mode, statut, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (queue_id, precision_id, agent_id, mode or "ajout", "en_attente", _now()))


def agents_a_suivre() -> list[str]:
    """Les agents à qui une précision a été transmise et qui ne l'ont pas encore lue."""
    with _tx() as conn:
        return [row[0] for row in conn.execute(
            "SELECT DISTINCT agent_id FROM micro_transmissions WHERE statut = 'en_attente'")]


def marquer_transmission(queue_id: str, statut: str) -> None:
    """L'agent a lu (`lue`) — ou ne lira jamais (`non_lue`) — le message `queue_id`."""
    with _tx() as conn:
        conn.execute("UPDATE micro_transmissions SET statut = ?, lu_at = ?"
                     " WHERE queue_id = ? AND statut = 'en_attente'", (statut, _now(), queue_id))


def valider_precision(micro_id: str, precision_id: str, texte: str = "") -> dict | None:
    """Je garde tel quel, je corrige, ou (via `jeter_precision`) je jette. C'est l'arbitrage."""
    if get_micro(micro_id) is None:
        return None
    with _tx() as conn:
        existantes = _rows(conn.execute(
            "SELECT * FROM micro_precisions WHERE id = ? AND micro_id = ?",
            (precision_id, micro_id)))
        if not existantes:
            return None
        corrige = str(texte or "").strip()
        if corrige:
            conn.execute("UPDATE micro_precisions SET texte = ?, statut = 'validee' WHERE id = ?",
                         (corrige, precision_id))
        else:
            conn.execute("UPDATE micro_precisions SET statut = 'validee' WHERE id = ?",
                         (precision_id,))
        conn.execute("UPDATE micros SET updated_at = ? WHERE id = ?", (_now(), micro_id))
    return get_micro(micro_id)


def jeter_precision(micro_id: str, precision_id: str) -> dict | None:
    """Jeter une PROPOSITION non validée. Une précision déjà validée, elle, ne s'efface pas :
    l'historique du brief est append-only, sinon on perd la trace de ce qui a été décidé."""
    if get_micro(micro_id) is None:
        return None
    with _tx() as conn:
        conn.execute("DELETE FROM micro_precisions WHERE id = ? AND micro_id = ? AND statut = ?",
                     (precision_id, micro_id, EN_ATTENTE))
        conn.execute("UPDATE micros SET updated_at = ? WHERE id = ?", (_now(), micro_id))
    return get_micro(micro_id)


def supprimer_precision(micro_id: str, precision_id: str) -> bool:
    """Jette une précision — typiquement une proposition d'assistant que l'humain refuse.

    Le filtre porte sur les DEUX clés : une précision appartient à sa micro-tâche, et un id
    de précision connu ne doit pas permettre de supprimer chez la voisine. `rowcount` fait
    office de verdict d'existence, ce qui évite un SELECT préalable."""
    with _tx() as conn:
        curseur = conn.execute("DELETE FROM micro_precisions WHERE id = ? AND micro_id = ?",
                               (precision_id, micro_id))
        if not curseur.rowcount:
            return False
        conn.execute("UPDATE micros SET updated_at = ? WHERE id = ?", (_now(), micro_id))
    return True


def marquer_pret(micro_id: str) -> dict | None:
    """Le geste EXPLICITE. Refuse un titre vide, ou une micro sans projet NI macro : un brief qui
    ne dit pas où il s'applique n'est pas un brief."""
    micro = get_micro(micro_id)
    if micro is None:
        return None
    if not str(micro.get("titre") or "").strip():
        raise BriefInsuffisant("titre vide : rien à briefer")
    if not (micro.get("projet_slug") or micro.get("macro_id")):
        raise BriefInsuffisant("ni projet ni macro-tâche : personne ne sait où ce travail s'applique")
    return marquer_etat(micro_id, "prete")


def marquer_etat(micro_id: str, etat: str, pourquoi: str = "") -> dict | None:
    """LA porte unique des changements d'état. Une transition hors du cycle lève `EtatRefuse` —
    et un retour en brouillon transforme sa raison en précision, pour que l'échec ENRICHISSE le
    brief au lieu de le perdre."""
    micro = get_micro(micro_id)
    if micro is None:
        return None
    if etat not in ETATS_MICRO:
        raise EtatRefuse(f"état inconnu : {etat!r}")
    depart = micro["etat"]
    if etat != depart and etat not in TRANSITIONS.get(depart, ()):
        raise EtatRefuse(f"transition refusée : {depart} → {etat}")
    raison = str(pourquoi or "").strip()
    with _tx() as conn:
        conn.execute("UPDATE micros SET etat = ?, pourquoi = ?, updated_at = ? WHERE id = ?",
                     (etat, raison or micro.get("pourquoi") or "", _now(), micro_id))
        if etat == "brouillon" and depart != "brouillon":
            conn.execute("INSERT OR REPLACE INTO micro_reouvertures (micro_id, at) VALUES (?, ?)",
                         (micro_id, _now()))
    if raison:
        add_precision(micro_id, raison, auteur="humain")
    return get_micro(micro_id)


def reouvertures() -> dict[str, str]:
    """`{micro_id: at}` des tâches rouvertes (retour voulu en brouillon) — une requête pour l'écran."""
    with _tx() as conn:
        rows = conn.execute("SELECT micro_id, at FROM micro_reouvertures").fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def lier_ticket(micro_id: str, slug: str, ticket_id: str) -> dict | None:
    """Une micro-tâche peut lancer PLUSIEURS tickets : on ajoute, on ne remplace pas."""
    if get_micro(micro_id) is None:
        return None
    with _tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO micro_tickets (micro_id, slug, ticket_id, at)"
            " VALUES (?, ?, ?, ?)", (micro_id, slug or "", ticket_id or "", _now()))
        conn.execute("UPDATE micros SET updated_at = ? WHERE id = ?", (_now(), micro_id))
    return get_micro(micro_id)


# ------------------------------------------------------------------------- retours


def add_retour(micro_id: str, texte: str, ticket_id: str = "", mode: str = "") -> dict | None:
    """Enregistre un retour humain donné en relançant (« ce qui ne va pas / ce qui manque »).

    Append-only, comme les précisions. Un retour VIDE n'est pas enregistré : relancer sans
    rien dire est permis (reprise après un arrêt), mais ne laisse pas de ligne fantôme."""
    texte = str(texte or "").strip()
    if not texte or get_micro(micro_id) is None:
        return None
    ligne = {"id": _id(), "micro_id": micro_id, "texte": texte,
             "ticket_id": (ticket_id or "").strip(), "mode": (mode or "").strip(),
             "created_at": _now()}
    with _tx() as conn:
        conn.execute("INSERT INTO micro_retours (id, micro_id, texte, ticket_id, mode, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)",
                     (ligne["id"], micro_id, texte, ligne["ticket_id"], ligne["mode"],
                      ligne["created_at"]))
        conn.execute("UPDATE micros SET updated_at = ? WHERE id = ?", (_now(), micro_id))
    return ligne


def rattacher_retour(retour_id: str, ticket_id: str) -> None:
    """Le lancement a produit son ticket : le retour qui l'a déclenché le désigne désormais."""
    with _tx() as conn:
        conn.execute("UPDATE micro_retours SET ticket_id = ? WHERE id = ?",
                     ((ticket_id or "").strip(), retour_id))


def retours_de(micro_id: str) -> list[dict]:
    with _tx() as conn:
        return _rows(conn.execute(
            "SELECT id, micro_id, texte, ticket_id, mode, created_at FROM micro_retours"
            " WHERE micro_id = ? ORDER BY created_at, rowid", (micro_id,)))


def tous_les_retours() -> dict[str, list[dict]]:
    """`{micro_id: [retours…]}` en UNE requête, pour annoter toute la liste du Bureau."""
    with _tx() as conn:
        lignes = _rows(conn.execute(
            "SELECT id, micro_id, texte, ticket_id, mode, created_at FROM micro_retours"
            " ORDER BY created_at, rowid"))
    index: dict[str, list[dict]] = {}
    for ligne in lignes:
        index.setdefault(ligne["micro_id"], []).append(ligne)
    return index


def micro_par_ticket() -> dict[str, dict]:
    """`{ticket_id: {micro_id, titre, macro_id}}` : la tâche du Bureau d'où vient chaque ticket."""
    with _tx() as conn:
        lignes = _rows(conn.execute(
            "SELECT t.ticket_id, m.id AS micro_id, m.titre, m.macro_id FROM micro_tickets t"
            " JOIN micros m ON m.id = t.micro_id"))
    return {ligne["ticket_id"]: ligne for ligne in lignes if ligne.get("ticket_id")}


def doublons() -> list[dict]:
    """Les micros qui disent la même chose dans la même macro. Clé = (titre normalisé, macro_id) :
    c'est ce qui remplace « quatre lignes identiques » par « demandé par N agents »."""
    groupes: dict[tuple[str, str], list[dict]] = {}
    for micro in list_micros():
        groupes.setdefault((_normalise(micro["titre"]), micro["macro_id"]), []).append(micro)
    return [{"titre": lot[0]["titre"], "macro_id": clef[1], "demandes": len(lot),
             "ids": [micro["id"] for micro in lot]}
            for clef, lot in groupes.items() if len(lot) > 1]
