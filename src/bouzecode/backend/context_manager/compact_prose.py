# [desc] LLM compaction of a note's prose into one model-written `## compacted-history` synthesis block [/desc]
"""LLM compaction of the note's PROSE.

``compact_judge`` only ever drops blocks that carry a snippet key. Every
``key is None`` block — the agent's own reasoning, which measures ~69 % of a
long note — is untouched by it, so a note made mostly of prose cannot shrink at
all: the pass fires, judges the snippets, and removes 0 characters.

This pass closes that hole. It hands the prose to the model and replaces it with
one ``## compacted-history`` block, judged against a single test: an agent handed
that block and nothing else must be able to carry the task on, without asking for
anything back and without re-exploring a path already explored. Facts, decisions
and their reasons, paths and dead ends serve that test; narration does not.

There is no floor, no ratio and no "recent entries are protected" rule: the
compaction only ever runs when the cached prefix has already grown expensive
(see ``compact_methodology``), and at that point the model — not an arbitrary
threshold — decides what is worth keeping. Three safeguards remain.

1. An empty answer leaves the note untouched: a truncated stream or a provider
   error must never erase the note.
2. The mission has to COME OUT of the summary. ``## User`` blocks ARE candidates
   — keeping them verbatim meant every user message in the session piled up for
   good — but a summary is REJECTED unless it opens on a ``Mission en cours :``
   line (see ``_states_the_mission``). Same incident behind the rule (2026-08-21:
   an agent lost its brief mid-run and had to stop and ask what it was supposed
   to deliver), enforced on the OUTPUT instead of the input: requiring the
   statement is checkable, hoarding the text was not.
3. A pass with nothing substantially new to fold in is skipped BEFORE the call.
   The previous version re-fed its own ``## compacted-history`` block on every
   trigger, so it kept paying a full side-call to summarise a summary: on that
   same session 11 of ~20 runs removed 0 or 1 characters, and the summary was
   rewritten five times over at an identical 7 189 chars — pure spend, plus the
   slow decay of a summary of a summary.

Segmentation note: ``_split_into_blocks`` only cuts on ``## `` while inside a
snippet block, so a prose-only note comes back as ONE block. This module
re-segments prose on its own ``## `` headings - one heading, one unit - instead
of touching that shared splitter.
"""
import logging

from ..core.config import DEFAULTS
from .note_blocks import _split_into_blocks

_log = logging.getLogger(__name__)

# Same model as the snippet judge, and for the same reason: this pass REWRITES the
# note, so anything its answer fails to carry over is lost. Resolved at call time on
# the session's provider (providers/side_model.py).


def summary_model(config: dict | None) -> str:
    from ..agent.providers.side_model import modele_annexe
    return modele_annexe(config)

SUMMARY_HEADER = "## compacted-history"

# Below this many characters of prose the existing summary does not already
# cover, the pass is skipped without calling the model. Measured floor, not a
# guess: every run that removed 0 or 1 chars carried a single small block next
# to the summary, while the runs that paid off carried several thousand chars.
_MIN_FRESH_PROSE_CHARS = 2000


# Plafond APPLIQUE, aligne sur le budget demande au modele. Un resume qui garde plus
# de cette part de son entree n'est pas une compaction :
# il fait payer la regravure complete du prefixe cache pour un gain marginal. Mesure
# du 2026-08-22 sur une session de 425 tours : les passes 'utiles' gardaient 83 % de
# leur entree (mediane), et la note a quand meme atteint 79 000 tokens. Refuser une
# telle passe laisse la note intacte — donc SANS invalider le cache — ce qui est
# strictement moins cher que de la reecrire pour rien.
_MAX_SUMMARY_RATIO = 0.2

# Nombre total de tentatives. Une passe qui depasse le plafond n'est pas abandonnee :
# on redemande de compacter davantage, en indiquant de combien on depasse. Le materiau
# reste dans le prefixe CACHE d'un appel a l'autre, donc une tentative de plus ne coute
# que la relecture du cache (0,1x) plus le delta.
_MAX_ATTEMPTS = 3

