# [desc] Registers built-in tool definitions and executes tools with permission checks. [/desc]
"""Tool registration: builtins, plan mode, and side-effect plugin imports."""
from typing import Callable, Optional

from ..core.tool_registry import ToolDef, register_tool
from ..core.tool_registry import execute_tool as _registry_execute

from .schemas import TOOL_SCHEMAS
from .ops.file_ops import _read, _write, _edit
from .ops.shell_search import _is_safe_bash, _bash, bash_handler, _glob, _grep
from .ops.bash_bg import bash_output
from .ops.web_ops import _webfetch, _websearch
from .ops.notebook_diagnostics import _notebook_edit, _get_diagnostics
from .interaction import _ask_user_question, _sleeptimer
from .ops.diff_ops import _get_diff
from ..core.dossier_agent import resoudre
from ..context_manager.methodology import methodology_tool, snippet_tool


# Outil soumis à permission -> (paramètre décrit, libellé de la question, refus rendu).
_PERMISSIONS = {
    "Write": ("file_path", "Write to {}", "Denied: user rejected write operation"),
    "Edit": ("file_path", "Edit {}", "Denied: user rejected edit operation"),
    "Bash": ("command", "Bash: {}", "Denied: user rejected bash command"),
    "NotebookEdit": ("notebook_path", "Edit notebook {}", "Denied: user rejected notebook edit operation"),
}


def _refus_permission(name: str, inputs: dict, permission_mode: str,
                      ask_permission: Optional[Callable[[str], bool]]) -> str | None:
    """Le refus de l'utilisateur, ou None si l'appel peut passer.

    Paramètre requis absent (appel natif aux arguments vides, vu sur MiMo) : aucune question ;
    le garde du registre renvoie l'erreur explicite au modèle. Un `inputs["command"]` direct
    levait KeyError et tuait tout le process d'agent."""
    if name not in _PERMISSIONS or permission_mode == "accept-all" or not ask_permission:
        return None
    param, libelle, refus = _PERMISSIONS[name]
    valeur = inputs.get(param)
    if not valeur or (name == "Bash" and _is_safe_bash(valeur)):
        return None
    return None if ask_permission(libelle.format(valeur)) else refus


def _read_normalise(inputs: dict, cfg: dict) -> str:
    """Snippet speaks 1-indexed inclusive `ranges`, Read speaks 0-indexed offset+limit; the
    model mixes them. Convert what is exact arithmetic, refuse what would need a choice. Runs
    BEFORE the registry's unknown-parameter guard, which is what turned these into lost turns."""
    from .ops.read_params import normalize_read_params
    error, note = normalize_read_params(inputs)
    if error:
        return error
    result = _registry_execute("Read", inputs, cfg)
    if note and not result.startswith(("Error:", "__BOUZE_IMAGE__")):
        return f"{result}\n{note}"
    return result


def execute_tool(
    name: str,
    inputs: dict,
    permission_mode: str = "auto",
    ask_permission: Optional[Callable[[str], bool]] = None,
    config: dict = None,
) -> str:
    cfg = config or {}
    if name == "Read":
        return _read_normalise(inputs, cfg)
    refus = _refus_permission(name, inputs, permission_mode, ask_permission)
    if refus:
        return refus
    # Plan check disabled — WritePlan is advisory, not enforced.
    return _registry_execute(name, inputs, cfg)


def _coerce_recap(recap: object) -> object:
    """Certains modèles (Opus inclus) sérialisent l'objet `recap` en CHAÎNE JSON au lieu de
    passer un objet. On le reparse en dict — sinon un récap POURTANT complet est lu comme
    « tous les champs manquants » par le gate (refus en boucle), puis jeté à la persistance
    (`state.recap` reste None car non-dict) → tous les GET /recap sortent vides."""
    if isinstance(recap, str):
        import json
        try:
            parsed = json.loads(recap)
        except (ValueError, TypeError):
            return recap
        if isinstance(parsed, dict):
            return parsed
    return recap


def _coerce_liste(value: object) -> object:
    """Tolère une liste sérialisée en CHAÎNE JSON (même travers que `_coerce_recap`).

    Un modèle qui renvoie `"[]"` au lieu de `[]` déclare bel et bien « rien ne
    reste » : le transformer en refus bouclerait jusqu'au cap des reprises.
    Une chaîne illisible est rendue TELLE QUELLE pour que la porte la refuse.
    """
    if not isinstance(value, str):
        return value
    texte = value.strip()
    if not texte:
        return value
    import json
    try:
        decode = json.loads(texte)
    except ValueError:
        return value
    return decode if isinstance(decode, list) else value


