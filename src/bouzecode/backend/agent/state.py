# [desc] Dataclass definitions for agent state, tool events, turn metrics, and control signals. [/desc]
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass

from ..context_manager import ContextState


@dataclass
class AgentState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    turn_count: int = 0
    user_loop_count: int = 0
    total_tool_calls: int = 0
    meta_only_nudges: int = 0
    timing_entries: list = field(default_factory=list)
    conversation_start: float = 0.0
    compaction_log: list = field(default_factory=list)
    distinct_base: int = 0
    context_state: ContextState = field(default_factory=ContextState)
    notes_timeline: list = field(default_factory=list)
    last_api_payload: list = field(default_factory=list)
    thinking_log: list = field(default_factory=list)
    system_prompt: str = ""
    bouzecode_commit: str = ""
    bouzecode_version: str = ""
    # Commit chargé par le process au démarrage (≠ bouzecode_commit, HEAD relu à chaque run).
    bouzecode_boot_commit: str = ""
    # Code successif d'une session reprise : [{tour, version, commit, boot_commit, branche}].
    versions_successives: list = field(default_factory=list)
    profile: str = ""  # profil effectif du run (--profile, sinon classification de tâche)
    run_kind: str = ""  # rôle du run : work | validation | merge (deux runs `coder` ≠ métier)
    final_answer: str = ""  # set by the FinalAnswer tool (explicit close signal)
    close_reason: str = ""  # telemetry: which branch closed the session
    close_detail: str = ""  # death cause detail (e.g. the 400 body) persisted for crash reporting
    recap: dict | None = None  # structured recap object (symptoms/explanation/tests/changes) set by FinalAnswer
    recap_missing: bool = False  # True when the recap gate was bypassed after the retry cap (never brick a session)
    taches_terminees: list = field(default_factory=list)  # declared at close by FinalAnswer: what is DONE (one line per task)
    taches_restantes: list = field(default_factory=list)  # declared at close: what REMAINS, each {macro, texte, decision?} — feeds the TO-DO page
    taches_declarees: bool = False  # True once the agent actually declared both lists (an older close shows « non déclaré »)
    related_files: list = field(default_factory=list)  # declared at close: deliverables for the human, each {path (absolute), label, kind}
    cloture_en_attente_des_enfants: bool | None = None  # at the last accepted close: waiting on active children (manager) — the server only wakes such agents; None = close predating the field
    artifacts: list = field(default_factory=list)  # plugin artifact store (e.g. PBI store_pbi_model); wired into config in loop.py
    # Repli collant (cf. repli_collant.py) : {principal, repli, depuis_tour, allegements} une fois
    # qu'un refus a été servi par une marche de repli (`repli` = cette marche) ; vide = chaque
    # tour part sur le principal.
    repli_collant: dict = field(default_factory=dict)
    deferred_result: dict | None = None  # verdict des vérifications différées, arrivé APRÈS la clôture (TUI ; côté web le runner l'écrit dans la session)

    def repartir_de_zero(self) -> None:
        """Nouvelle session sur le MÊME objet (`/clear`) : chaque champ reprend sa valeur neuve.

        Générique exprès : `/clear` énumérait les champs à vider et n'en connaissait aucun
        de clôture — 001c222b et 6dc8170b (poste Windows) ont été enregistrées avec le
        `close_reason`/`final_answer` de la session d'avant sans jamais s'être closes. Un
        champ ajouté demain est remis à zéro sans qu'on y pense. Les listes et la note sont
        vidées EN PLACE : la boucle et la config en tiennent des références.

        `context_state` suit la même règle, champ par champ (2026-10-07 : le contexte de session
        figé et ses notes « [harnais] » survivaient au `/clear`, la session suivante les
        renvoyait)."""
        _remettre_a_neuf(self, AgentState())


def _remettre_a_neuf(objet, neuf) -> None:
    """Chaque champ de dataclass de `objet` reprend la valeur de `neuf` : listes et dicts vidés
    en place quand la valeur neuve est du même type (un `recap` posé redevient None, pas {}),
    dataclass imbriquée traitée de même (récursion), le reste réaffecté."""
    for f in fields(objet):
        courant, valeur_neuve = getattr(objet, f.name), getattr(neuf, f.name)
        if isinstance(courant, (list, dict)) and type(valeur_neuve) is type(courant):
            courant.clear()
        elif is_dataclass(courant) and not isinstance(courant, type):
            _remettre_a_neuf(courant, valeur_neuve)
        else:
            setattr(objet, f.name, valeur_neuve)


@dataclass
class ToolStart:
    name: str
    inputs: dict
    tool_id: str = ""


@dataclass
class ToolEnd:
    name: str
    result: str
    permitted: bool = True
    duration: float = 0.0
    tool_id: str = ""
    inputs: dict = field(default_factory=dict)


@dataclass
class TurnDone:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    # Compte absent de l'usage renvoyé par l'API (flux coupé avant) : valeur estimée.
    input_estimated: bool = False
    output_estimated: bool = False



@dataclass
class PermissionRequest:
    description: str
    granted: bool = False


@dataclass
class CheckpointReady:
    message_count: int