# Budget de SORTIE de l'appel de compaction. Il n'y a pas de nombre magique ici :
# le plafond fonctionnel de la passe est `_MAX_SUMMARY_RATIO`, exprime en
# CARACTERES (`ceiling`), donc le budget en tokens doit en DECOULER. Un cap fixe
# de 4096 tokens (~14 000 caracteres) coupait mecaniquement les TROIS tentatives
# des que la prose compactable depassait ~72 000 caracteres : trois appels payes
# pour un refus, et un `stop_reason=max_tokens` qui faisait accuser a tort le
# tour de l'agent.
#
# La marge est VOLONTAIRE : un resume legerement au-dessus du plafond doit rester
# ECRIVABLE pour que `_stalled`/`_salvage` puissent le juger. Coupe net par le
# fournisseur, il ressemble a un refus et les tentatives sont perdues.
_CHARS_PER_TOKEN = 3.5
_ANSWER_MARGIN = 1.5
# Plancher : en dessous, meme une petite note ne peut pas etre resumee proprement.
_MIN_ANSWER_TOKENS = 4096

# Nom porte par l'appel jusqu'au streamer, pour qu'un avertissement de troncature
# dise QUI a ete tronque au lieu de laisser croire que le tour de l'agent l'a ete.
_CALL_LABEL = "note prose compaction"


def _answer_budget(ceiling: int, config: dict | None) -> int:
    """Tokens a demander pour ecrire un resume qui tient dans `ceiling` caracteres.

    Borne par le budget de la session : la compaction ne doit jamais demander plus
    que ce que l'agent lui-meme a le droit de produire.
    """
    cap = int((config or {}).get("max_tokens") or DEFAULTS["max_tokens"])
    needed = int(ceiling / _CHARS_PER_TOKEN * _ANSWER_MARGIN)
    return max(_MIN_ANSWER_TOKENS, min(needed, cap))


# Le resume DOIT s'ouvrir la-dessus. C'est ce qui remplace l'ancienne protection
# verbatim des blocs `## User` : on n'entasse plus la consigne brute, on exige
# qu'elle soit reformulee — et on le verifie.
_MISSION_MARKER = "Mission en cours"

_SYSTEM = (
    "You compact the working notes of a coding agent.\n"
    "You are given its note entries. Rewrite them as a dense briefing.\n"
    "\n"
    "THE TEST YOUR ANSWER MUST PASS: the agent is handed your briefing and NOTHING\n"
    "else, and must carry the task on from there — without asking for anything back,\n"
    "and without spending a single turn re-exploring a path that has already been\n"
    "explored. Judge every line against that test: what serves it stays, what does\n"
    "not goes. Dropping is the default.\n"
    "\n"
    "To pass, a briefing has to carry: what has been ESTABLISHED (facts, measured\n"
    "numbers), what has been DECIDED and the reason behind it, the identifiers\n"
    "needed to act (absolute paths, file and symbol names, commands, UUIDs, commits,\n"
    "URLs, versions), what has already been TRIED AND RULED OUT and why it was ruled\n"
    "out, and the task in progress with its next step.\n"
    "\n"
    "It fails if it carries narration, restatements, politeness, per-turn ceremony,\n"
    "finished checklists, duplicates, or anything belonging to a task the session has\n"
    "already moved on from. Those cost the agent tokens and buy it nothing.\n"
    "\n"
    "BUDGET — your answer MUST fit in a FIFTH of the input you are given.\n"
    "This is not a style preference. The notes live in the cached prefix: a\n"
    "briefing that keeps most of its input forces a full rewrite of that prefix\n"
    "and saves nothing, so it costs more than doing nothing at all. If you cannot\n"
    "reach a fifth, you are keeping material that can be re-derived — cut it.\n"
    "\n"
    "OPEN WITH THE MISSION. The first line of your answer MUST be\n"
    "`Mission en cours : <what the agent has been asked to deliver>` — one sentence,\n"
    "distilled from the `## User` entries. Those entries are yours to compact like any\n"
    "other material; what must survive is the statement of the goal, not their wording.\n"
    "A briefing that does not open with that line is rejected.\n"
    "\n"
    "PRIORITY — A MEASURED RESULT OUTLIVES WHAT PRODUCED IT. A number, a count, a\n"
    "test verdict, a diagnosis: keep it even when the query, the script or the code\n"
    "that yielded it is dropped. The reverse is a trap — keeping the command and\n"
    "losing its result forces the agent to run it again, which is precisely the\n"
    "spend this note exists to avoid.\n"
    "\n"
    "Write terse markdown bullets. No preamble, no conclusion, no code fences. "
    "Never invent: if a fact is not in the input, it does not exist."
)