def _ouvrir_micros(taches_restantes: list, session_id: str = "") -> None:
    """Chaque point resté ouvert devient une micro-tâche en BROUILLON, rattachée par défaut
    au chantier du ticket courant (règle utilisateur du 2026-09-08).

    Import LOCAL : le TUI ne doit pas payer l'import de web_v2 au démarrage. Et l'échec est
    AVALÉ — la déclaration écrite dans le JSON de session reste la source de vérité, un pont
    cassé (base absente, schéma en retard) ne doit JAMAIS refuser une clôture d'agent.
    """
    if not taches_restantes:
        return
    import os
    try:
        from bouzecode.web_v2.services.work import cloture_micros
        cloture_micros.ouvrir_micros_de_cloture(
            taches_restantes,
            ticket_id=os.environ.get("BOUZECODE_TICKET_ID", ""),
            slug=os.environ.get("BOUZECODE_TICKET_SLUG", ""),
            #  La session est dans `config` (`loop.py` l'y met), pas dans l'environnement :
            #  c'est le seul identifiant qui permette de retrouver la VAGUE de lignes
            #  fabriquée par une clôture, et donc de l'auditer ou de la purger en bloc.
            session_id=session_id,
        )
    except Exception:
        #  Avalé, mais JAMAIS muet : distinguer « aucun reste déclaré » de « pont cassé » a
        #  coûté trois scripts de mesure. La trace dit laquelle des deux on regarde.
        import logging
        logging.getLogger(__name__).warning(
            "pont de clôture : les taches_restantes n'ont pas ouvert de micro-tâche",
            exc_info=True,
        )


def _lignes_absentes(answer: str, items: object) -> list[str]:
    """Points d'une liste de tâches qui ne figurent pas déjà dans le texte du rapport."""
    if not isinstance(items, list):
        return []
    lignes = []
    for item in items:
        if isinstance(item, dict):
            titre = str(item.get("titre") or "").strip()
            corps = str(item.get("corps") or "").strip()
            texte = f"{titre} — {corps}" if titre and corps else (titre or corps)
        else:
            titre = texte = str(item).strip()
        if texte and (titre or texte) not in answer:
            lignes.append(f"- {texte}")
    return lignes


def _reste_a_faire_dans_le_rapport(answer: str, taches_restantes: object,
                                   taches_terminees: object = None) -> str:
    """Sous-agent : ses tâches terminées et restantes n'alimentent pas le Bureau (ni création,
    ni marquage), elles doivent donc figurer dans le texte que lit le parent. Chaque point
    absent du rapport y est ajouté."""
    faites = _lignes_absentes(answer, taches_terminees)
    reste = _lignes_absentes(answer, taches_restantes)
    sortie = answer.rstrip()
    if faites:
        sortie += ("\n\n## Tâches terminées (sous-agent : rapport au parent)\n"
                   + "\n".join(faites))
    if reste:
        sortie += ("\n\n## Reste à faire (sous-agent : à consolider par le parent)\n"
                   + "\n".join(reste))
    return sortie if (faites or reste) else answer


#  Les suites déclarées par une FinalAnswer que la boucle n'a pas encore acceptée.
#  Essai 3 (racine 6bafe9cd, 2026-09-24) : 3 des 7 clôtures « livrées » ont ensuite été
#  refusées par la boucle (FinalAnswer dans le même lot qu'un Bash) ; chacune avait déjà
#  ouvert ses suites — « Étendre le scraping » en 3 exemplaires, Q25/Q26 en 2.
_MICROS_EN_ATTENTE = "_micros_de_cloture_en_attente"


def ouvrir_micros_de_cloture_acceptee(config: dict) -> None:
    """La clôture est ACCEPTÉE (la session se ferme) : ses suites deviennent des tâches."""
    en_attente = config.pop(_MICROS_EN_ATTENTE, None)
    if en_attente:
        _ouvrir_micros(*en_attente)


def oublier_micros_de_cloture_refusee(config: dict) -> None:
    """La boucle a refusé la clôture : la prochaine FinalAnswer redéclarera ses suites."""
    config.pop(_MICROS_EN_ATTENTE, None)


