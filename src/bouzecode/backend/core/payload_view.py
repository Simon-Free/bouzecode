# [desc] Vue du contexte d'un tour : replie les deltas du journal des payloads en payloads complets. [/desc]
"""Relit `~/.bouzecode/debug_payloads/<session_id>/turns.jsonl` et rend chaque payload ENTIER.

LE CONTEXTE D'UN TOUR EST UNE VUE, PAS UNE DONNÉE STOCKÉE. Le journal ne garde que ce qui
CHANGE d'un enregistrement au suivant ; ce module le replie. Voir `agent/payload_dump.py` pour
le côté écriture et la mesure qui a motivé le changement (219 Mo pour une seule session, dont
le dernier enregistrement — le seul complet — pèse 1 Mo).

POURQUOI CE MODULE EST DANS `core` ET PAS À CÔTÉ DE L'ÉCRIVAIN : ses lecteurs sont le
visualiseur de contexte de BouzéqUI, l'analyse de session et l'export wire. Importer
`backend.agent.payload_dump` depuis eux déclenche `backend/agent/__init__` → la boucle
d'agent → le registre d'outils → le chargement des plugins. C'est une cascade entière pour
lire un fichier, et elle casse dès qu'un appelant n'a pas l'environnement complet (constaté :
`TypeError` dans le store de plugins). `core` n'importe rien de tout ça.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Séparateur des blocs de texte. Les gros champs du journal (note de méthodologie, blocs
# système) sont des textes composés de blocs joints par une ligne vide : c'est la maille à
# laquelle ils se répètent d'un tour à l'autre, donc la maille à laquelle il faut les adresser.
SEP = "\n\n"


def _hash(texte: str) -> str:
    return hashlib.blake2b(texte.encode("utf-8"), digest_size=8).hexdigest()


def to_refs(texte: str, blobs: dict, connus: set) -> list[str]:
    """Découpe `texte` en blocs et rend leurs empreintes, en n'ajoutant à `blobs` que les
    blocs JAMAIS ÉCRITS auparavant dans ce journal.

    C'est ce qui casse la croissance quadratique : une note qui passe de 10 à 11 blocs entre
    deux tours n'écrit que le 11e. Mesuré sur une session réelle, les notes pesaient 137 Mo
    pour 0,48 Mo de contenu final."""
    refs = []
    for bloc in (texte or "").split(SEP):
        h = _hash(bloc)
        refs.append(h)
        if h not in connus:
            connus.add(h)
            blobs[h] = bloc
    return refs


def from_refs(refs: list[str], blobs: dict) -> str:
    """Recompose un texte depuis ses empreintes. Un bloc manquant est rendu visible plutôt
    que silencieusement vide : un journal tronqué doit se voir."""
    return SEP.join(blobs.get(h, f"[bloc {h} absent du journal]") for h in refs or [])


def payload_dir(session_id: str) -> Path:
    from .config import CONFIG_DIR
    return Path(CONFIG_DIR) / "debug_payloads" / session_id


def fold_records(records) -> list[dict]:
    """Déplie une suite d'enregistrements : chacun ressort avec son `messages` COMPLET.

    Le pliage suit l'ordre du FICHIER, pas celui des tours : il y a deux enregistrements par
    tour (avant et après le stream) et le delta de chacun porte sur celui qui le précède
    physiquement. Un enregistrement ABSOLU (clé `messages`) réinitialise la base — c'est ce qui
    rend le journal relisable après une reprise de process, et compatible avec tout ce qui a
    été écrit avant le passage aux deltas."""
    deplies: list[dict] = []
    base: list = []
    blobs: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        blobs.update(record.get("blobs") or {})
        if "messages" in record:
            base = record["messages"] or []
            complet = dict(record)
        else:
            keep = int(record.get("keep") or 0)
            base = list(base[:keep]) + list(record.get("append") or [])
            complet = {k: v for k, v in record.items() if k not in ("keep", "append")}
            complet["messages"] = base
        _restaurer_textes(complet, blobs)
        deplies.append(complet)
    return deplies


def _restaurer_textes(record: dict, blobs: dict) -> None:
    """Recompose sur place les gros textes adressés par empreinte (blocs système, notes).

    Les enregistrements écrits AVANT l'adressage par contenu portent déjà leurs textes en
    clair : ils n'ont ni `system_blocks_refs` ni `notes_refs`, donc rien ne les touche."""
    record.pop("blobs", None)
    refs_blocs = record.pop("system_blocks_refs", None)
    if refs_blocs is not None:
        record["system_blocks"] = [
            {**{k: v for k, v in bloc.items() if k != "refs"},
             "text": from_refs(bloc.get("refs"), blobs)}
            for bloc in refs_blocs
        ]
    refs_notes = record.pop("notes_refs", None)
    if refs_notes is not None:
        etat = dict(record.get("context_state") or {})
        etat["notes"] = {cle: from_refs(refs, blobs) for cle, refs in refs_notes.items()}
        record["context_state"] = etat


def read_records(session_id: str, payloads_dir: Path | None = None) -> list[dict]:
    """Enregistrements BRUTS du journal, dans l'ordre du fichier. [] si aucun journal."""
    path = (Path(payloads_dir) if payloads_dir is not None
            else payload_dir(session_id)) / "turns.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def load_turn_records(session_id: str, payloads_dir: Path | None = None) -> list[dict]:
    """Le journal d'une session, chaque enregistrement portant son `messages` reconstitué.

    Point d'entrée UNIQUE des lecteurs : ils ne connaissent jamais la forme du stockage."""
    return fold_records(read_records(session_id, payloads_dir))


def load_turn_map(session_id: str, payloads_dir: Path | None = None) -> dict:
    """`{numéro de tour: enregistrement complet}`, DERNIER GAGNANT.

    Deux enregistrements par tour : un avant le stream (requête seule), un enrichi après
    (system_blocks, token_counts, réponse). Le plus riche est écrit en dernier — d'où la règle
    du dernier gagnant, que les trois lecteurs appliquaient déjà chacun de leur côté."""
    return {record.get("turn"): record
            for record in load_turn_records(session_id, payloads_dir)}