def compact_prose(note: str, context_state, config: dict | None) -> tuple[str, int]:
    """Replace the prose of ``note`` by one model-written synthesis.

    Returns ``(new_note, chars_removed)``. Never raises: on any failure the note
    is handed back untouched, because losing a decision costs more than keeping
    a few thousand characters.
    """
    try:
        return _compact(note, context_state, config)
    except Exception as exc:  # pragma: no cover - defensive
        from ..agent.providers.side_model import signaler_echec
        signaler_echec("synthèse de compaction", summary_model(config), exc)
        return note, 0


def _compact(note: str, context_state, config: dict | None) -> tuple[str, int]:
    units = _units(note)
    candidates = _candidates(units)
    if not candidates or not _worth_a_call(units, candidates):
        return note, 0
    replaced = sum(len(units[i]) for i in candidates)

    ceiling = int(replaced * _MAX_SUMMARY_RATIO)
    prose = "\n".join(units[i] for i in candidates)
    mission = _mission(units)

    # Over the ceiling is not a refusal: we say by how much and ask again. `prose`
    # carries the cache breakpoint, so each extra attempt re-reads it from cache
    # instead of re-sending it.
    summary, attempts, usages, accepted = "", [], [], False
    for _ in range(_MAX_ATTEMPTS):
        summary, usage = _ask(prose, mission, config, attempts, ceiling)
        usages.append(usage)
        # An empty answer means a refusal or a cut stream. Rewriting the note with
        # nothing would delete the agent's memory outright, so it stays as it is.
        if not summary.strip():
            _journal(config, len(candidates), len(summary), 0, replaced, usages, summary)
            return note, 0
        if len(summary) <= ceiling and _states_the_mission(summary):
            accepted = True
            break
        attempts.append(summary)
        if _stalled(attempts, ceiling):
            break

    if not accepted:
        summary = _salvage(summary, mission, ceiling)
        if not summary:
            # Only a summary still OVER THE CEILING is thrown away. The note is
            # handed back untouched, which leaves the cached prefix VALID —
            # strictly cheaper than rewriting it for a gain the model missed.
            _log.info("prose compaction refused after %d attempts: %d chars for a %d ceiling",
                      len(usages), len(attempts[-1]), ceiling)
            _journal(config, len(candidates), len(attempts[-1]), 0, replaced,
                     usages, attempts[-1])
            return note, 0

    summary = _retrograder_titres(summary)
    block = (f"{SUMMARY_HEADER} ({len(candidates)} entries compacted, "
             f"{replaced} chars -> {len(summary)})\n\n{summary.strip()}")
    new_note = _rebuild(units, candidates, block)
    removed = len(note) - len(new_note)
    if removed <= 0:
        _journal(config, len(candidates), len(summary), 0, replaced, usages, summary)
        return note, 0

    _journal(config, len(candidates), len(summary), removed, replaced, usages, summary)
    count = getattr(context_state, "_prose_compactions", 0)
    setattr(context_state, "_prose_compactions", count + 1)
    return new_note, removed


def _retrograder_titres(summary: str) -> str:
    """Les titres ``## `` de la synthese deviennent ``### ``.

    La note se decoupe sur ``## `` : une synthese a 7 sous-titres revenait, a la passe
    suivante, en 7 unites dont 6 passaient pour de la prose NOUVELLE (~5 500 caracteres,
    au-dessus du plancher de `_worth_a_call`) — la garde « rien de neuf a resumer » etait
    contournee (rejeu du 2026-09-24). Un titre ``## snippet:`` recopie dans la synthese
    serait meme pris pour un extrait vivant."""
    return "\n".join("#" + line if line.startswith("## ") else line
                     for line in summary.split("\n"))