def _refus_de_cloture(answer: str, config: dict, recap, taches_terminees, taches_restantes,
                      parcours_verifies) -> str:
    """Le message de refus des portes de clôture, "" si la clôture passe.

    Portes gratuites d'abord (récap, déclarations, parcours prouvés, validateur léger),
    puis la relecture indépendante (opt-in `close_review`), qui coûte une session entière.

    Enfants actifs EN PREMIER : prouver des parcours sur un travail que l'enfant va encore
    modifier (essai 3 : il s'est intégré par-dessus la racine après sa clôture) ne vaut rien,
    et ce refus-là ne consomme pas les reprises de la porte des parcours."""
    from ..multi_agent.enfants import refus_de_cloture as refus_enfants
    refus = refus_enfants(config)
    if refus:
        return refus
    from ..agent.close_validator import validate_close
    accepted, feedback = validate_close(
        answer, config, recap, taches_terminees, taches_restantes, parcours_verifies
    )
    if not accepted:
        #  Session c4fe6829 (2026-10-07) : seul `taches_restantes` manquait, la réponse
        #  entière a été retapée. Dire qu'on peut ne corriger QUE les champs.
        return (f"CLÔTURE REFUSÉE par le validateur — il manque : {feedback}\n"
                "Termine ce qui manque (coche ta todolist) puis rappelle FinalAnswer. Si ton "
                "texte reste juste et qu'il ne manquait qu'un champ (une tâche, une décision, "
                "le récap…), rappelle FinalAnswer SANS `answer` (omets-le) avec "
                "les champs corrigés : le harnais reprend le texte de cette tentative. Ne "
                "retape `answer` que si son contenu doit changer.")
    from ..agent.close_review import relire
    accepted, relecture = relire(answer, config, parcours_verifies)
    if not accepted:
        return ("CLÔTURE REFUSÉE par le relecteur indépendant — il a testé comme un "
                f"utilisateur et rend KO :\n{relecture}\n"
                "Corrige ces défauts, rejoue les parcours concernés, puis rappelle FinalAnswer.")
    return ""


def _avouer_parcours_non_prouves(answer: str, config: dict) -> str:
    """Cap des reprises atteint : la clôture passe, mais l'utilisateur doit le LIRE. Une
    clôture acceptée peut aussi porter un signalement (recette forcée à `exit 0`…)."""
    non_prouves = config.get("_parcours_non_prouves")
    signales = config.get("_parcours_signalements")
    if non_prouves:
        answer += ("\n\n⚠️ Parcours utilisateur NON prouvés (clôture forcée après refus) :\n- "
                   + "\n- ".join(non_prouves))
    if signales:
        answer += "\n\nℹ️ À savoir sur les preuves des parcours :\n- " + "\n- ".join(signales)
    return answer


