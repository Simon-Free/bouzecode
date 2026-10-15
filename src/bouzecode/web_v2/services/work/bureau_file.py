# [desc] Le fichier bureau.md : lecture des lignes humaines, ancres [#id], bloc de la machine. [/desc]
"""`~/.bouzecode/bureau/bureau.md` — le fichier que l'humain tient à la main.

RÈGLE D'OR, non négociable : la machine ne modifie JAMAIS le texte d'une ligne humaine.
Elle a exactement deux droits : ajouter ` [#<id>]` en fin d'une ligne qu'elle vient de
promouvoir en tâche, et réécrire le bloc balisé qui lui appartient, en bas du fichier.

Second volet de la règle d'or : si le fichier a changé entre le moment où la machine a
lu et le moment où elle écrit, elle ABANDONNE son écriture (`apply()` renvoie False) et
réessaiera au tour suivant. Un conflit d'édition se résout toujours en faveur de l'humain.
"""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import os
import re
from pathlib import Path

BUREAU_DIR = bouzecode_data_dir() / "bureau"

MARK_BEGIN = "<!-- bureau:début — bloc de la machine, ne pas éditer à la main -->"
MARK_END = "<!-- bureau:fin -->"
STATE_LABELS = {"a_faire": "à faire", "en_cours": "en cours", "bloquee": "bloquée",
                "a_relire": "à relire", "fait": "fait", "abandonnee": "abandonnée"}

_BULLET = re.compile(r"^\s*[-*]\s+(?P<body>.*?)\s*$")
_ANCHOR = re.compile(r"\[#(?P<id>[0-9a-fA-F]{4,12})\]\s*$")


def bureau_path() -> Path:
    """Le chemin du fichier (BUREAU_DIR est relu à chaque appel : les tests le déplacent)."""
    return BUREAU_DIR / "bureau.md"


def read_text() -> str:
    """Le contenu du fichier, ou '' s'il n'existe pas encore."""
    path = bureau_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def human_part(text: str) -> str:
    """Tout ce qui précède le bloc de la machine — la zone que la machine ne réécrit pas."""
    index = text.find(MARK_BEGIN)
    return text if index < 0 else text[:index]


def anchor_of(line: str) -> str:
    """L'id de tâche ancré en fin de ligne, ou '' si la ligne n'est pas encore ancrée."""
    found = _ANCHOR.search(line)
    return found.group("id") if found else ""


def bullet_body(line: str) -> str:
    """Le texte d'une ligne de puce, sans le tiret ni l'ancre ; '' si ce n'est pas une puce."""
    found = _BULLET.match(line)
    if not found:
        return ""
    return _ANCHOR.sub("", found.group("body")).strip()


def unanchored(text: str) -> list[str]:
    """Les lignes de puce humaines qui n'ont pas encore d'ancre — candidates à l'import."""
    seen: list[str] = []
    for line in human_part(text).splitlines():
        if anchor_of(line):
            continue
        body = bullet_body(line)
        if body and body not in seen:
            seen.append(body)
    return seen


def block_row(task: dict) -> str:
    """Une ligne du bloc machine : `3b1e  en cours  migrer l'ingestion demo_table`.

    L'état affiché est l'état STOCKÉ de la tâche : ce module ne manipule que du texte, lui faire
    dériver l'état imposerait d'y ouvrir la base des tickets.
    """
    title = " ".join(str(task.get("title") or "").split())
    if len(title) > 70:
        title = title[:69] + "…"
    return f"{task.get('id', '')}  {STATE_LABELS.get(task.get('state'), str(task.get('state') or ''))}  {title}".rstrip()


def render_block(rows: list[str]) -> str:
    """Le bloc de la machine, balises comprises."""
    return "\n".join([MARK_BEGIN, *rows, MARK_END]) + "\n"


def _anchored(human: str, anchors: dict[str, str]) -> str:
    """Le texte humain avec ` [#id]` ajouté en fin des lignes citées — rien d'autre ne bouge."""
    out: list[str] = []
    for line in human.splitlines():
        body = bullet_body(line)
        task_id = anchors.get(body, "")
        if body and task_id and not anchor_of(line):
            out.append(f"{line.rstrip()} [#{task_id}]")
        else:
            out.append(line)
    return "\n".join(out)


def append_human_line(line: str, expected_text: str) -> bool:
    """Ajoute UNE ligne à la fin de la zone humaine. False = écriture ABANDONNÉE (conflit).

    Même règle d'or que `apply()` : aucune ligne humaine existante n'est touchée, le bloc de la
    machine est recopié tel quel, et si le fichier a changé depuis la lecture on abandonne.
    """
    path = bureau_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_text() != expected_text:
        return False
    index = expected_text.find(MARK_BEGIN)
    block = expected_text[index:] if index >= 0 else ""
    human = human_part(expected_text).rstrip("\n")
    human = f"{human}\n{line}" if human else line
    scratch = path.with_suffix(".md.tmp")
    scratch.write_text(human + (f"\n\n{block}" if block else "\n"), encoding="utf-8")
    os.replace(scratch, path)
    return True


def apply(anchors: dict[str, str], rows: list[str], expected_text: str) -> bool:
    """Ancre les lignes citées et réécrit le bloc machine. False = écriture ABANDONNÉE.

    `expected_text` est le contenu lu au début du travail. Le fichier est relu juste avant
    d'écrire : s'il diffère, l'humain a édité entre-temps et l'écriture est abandonnée.
    """
    path = bureau_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_text() != expected_text:
        return False
    human = _anchored(human_part(expected_text), anchors).rstrip("\n")
    body = f"{human}\n\n" if human else ""
    scratch = path.with_suffix(".md.tmp")
    scratch.write_text(body + render_block(rows), encoding="utf-8")
    os.replace(scratch, path)
    return True