def _salvage(summary: str, mission: str, ceiling: int) -> str:
    """Rattraper un resume qui TIENT dans le plafond mais n'ouvre pas sur la mission.

    Les deux tests ne meritent pas la meme sanction. Depasser le plafond est un
    echec de compaction : il n'y a rien a sauver, et refuser laisse au moins le
    cache valide. Omettre la ligne d'ouverture n'est pas un echec de compaction :
    le resume est bon, il lui manque une phrase que nous savons ecrire nous-memes.

    Mesure du 2026-08-23, agent f52cb5297f4f : aux tours 128, 129 et 130 la passe
    rendait 6 565 / 5 243 / 6 728 caracteres pour des plafonds de 20 441 / 20 913 /
    21 234 — un facteur 17 de compaction, dans le budget trois fois sur trois — et
    les trois ont ete jetees. Seule la marque manquait. Rejoue trois fois hors ligne
    sur la meme entree, la marque etait presente une fois sur trois : le portillon
    n'est pas fiable, et il coutait la totalite du gain.

    La garantie est conservee : le resume rendu ENONCE la mission. On ne la
    fabrique pas, on la reprend du bloc `## User` que la passe a deja sous la main.
    Sans bloc `## User`, il n'y a pas de mission a perdre : le resume passe tel quel.
    """
    if len(summary) > ceiling:
        return ""
    if _states_the_mission(summary):
        return summary
    brief = " ".join(mission.splitlines()[1:]).strip()
    if not brief:
        return summary
    ouverture = f"{_MISSION_MARKER} : {brief[:300].rstrip()}"
    return f"{ouverture}\n\n{summary}"


def _units(note: str) -> list[str]:
    """The note as replaceable units: snippet blocks kept whole, prose per ``## ``."""
    units: list[str] = []
    for text, key in _split_into_blocks(note):
        if key is not None:
            units.append(text)
            continue
        units.extend(_split_prose(text))
    return units


def _split_prose(text: str) -> list[str]:
    """Cut a prose block on its own ``## `` headings - one heading, one unit."""
    parts: list[list[str]] = []
    for line in text.split("\n"):
        if line.startswith("## ") or not parts:
            parts.append([line])
        else:
            parts[-1].append(line)
    return ["\n".join(part) for part in parts]


def _candidates(units: list[str]) -> list[int]:
    """Indices of every summarisable prose unit — the ``## User`` blocks included.

    They used to be excluded outright, to stop the brief being lost (2026-08-21: an
    agent stopped mid-run to ask what it was supposed to deliver). But protecting the
    raw text means every user message piles up verbatim for the whole session. The
    guarantee moved instead to the OUTPUT: the briefing must carry a distilled
    ``Mission en cours :`` line, and a summary without one is rejected — see
    ``_states_the_mission``. Requiring the statement is checkable; hoarding the text is not."""
    return [i for i, unit in enumerate(units)
            if _is_prose(unit) and unit.strip() and not _is_stale_marker(unit)
            and not _is_harness_context(unit)]


def _is_harness_context(unit: str) -> bool:
    """Un bloc ``## Harnais @…`` (contexte_fige.empiler_note_de_contexte) : un changement de
    situation (worktree, cd, mémoire) écrit par le harnais, gardé intact à sa place — ni résumé,
    ni élagué. Le reformuler ferait perdre le contrat de worktree (récolte, branche de travail).
    Idem pour le bloc ``## Contexte archivé`` de ResetContext (context_reset.py) : résumé, il
    perdrait le chemin de l'archive, seul accès à l'ancienne note."""
    from .contexte_fige import ENTETE_NOTE_DE_CONTEXTE
    from .context_reset import ARCHIVE_HEADER
    return unit.lstrip().startswith((ENTETE_NOTE_DE_CONTEXTE, ARCHIVE_HEADER))