def _final_answer(
    answer: str,
    config: dict,
    recap: object = None,
    taches_terminees: object = None,
    taches_restantes: object = None,
    parcours_verifies: object = None,
    related_files: object = None,
) -> str:
    """Explicit close signal (ends_turn=True): store and echo the final answer.
    On native models a one-call validator checks the Methodology todolist first
    and can REFUSE the close (loop continues via _final_answer_refused). When the
    profile sets require_recap the same gate also enforces a complete `recap`
    object (symptoms/explanation/tests/changes) before accepting the close."""
    if not answer.strip():
        config["_final_answer_refused"] = True
        return "Error: 'answer' is empty — provide the complete final answer."
    recap = _coerce_recap(recap)   # tolère un recap sérialisé en chaîne JSON (cf. _coerce_recap)
    taches_terminees = _coerce_liste(taches_terminees)
    taches_restantes = _coerce_liste(taches_restantes)
    parcours_verifies = _coerce_liste(parcours_verifies)
    refus = _refus_de_cloture(answer, config, recap, taches_terminees, taches_restantes,
                              parcours_verifies)
    if refus:
        config["_final_answer_refused"] = True
        return refus
    answer = _avouer_parcours_non_prouves(answer, config)
    from ..multi_agent.profondeur import profondeur_courante
    est_sous_agent = profondeur_courante(config) > 0
    if est_sous_agent:
        answer = _reste_a_faire_dans_le_rapport(answer, taches_restantes, taches_terminees)
    from ..multi_agent.enfants import avouer_enfants_actifs
    answer = avouer_enfants_actifs(answer, config)
    config["_final_answer"] = answer
    # Persiste la reponse livree DANS la note : une session qui continue apres un
    # FinalAnswer (TUI/web relance par un nouveau message user) garde ainsi le
    # referent de ce que l'utilisateur repond ensuite. Sans ca, le "Ok pour 1,
    # pour 2 disons 2 minutes" est note (append_user_msg) mais les propositions
    # 1/2/3/4 auxquelles il repond sont perdues (cas mesure : session
    # session_081618_e59985ab, 46 tours, propositions du tour 23 introuvables).
    from ..context_manager.methodology import append_final_answer_to_methodology
    append_final_answer_to_methodology(config.get("_context_state"), answer)
    state = config.get("_state")
    if state is not None:
        state.final_answer = answer
        from ..multi_agent.enfants import cloture_en_attente
        state.cloture_en_attente_des_enfants = cloture_en_attente(config)
        # Récap persisté UNIQUEMENT pour les runs de LIVRAISON (work). Un validateur partage le
        # prompt du codeur et remplit parfois un `recap`, mais il rend un VERDICT : son « récap »
        # ne doit ni afficher de pastille ni polluer la vue consolidée du manager.
        import os
        if os.environ.get("BOUZECODE_RUN_KIND", "work") == "work":
            if isinstance(recap, dict):
                state.recap = recap
            #  Livrables consultables par l'humain (rapport .html, .pptx…) : chemins absolus.
            from ..agent.related_files import normaliser_related_files
            fichiers = normaliser_related_files(related_files)
            if fichiers:
                state.related_files = fichiers
            #  Les deux déclarations sont persistées TELLES QUE DÉCLARÉES, et le
            #  drapeau dit qu'elles l'ont ÉTÉ : une clôture antérieure au champ
            #  s'affiche « non déclaré », jamais « rien laissé ».
            if isinstance(taches_terminees, list):
                state.taches_terminees = taches_terminees
                state.taches_declarees = True
            if isinstance(taches_restantes, list):
                state.taches_restantes = taches_restantes
                state.taches_declarees = True
                #  DIFFÉRÉ : la boucle peut encore refuser cette clôture (outil du même lot
                #  jamais lu, cf. `close_guard`). Les suites ne s'ouvrent qu'à l'acceptation.
                #  SOUS-AGENT : jamais de tâche au Bureau (des centaines de lignes de « reste »
                #  le polluaient). Son reste est dans le rapport lu par le parent, qui
                #  consolide lui-même ce qui mérite une tâche.
                if not est_sous_agent:
                    config[_MICROS_EN_ATTENTE] = (taches_restantes,
                                                  str(config.get("_session_id") or ""))
            if config.get("_recap_missing"):
                state.recap_missing = True
    return f"Session closing — final answer delivered:\n{answer}"


def _register_builtins() -> None:
    _schemas = {s["name"]: s for s in TOOL_SCHEMAS}

    _tool_defs = [
        ToolDef(
            name="Read",
            schema=_schemas["Read"],
            func=lambda p, c: _read(**p),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="Write",
            schema=_schemas["Write"],
            func=lambda p, c: _write(**p),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="Edit",
            schema=_schemas["Edit"],
            func=lambda p, c: _edit(**p),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="Bash",
            schema=_schemas["Bash"],
            func=lambda p, c: bash_handler(p, c),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="BashOutput",
            schema=_schemas["BashOutput"],
            func=lambda p, c: bash_output(p["bash_id"], p.get("kill", False),
                                          p.get("wait_s", 0), p.get("until_exit", False),
                                          (c or {}).get("_cancel_peek")),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="Glob",
            schema=_schemas["Glob"],
            func=lambda p, c: _glob(p["pattern"], p.get("path"), p.get("ignore_gitignore", True), p.get("include_patterns")),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="Grep",
            schema=_schemas["Grep"],
            func=lambda p, c: _grep(
                p["pattern"], p.get("path"), p.get("glob"),
                p.get("output_mode", "content"),
                p.get("case_insensitive", False),
                p.get("context", 0),
                p.get("ignore_gitignore", True),
                p.get("include_patterns"),
            ),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="WebFetch",
            schema=_schemas["WebFetch"],
            func=lambda p, c: _webfetch(p["url"], p.get("prompt")),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="WebSearch",
            schema=_schemas["WebSearch"],
            func=lambda p, c: _websearch(p["query"]),
            read_only=True,
            # NOT concurrent_safe: firing several WebSearch in parallel from one
            # batch hits DuckDuckGo from the same (proxy) IP simultaneously and
            # trips its anti-bot "anomaly" page (0 results). Serialising lets the
            # module-level throttle in _websearch space the requests out.
            concurrent_safe=False,
        ),
        ToolDef(
            name="NotebookEdit",
            schema=_schemas["NotebookEdit"],
            func=lambda p, c: _notebook_edit(
                resoudre(p["notebook_path"]),
                p["new_source"],
                p.get("cell_id"),
                p.get("cell_type"),
                p.get("edit_mode", "replace"),
            ),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="GetDiagnostics",
            schema=_schemas["GetDiagnostics"],
            func=lambda p, c: _get_diagnostics(
                resoudre(p["file_path"]),
                p.get("language"),
            ),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="AskUserQuestion",
            schema=_schemas["AskUserQuestion"],
            func=lambda p, c: _ask_user_question(
                p["question"],
                p.get("options"),
                p.get("allow_freetext", True),
                config=c,
            ),
            read_only=True,
            concurrent_safe=False,
        ),
        ToolDef(
            name="SleepTimer",
            schema=_schemas["SleepTimer"],
            func=lambda p, c: _sleeptimer(p["seconds"], c),
            read_only=False,
            concurrent_safe=True,
        ),
        ToolDef(
            name="Methodology",
            schema=_schemas["Methodology"],
            func=lambda p, c: methodology_tool(p, c),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="FinalAnswer",
            schema=_schemas["FinalAnswer"],
            #  Les DEUX champs de clôture obligatoires voyagent jusqu'au handler : les jeter
            #  faisait refuser toute clôture d'un profil `require_recap` (le validateur les
            #  voyait absents) et le reste-à-faire n'atteignait jamais le Bureau.
            func=lambda p, c: _final_answer(p.get("answer", ""), c, p.get("recap"),
                                            p.get("taches_terminees"),
                                            p.get("taches_restantes"),
                                            p.get("parcours_verifies"),
                                            p.get("related_files")),
            read_only=True,
            concurrent_safe=False,
            ends_turn=True,
            #  Son verdict dépend de l'état des enfants (autres process) : jamais mémorisé.
            etat_externe=True,
        ),
        ToolDef(
            name="Snippet",
            schema=_schemas["Snippet"],
            func=lambda p, c: snippet_tool(p, c),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="GetDiff",
            schema=_schemas["GetDiff"],
            func=lambda p, c: _get_diff(resoudre(p.get("file_path"))),
            read_only=True,
            concurrent_safe=True,
        ),
    ]
    for td in _tool_defs:
        register_tool(td)


_register_builtins()


# ── Environment on demand (worktree / venv / intégration demandés par l'agent) ──
# Import à effet de bord : le module s'enregistre lui-même (patron plan_mode / projects_tool).
from . import environment as _environment_tool  # noqa: F401

# Outils de pilotage du Bureau (ResteAFaire/Taches/Decisions/Flotte/LancerAgent).
# Contrairement a `environment`, ce module ne s'enregistre PAS a l'import : il faut
# appeler register() explicitement. Sans cet appel, le profil `bureau-assistant`
# nomme dans son prompt des outils absents du registry vivant
# (enabled_tools_for_profile croise le YAML avec `_registry`) : l'assistant du
# Bureau demarrait donc sans aucun de ses outils.
from . import bureau_tools as _bureau_tools  # noqa: F401

_bureau_tools.register()
#  Outils de l'assistant extraits de `bureau_tools` (deja trop long) : meme regle, ils sont
#  enregistres AVANT la passe de whitelist et seul un profil qui les declare les rallume.
from . import bureau_agenda as _bureau_agenda  # noqa: E402
from . import bureau_projets as _bureau_projets  # noqa: E402

_bureau_agenda.register()
_bureau_projets.register()
# Remontee non bloquante (always-on, cf. FRAMEWORK_ALWAYS_ON).
from . import signaler as _signaler  # noqa: E402

_signaler.register()
# TODO des chantiers du projet, lecture + classement pour tout agent (always-on).
from . import taches_projet as _taches_projet  # noqa: E402

_taches_projet.register()
# Nettoyage du contexte quand la tâche change (always-on, cf. FRAMEWORK_ALWAYS_ON).
from ..context_manager import context_reset as _context_reset  # noqa: E402

_context_reset.register()

# ── Project config tool ──────────────────────────────────────────────────────
from .ops.project_config import _load_project_config