def _is_stale_marker(unit: str) -> bool:
    """Un marqueur de peremption vise un extrait VIVANT : le resumer le ferait disparaitre
    et l'extrait perime paraitrait valide. La passe mecanique (compact_snippets) le consomme
    avant ; il n'est jamais matiere a synthese."""
    return unit.lstrip().startswith("## snippet-stale:")


# Ce qui est HORS de portee de cette passe : le snippet VIVANT, dont le juge de
# `compact_judge` est seul maitre. Tout le reste est de la prose -- y compris les
# deux sortes de RECU que laisse un snippet disparu :
#   `## snippet-dropped:` le juge a decide que l'agent n'en avait plus besoin ;
#   `## snippet-stale:`   un Edit a rendu le contenu epingle faux.
# Aucun des deux ne porte plus de contenu : ils disent "ce fichier a ete vu,
# re-Snippet si besoin". C'est une phrase, pas un bloc a garder 88 fois.
_LIVE_SNIPPET_PREFIXES = ("## snippet:",)


def _is_prose(unit: str) -> bool:
    """Tout sauf un snippet VIVANT — les deux sortes de recu comprises.

    Le filtre testait le prefixe `## snippet`, ce qui excluait aussi
    `## snippet-dropped:` et `## snippet ERROR`. Or ces deux-la sont de la prose
    pour `_split_into_blocks` (la ligne tombe dans sa branche `## ` generique, qui
    ouvre un bloc `key=None`) : ni ce module ni `compact_judge`, qui ne traite que
    les blocs portant une cle de snippet, ne pouvaient les retirer. Une pierre
    tombale entrait donc dans la note pour n'en jamais ressortir.

    Mesure du 2026-08-23 sur l'agent f52cb5297f4f : 88 pierres tombales pour
    44 014 caracteres, soit 37,8 % d'une note de 116 549 — mediane 249 caracteres,
    maximum 7 394, la ou le code les decrivait comme une ligne courte. Plus le juge
    faisait bien son travail, plus la note grossissait de ses propres residus, et la
    passe ne voyait que 22 785 caracteres sur 116 549 : meme parfaite, elle ne
    pouvait pas ramener le prefixe sous la barre.

    Elles ne sont pas jetees aveuglement : elles deviennent matiere a compacter,
    et le resume garde ce qu'elles apprennent vraiment — quel fichier a ete vu et
    ecarte — sans les 90 caracteres de chemin absolu repetes 88 fois.
    """
    return not unit.lstrip().startswith(_LIVE_SNIPPET_PREFIXES)


def _states_the_mission(summary: str) -> bool:
    """Le resume enonce-t-il ce que l'agent doit livrer ?"""
    return _MISSION_MARKER.lower() in summary.lower()


def _is_mission(unit: str) -> bool:
    """A ``## User`` block: the brief, kept verbatim and never summarised."""
    return unit.lstrip().startswith("## User")


def prose_units(note: str) -> list[str]:
    """La prose qu'une passe de compaction peut REELLEMENT reduire.

    C'est le seul point de verite partage avec le declencheur
    (``compact_methodology``) : celui-ci ne doit PAS redecouper la note ni
    recopier les filtres, sinon les deux vues divergent au premier changement de
    format d'entete. Un declencheur qui compte autre chose que ce que la passe
    peut retirer arme des appels payants sur de la matiere intouchable — c'est
    exactement le defaut mesure sur ``cached_prefix_tokens``, dont 52 % est du
    prompt statique.

    Les blocs ``## User`` en sont exclus, alors que ``_candidates`` les inclut :
    la difference est voulue. La passe accepte de reformuler la mission, mais on
    refuse d'ARMER une passe payante sur un volume de brief — une note qui n'est
    que du brief n'a rien de compactable a offrir.
    """
    return [u for u in _units(note) if _is_prose(u) and not _is_mission(u) and u.strip()
            and not _is_harness_context(u)]