_schemas_map = {s["name"]: s for s in TOOL_SCHEMAS}
register_tool(ToolDef(
    name="LoadProjectConfig",
    schema=_schemas_map["LoadProjectConfig"],
    func=lambda p, c: _load_project_config(resoudre(p["path"]), c, cd=bool(p.get("cd"))),
    read_only=False,
    concurrent_safe=False,
    # Le briefing d'un projet (ses skills, ses outils) est exactement le genre de
    # résultat qu'on veut figer : sans ça il meurt au tour suivant et l'agent doit
    # le racheter — ou pire, travaille sans savoir de quoi il dispose.
    snippetable=True,
    snippet_key="tool_id",
))


# ── ImageQuestion : regarder une image par un appel annexe (rapport reduction_tokens §4.3) ──
from .image_question import SCHEMA as _IMAGE_QUESTION_SCHEMA, image_question as _image_question

register_tool(ToolDef(
    name="ImageQuestion",
    schema=_IMAGE_QUESTION_SCHEMA,
    func=_image_question,
    read_only=True,
    concurrent_safe=True,
))


# ── Plan mode tools ──────────────────────────────────────────────────────────
from .plan_mode import _enter_plan_mode, _exit_plan_mode, _write_plan, _PLAN_MODE_SCHEMAS

register_tool(ToolDef(
    name="EnterPlanMode",
    schema=_PLAN_MODE_SCHEMAS[0],
    func=_enter_plan_mode,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="WritePlan",
    schema=_PLAN_MODE_SCHEMAS[1],
    func=_write_plan,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="ExitPlanMode",
    schema=_PLAN_MODE_SCHEMAS[2],
    func=_exit_plan_mode,
    read_only=False,
    concurrent_safe=False,
))


# ── Side-effect imports: register tools from other packages ──────────────────
from ..multi_agent import tools as _multiagent_tools  # noqa: F401
from .skill import tools as _skill_tools  # noqa: F401
from .task import tools as _task_tools  # noqa: F401

from ..checkpoint.hooks import install_hooks as _install_checkpoint_hooks
_install_checkpoint_hooks()

from ..context_manager.stale_hooks import install_stale_hooks as _install_stale_hooks
_install_stale_hooks()

from .folder_desc import tools as _folder_desc_tools  # noqa: F401

# Code navigation (FindCode, Tree): deterministic index, no LLM. Registered BEFORE the
# whitelist pass below; they survive it through FRAMEWORK_ALWAYS_ON.
from .findcode import tools as _findcode_tools  # noqa: F401

# ── RunPythonTest tool ───────────────────────────────────────────────────────

from .ops.test_runner import run_python_test as _run_python_test
from .ops.runner_guards import DEFAULT_PARALLEL

_schemas_map2 = {s["name"]: s for s in TOOL_SCHEMAS}


def _progression_sous_agent(config):
    """Progress callback for a TUI sub-agent: routes the pytest progress to its own
    conversation (FicheAgent.progression) instead of the shared process stderr,
    which the terminal shows in the MAIN agent's view. None for the main agent: its
    progress takes the spinner's live line (ops/progression_terminal.py)."""
    config = config or {}
    registre, moi = config.get("_tui_agents"), config.get("_tui_moi")
    if registre is None or not moi:
        return None
    return lambda texte: registre.changer(moi, progression=texte)


register_tool(ToolDef(
    name="RunPythonTest",
    schema=_schemas_map2["RunPythonTest"],
    func=lambda p, c: _run_python_test(
        progression=_progression_sous_agent(c),
        targets=p.get("targets"),
        parallel=p.get("parallel", DEFAULT_PARALLEL),
        marker=p.get("marker"),
        keyword=p.get("keyword"),
        timeout=p.get("timeout", 300),
        extra_args=p.get("extra_args"),
        no_sync=p.get("no_sync", False),
        testmon=p.get("testmon", False),
        full=p.get("full", False),  # hors schéma public : refusé hors nightly (runner_guards)
        show=p.get("show"),
        wait=p.get("wait", True),
    ),
    read_only=True,
    concurrent_safe=True,
))


def _test_status(p, c):
    from ..testd.rendu import statut_job
    return statut_job(p["job_id"], p.get("wait_s", 0), p.get("cancel", False),
                       (c or {}).get("_cancel_peek"))


#  Va par paire avec RunPythonTest(wait=false) : sans lui, le job_id rendu serait inutilisable.
register_tool(ToolDef(
    name="TestStatus",
    schema=_schemas_map2["TestStatus"],
    func=_test_status,
    read_only=True,
    concurrent_safe=True,
))

# ── AddProject tool (web_v2 project registry) ────────────────────────────────
# Registers a project into ~/.bouzecode/web_v2/projects.json so the model can
# add a project the same way the manual UI form does. Side-effect import.
from .projects_tool import tools as _projects_tool  # noqa: F401

# ── Plugin tools (pip packages from Artifactory) ─────────────────────────────
# Enabled plugins register their TOOL_DEFS here. Like other optional tools they
# are then gated by the whitelist below and re-enabled per-session via the
# agent profile's `requires_plugins` / `tools`.
from ..plugin.loader import register_plugin_tools as _register_plugin_tools
from ..plugin.loader import register_plugin_hooks as _register_plugin_hooks

# Skip plugin loading when BOUZECODE_NO_PLUGINS is set (CI/tests without
# Artifactory access, or when a plugin's native deps are broken in the env).
import os as _os

_plugin_count = 0 if _os.environ.get("BOUZECODE_NO_PLUGINS") else _register_plugin_tools()
if _plugin_count:
    print(f"[plugin] registered {_plugin_count} tool(s) from installed plugins")
# Plugins also contribute named hooks (HOOK_DEFS) into the pipeline catalog, but
# their registration is DEFERRED (loaded lazily by the pipeline catalog on first
# lookup, at agent startup). Calling it here — during `tools/__init__` import —
# pulls in `agent.hooks.pipeline` → `agent.__init__` → `loop` → `dag` →
# `..tools` while `tools` is still initialising, a circular import that crashes
# the agent subprocess. See pipeline._ensure_builtin.
_ = _register_plugin_hooks  # kept importable; invoked lazily from the pipeline

# ── Default enabled tools (whitelist) ─────────────────────────────────────────
# Only these tools are sent to the model. All others are disabled at import time.
# Re-enable at runtime via enable_tool() or config["extra_tools"].
from ..core.tool_registry import disable_tool, _registry, FRAMEWORK_ALWAYS_ON

# Work tools enabled by default for a plain agent (no profile whitelist).
# BashOutput pairs with Bash(background=true): without it an agent that launches a
# background process (e.g. a dev server) is blind to its stdout — it cannot read the
# boot output/port and ends up killing & restarting servers to compensate.
# RunPythonTest is prescribed by the `default` prose ("Lance-les via RunPythonTest")
# and by the Bash schema itself; leaving it disabled made the harness forbid what it
# prescribes — 94 measured refusals for a tool the prompt named in 29 % of sessions.
# AddProject/DismissProject vont par paire : ils ne font que transcrire la réponse de
# l'utilisateur à « ce dossier est-il un projet ? ». N'en exposer qu'un laisserait le
# « non » sans destination, et la question reviendrait à chaque session.
_DEFAULT_WORK_TOOLS = {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "BashOutput",
                       "RunPythonTest", "TestStatus", "AddProject", "DismissProject", "WebFetch", "WebSearch",
                       # Sans lui dans la whitelist, l'outil est `disable_tool()` à l'import et
                       # n'est JAMAIS envoyé au modèle : un agent ne pourrait plus demander son
                       # worktree, alors que c'est désormais la seule façon d'en obtenir un.
                       "Environment",
                       #  Les outils Microsoft Graph (Mails, Teams, Canaux, Brouillon, Creneau,
                       #  Reunion) ne sont PAS ici : 3 050 tokens par appel pour 0 appel mesuré
                       #  sur 18 sessions d'agents de code (audit du 2026-09-24). Ils restent
                       #  enregistrés et le profil `bureau-assistant` les DÉCLARE dans son
                       #  allowlist : `enabled_tools_for_profile` / `apply_profile_tools` les
                       #  lui rallument. Un autre profil qui en a besoin les déclare de même.
                       #  Délégation. Le noyau ORDONNE à tout agent de décomposer sa mission et
                       #  de déléguer via `Agent(...)`, mais sans ces noms ici l'outil est
                       #  `disable_tool()` à l'import et AUCUN profil de travail ne le récupère
                       #  (`default.yaml` porte `tools: []`, `coder.yaml` une whitelist sans
                       #  `Agent`, et `config["extra_tools"]` n'est utilisé par aucun runner) :
                       #  le prompt promettait un outil absent du schéma — mesuré le 2026-09-23
                       #  sur un agent `default` lancé par la web UI, qui ne pouvait pas déléguer.
                       #  ListAgentTypes va par paire avec Agent (choisir la typologie avant de
                       #  dispatcher) ; ListAgentTasks / CheckAgentResult sont le SEUL moyen de
                       #  récupérer un enfant lancé en `wait=false` — sans eux, déléguer sans
                       #  bloquer perdrait le résultat, donc personne ne paralléliserait.
                       "Agent", "ListAgentTypes", "ListAgentTasks", "CheckAgentResult",
                       #  MessageAgent répond à un enfant bloqué sur une question ; Fleet liste la
                       #  flotte. Sans eux, le profil `default` (qui porte la prose de délégation)
                       #  lancerait des enfants qu'il ne saurait ni débloquer ni situer.
                       "MessageAgent", "Fleet"}