def live_snippet_units(note: str) -> list[str]:
    """Les snippets VIVANTS de la note — la matiere du juge, et de lui seul.

    Complementaire de ``prose_units`` : les pierres tombales
    (``## snippet-dropped:``, ``## snippet ERROR``, ``## snippet-stale:``) n'en
    font PAS partie, elles sont de la prose pour ce module (voir ``_is_prose``).
    """
    return [u for u in _units(note) if not _is_prose(u) and u.strip()]


def _mission(units: list[str]) -> str:
    """The first ``## User`` block, passed to the summariser as read-only context."""
    return next((u for u in units if _is_mission(u)), "")


def _worth_a_call(units: list[str], candidates: list[int]) -> bool:
    """True when the candidates hold enough material the summary does not cover.

    Folding the previous ``## compacted-history`` back in is deliberate — it keeps
    the note at a single synthesis block. But it also means the pass always has one
    fat candidate, so without this check it fires on every trigger even when the
    only new prose is a two-line turn header, and pays a full side-call to rewrite
    its own summary."""
    fresh = sum(len(units[i]) for i in candidates
                if not units[i].lstrip().startswith(SUMMARY_HEADER))
    return fresh >= _MIN_FRESH_PROSE_CHARS


def _rebuild(units: list[str], candidates: list[int], block: str) -> str:
    """Drop the candidates, put the synthesis where the first one stood."""
    dropped = set(candidates)
    first = candidates[0]
    kept = [block if i == first else unit
            for i, unit in enumerate(units) if i == first or i not in dropped]
    return "\n".join(kept)


def _stalled(attempts: list[str], ceiling: int) -> bool:
    """True quand une tentative de plus ne raccourcira plus rien.

    Un depassement de plafond est relance en disant de combien on depasse. Mais
    si la nouvelle reponse fait au moins 90 % de la precedente, le modele a
    montre son plancher : la troisieme tentative rendra la meme longueur et
    coutera un appel pour un resultat deja connu.

    La condition ``> ceiling`` est essentielle : un refus pour marque de mission
    absente n'a rien a voir avec la taille — il garde ses tentatives, et
    ``_salvage`` sait le rattraper.
    """
    return (len(attempts) >= 2 and len(attempts[-1]) > ceiling
            and len(attempts[-1]) >= 0.9 * len(attempts[-2]))


def _ask(old_prose: str, mission: str, config: dict | None,
         attempts: list[str] | None = None, ceiling: int = 0) -> tuple[str, dict]:
    """Run the side-call. Same wiring as the snippet judge, bigger answer budget.

    Returns the answer AND what the call cost (``in``/``out``/``cache_read``/
    ``cache_creation`` tokens). Without those, a refusal was undiagnosable: we
    could not tell an expensive retry loop from a cheap one, and the whole point
    of the retries is that the material is re-read from cache.

    ``mission`` is context, never material to rewrite: the summary has to stay
    oriented towards what the agent was actually asked to deliver.

    ``attempts`` holds the answers that came back over the ceiling. They are sent
    AFTER the cache breakpoint, so the material to compact — mission and note
    entries, the bulk of the call — is re-read from cache on every retry and only
    the failed attempt and the overshoot are new tokens.
    """
    from ..agent.providers import AssistantTurn
    from ..agent.stream_interceptor import get_streamer

    side_config = dict(config or {})
    # _depth guards against recursion: the compactor's own call must not trigger
    # a compaction of its own context.
    side_config["_depth"] = (config or {}).get("_depth", 0) + 1
    side_config["_context_state"] = None
    side_config["max_tokens"] = _answer_budget(ceiling, config)
    side_config["_call_label"] = _CALL_LABEL
    side_config.pop("_tool_choice", None)

    answer = ""
    usage = {"in_tokens": 0, "out_tokens": 0,
             "cache_read_tokens": 0, "cache_creation_tokens": 0}
    for event in get_streamer()(
        model=summary_model(config),
        system=_SYSTEM,
        messages=[{"role": "user", "content": [
            {
                "type": "text",
                "text": (
                    f"MISSION (read-only context, never rewrite or drop it)\n"
                    f"{mission.strip() or '(not recorded)'}\n\n"
                    f"NOTE ENTRIES\n{old_prose}"
                ),
                "cache_control": {"type": "ephemeral"},
            },
            *_retry_blocks(attempts or [], ceiling),
        ]}],
        tool_schemas=[],
        config=side_config,
    ):
        if isinstance(event, AssistantTurn):
            answer = event.text or ""
            for field in usage:
                usage[field] += getattr(event, field, 0) or 0
    return answer, usage


def _retry_blocks(attempts: list[str], ceiling: int) -> list[dict]:
    """Dire ce qui a ete rendu et de combien il faut encore couper.

    Placé APRÈS le point de césure du cache : ces quelques centaines de caractères
    sont les seuls tokens neufs d'une nouvelle tentative.
    """
    if not attempts:
        return []
    last = attempts[-1]
    trop = len(last) - ceiling
    if not _states_the_mission(last):
        return [{
            "type": "text",
            "text": (
                f"YOUR PREVIOUS ANSWER (attempt {len(attempts)}) DID NOT OPEN WITH THE "
                f"MISSION.\n\n{last}\n\n"
                f"Write it again. The FIRST line must be "
                f"`{_MISSION_MARKER} : <what the agent has been asked to deliver>`, one "
                f"sentence distilled from the `## User` entries. Keep the rest within "
                f"{ceiling} characters."
            ),
        }]
    return [{
        "type": "text",
        "text": (
            f"YOUR PREVIOUS ANSWER (attempt {len(attempts)}) WAS TOO LONG: "
            f"{len(last)} characters for a {ceiling} ceiling — {trop} over.\n\n"
            f"{last}\n\n"
            f"Compact it FURTHER. Cut at least {trop} more characters. Same test as "
            f"before: keep only what an agent needs to carry the task on without "
            f"asking anything back and without re-exploring a path already explored. "
            f"Everything else goes."
        ),
    }]


def _journal(config: dict | None, entries: int, summary_chars: int, removed: int,
             replaced: int = 0, usages: list[dict] | None = None,
             summary: str = "") -> None:
    """Record the attempt - refusals included.

    A refusal is as informative as a removal: it says the model could not make
    the history smaller, which is the signal for tuning the prompt.

    ``usages`` carries one token record per attempt, so the cost of a refused
    pass is readable instead of inferred: that is what says whether the retries
    really re-read the material from cache. ``trigger_prose_tokens`` and
    ``cached_prefix_tokens`` say WHY the pass was armed and what the old trigger
    would have seen — the two numbers cannot be recovered afterwards.
    """
    log_list = getattr((config or {}).get("_state"), "compaction_log", None)
    if log_list is None:
        return
    from .compact_methodology import CHARS_PER_TOKEN, cached_prefix_tokens
    log_list.append({
        "phase": "note_prose_compaction",
        "turn": getattr((config or {}).get("_state"), "turn_count", 0),
        "chars_removed": removed,
        "blocks_summarised": entries,
        # Sans la taille de l'ENTREE, un refus est indiagnosticable : on ne sait pas si
        # le modele a rate le plafond de peu ou de loin. Constate le 2026-08-23, ou 105
        # passes sur 106 ont ete refusees sans qu'on puisse dire pourquoi.
        "input_chars": replaced,
        "ceiling_chars": int(replaced * _MAX_SUMMARY_RATIO),
        "attempts": len(usages or []),
        "attempt_tokens": list(usages or []),
        "trigger_prose_tokens": int(replaced / CHARS_PER_TOKEN),
        "cached_prefix_tokens": cached_prefix_tokens(config),
        # Deux tests peuvent refuser une passe, et le journal ne disait pas lequel.
        # Mesure du 2026-08-23 : une passe rendait 6 192 caracteres pour un plafond
        # de 21 234 -- largement dans le budget -- et etait quand meme refusee, donc
        # par la marque de mission. Sans ces deux champs on ne pouvait pas le voir.
        "states_mission": _states_the_mission(summary),
        "summary_head": summary[:200],
        "summary_chars": summary_chars,
    })