# Sent to the model by default = framework (always-on) + default work tools.
_DEFAULT_ENABLED = set(FRAMEWORK_ALWAYS_ON) | _DEFAULT_WORK_TOOLS

for _tool_name in list(_registry.keys()):
    if _tool_name not in _DEFAULT_ENABLED:
        disable_tool(_tool_name)

#  La TODO (TachesProjet) est a l'agent PRINCIPAL du ticket : un sous-agent ne l'a pas.
from .taches_projet import est_sous_agent as _est_sous_agent  # noqa: E402

if _est_sous_agent() and "TachesProjet" in _registry:
    disable_tool("TachesProjet")


def enabled_tools_for_profile(profile_name: str) -> set:
    """Return the tool names a `--profile <profile_name>` agent can call.

    Single source of truth for the profile whitelist, shared by `apply_profile_tools`
    (which enforces it on the live registry) and by the prompt/registry conformity
    test (which checks that nothing in that agent's prompt names a tool outside it).
    A profile with an empty `tools:` list means "no restriction" — whatever the
    registry currently has enabled, including tools switched on after the import-time
    whitelist (chrome-devtools bootstrap)."""
    from ..core.tool_registry import is_enabled
    from ..profiles import resolve_agent_profile

    profile = resolve_agent_profile(profile_name)
    declared = set(profile.tools) if profile and profile.tools else None
    if declared is None:
        noms = {name for name in _registry if is_enabled(name)}
    else:
        noms = {name for name in _registry if name in FRAMEWORK_ALWAYS_ON or name in declared}
    #  Sous-agent : pas de TODO, il rend compte a son parent (agent principal du ticket).
    #  Decide a l'appel (pas seulement a l'import) : c'est la lignee de l'agent qui compte.
    if _est_sous_agent():
        noms.discard("TachesProjet")
    elif "TachesProjet" in _registry:
        noms.add("TachesProjet")
    return noms


def tools_offered_to_profile(profile_name: str) -> set:
    """Ce que le modèle de ce profil VOIT réellement : `enabled_tools_for_profile` moins les
    outils `web_seulement` (Fleet, MessageAgent) quand il n'y a pas de flotte à piloter (ni
    web, ni TUI en process) — exactement le filtre de `get_tool_schemas`. Les outils restent
    ACTIVÉS (un TUI qui lance ses sous-agents les rend visibles sans ré-appliquer le profil) :
    seul ce qui est proposé change, et c'est ce que le prompt ne doit pas dépasser."""
    from ..core.tool_registry import flotte_disponible
    flotte = flotte_disponible()
    return {name for name in enabled_tools_for_profile(profile_name)
            if flotte or not _registry[name].web_seulement}

# ── chrome-devtools MCP (opt-in via --enable-chrome-devtools) ─────────────────
# Registered AFTER the whitelist so its enable_tool() calls survive the global
# disable pass above. No-op unless BOUZECODE_ENABLE_CHROME_DEVTOOLS=1.
from ..chrome_devtools.launcher import register_chrome_devtools_tools as _register_cdt
from ..chrome_devtools.launcher import register_bootstrap_tools as _register_cdt_bootstrap
# Always-on Enable/DisableChromeDevtools bootstrap tools (lazy activation on demand),
# registered after the whitelist so their enable_tool() calls survive the disable pass.
_register_cdt_bootstrap()
try:
    _register_cdt()
except Exception as _cdt_err:  # noqa: BLE001
    print(f"[chrome-devtools] registration skipped: {_cdt_err}")

#  État « par défaut » figé APRÈS chrome-devtools : `/agent` y revient au lieu de tout rallumer.
from ..core.tool_registry import figer_desactives_par_defaut as _figer  # noqa: E402
_figer()
