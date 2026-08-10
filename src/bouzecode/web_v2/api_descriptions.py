# [desc] Descriptions écrites à la main des endpoints /api/, consommées par GET /api/schema. [/desc]
"""Surcouche de descriptions du schéma d'API, extraite d'`app.py` (seuil ~200 lignes).

Indexée par la clé CANONIQUE « <MÉTHODE> <règle Flask sans préfixe de convertisseur> »,
la même que produit `app.schema_key`. On n'en garde une entrée que quand elle dit plus
que le docstring de la vue ; sinon le docstring suffit. Deux gardes (tests/test_schema_coverage.py)
rendent la dérive impossible en silence : une entrée dont la route n'existe plus est une
erreur, et une route /api/ sans description l'est aussi.
"""
from __future__ import annotations

ENDPOINT_DESCRIPTIONS = {
    "GET /api/projects": "projets ouverts (un par path/worktree) + compteurs (agents en cours/en attente, tickets à relire, validations KO)",
    "GET /api/projects/logical": "projets regroupés par dépôt git (worktrees pliés sous un projet logique) + compteurs agrégés",
    "POST /api/projects": "{name, path, description?} — ouvrir un projet (description optionnelle, <=200 car.)",
    "PATCH /api/projects/<slug>": "{description} — éditer la description d'un projet (persistée dans projects.json)",
    "DELETE /api/projects/<slug>": "retirer un projet de la liste des projets ouverts (projects.json); n'efface rien sur le disque. 404 si slug inconnu.",
    "GET /api/projects/<slug>/agents": "agents web du projet avec statut live",
    "GET /api/projects/<slug>/tickets": "liste light des tickets (id, title, status, done, created_at, typology, runs summary, comments_count, liveness_state). ?full=1 pour le shape complet legacy, ?include_archived=1 pour inclure les archivés.",
    "GET /api/tickets/<slug>/<ticket_id>": "détail complet d'un ticket (prompt, comments, runs détaillés) + status dérivé. 404 si projet ou ticket inconnu.",
    "POST /api/projects/<slug>/tickets": "{title, prompt, model?, typology?, isolation?, parent?, launch?, defer?} — crée le ticket et, sauf launch=false, LANCE l'agent. defer défaut true : la réponse (le ticket) part dès la création, worktree+spawn continuent en fond. 400 si title ou prompt vide.",
    "POST /api/tickets/<slug>/<ticket_id>/launch": "{model?, typology?, isolation?} — relance un agent de travail sur le ticket → {key: 'agent/<id>'}. isolation ≠ 'shared' re-provisionne un worktree pour ce même ticket et purge ses drapeaux terminaux. 503 si l'env API est KO.",
    "POST /api/tickets/<slug>/<ticket_id>/validate": "{model?} — spawne un agent validateur (profil coder) sur le diff du ticket ; son verdict final 'VERDICT: OK|KO' est porté par le run → {key: 'agent/<id>'}. Il n'y a plus de paramètre `kind` : une seule sorte de validation.",
    "POST /api/tickets/<slug>/<ticket_id>/comments": "{text, send?} — commenter; send=true relance l'agent avec le commentaire",
    "POST /api/tickets/<slug>/<ticket_id>/done": "sans corps (le body est ignoré) — BASCULE le drapeau `done` du ticket → {done: <nouvelle valeur>} ; rappeler la route le ré-ouvre (done=false). Remède du cas « le merge est passé mais le ticket reste affiché validé / merge bloqué sans jamais devenir terminé » : si `done` passe à true alors que le worktree est en state='needs_attention', ce state est repassé à 'cleaned' avec resolved_by='manual-done' — sans quoi derive_status continuerait de renvoyer « merge bloqué », qui prime sur `done`. Un ticket `crashed` reste « planté » malgré done (même priorité). 404 si projet ou ticket inconnu.",
    "GET /api/tickets/<slug>/<ticket_id>/results": "MR/PR détectées dans la session, branche git, commits depuis création, fichiers modifiés",
    "GET /api/sessions": "agents web + sessions CLI récentes (10 derniers jours). ?include_tests=1 rétablit les conversations de test filtrées par défaut.",
    "GET /api/sessions/grep": "?q=<regex>&day=&model=&role=&limit=50 — recherche transversale regex dans toutes les sessions (messages + tool_calls)",
    "GET /api/sessions/<key>/overview": "vue supervision courante: résumé session + derniers tours (paginé ?after=N&limit=30). Texte plain par défaut, ?json pour JSON structuré.",
    "GET /api/sessions/<key>/blocks": "?after=N&plain=1 — conversation; plain=1 → texte structuré sans HTML",
    "GET /api/sessions/<key>/turns": "par appel LLM: heure, delta_s, tokens in/out, cache lu/écrit, %hit, outils, coût",
    "GET /api/sessions/<key>/costs": "agrégats coûts session: par modèle + total (tokens in/out, cache lu/écrit, %hit, coût $)",
    "GET /api/sessions/<key>/turns/<turn>": "payload exact du tour, items annotés cached/new-cache/fresh + réponse",
    "GET /api/sessions/<key>/turns/<n>/view": "zoom lisible sur un tour suspect: messages user/assistant, tool_calls avec résumé résultats. ?thinking=1 inclut les blocs thinking. Plain text par défaut.",
    "GET /api/sessions/<key>/turns/<n>/context": "diagnostic du contexte injecté au modèle pour le tour n. HTML riche par défaut, ?json=1 → payload brut. 404 si aucun diagnostic pour ce tour.",
    "GET /api/sessions/<key>/calls/<call_id>": "contenu intégral d'un tool_call (arguments + output complet). Pour inspecter un dump volumineux sans polluer la vue d'ensemble.",
    "GET /api/sessions/<key>/files": "diffs des fichiers modifiés (file_snapshots) → {files:[{path, is_new, added, html}]}. ?raw=1 joint `before`/`after` bruts (Monaco côte-à-côte).",
    "POST /api/sessions/<key>/restore": "restaure une session/conversation soft-supprimée (retire du registre deleted_sessions)",
    "POST /api/sessions/purge-test": "{dry?} — soft-delete des sessions CLI de test (titre 'test' + <=3 tours); dry=true → aperçu sans supprimer",
    "GET /api/typologies": "?project=<slug> — typologies d'agents déclarées (projet + global)",
    "GET /api/agents/tree": "parc d'agents tous projets, en arbre parent/enfants avec projet et état; les conversations en attente d'input remontent en tête. ?offset=&limit= sert `limit` RACINES à partir d'`offset`, chacune avec ses sous-agents, + `total_roots`; sans `limit`, l'arbre complet.",
    "GET /api/agents/activity": (
        "CE QUE FAIT chaque agent vivant : outil en cours, tour, âge du dernier battement "
        "(`idle_seconds`), silence anormal (`stale`), question posée — plus les tickets en cours "
        "de lancement avec leur phase (création du worktree / installation uv / démarrage). "
        "Vue de SURVEILLANCE : aucun git, aucun prompt, aucun agent terminé. À PRÉFÉRER à "
        "/api/agents/tree pour du monitoring — l'arbre complet coûte ~9,5 s et 929 Ko."
    ),
    "POST /api/dispatch": (
        "{prompt, project_slug?, typology?, model?, parent?, isolation?, defer?, ephemeral?, "
        "resume_branch?, work_branch?, use_readme?} — c'est CE endpoint qu'utilise la barre de lancement de "
        "/conversations : il crée le ticket ET lance l'agent (pas de ticket dormant). "
        "isolation = 'shared' (défaut, dépôt principal) | 'worktree' (worktree git seul) | "
        "'worktree+venv'; deux 'shared' sur le même dépôt → le second est basculé worktree "
        "d'office (garde-fou, commentaire posé sur le ticket). defer=true répond dès le ticket "
        "créé et fait partir worktree+spawn en fond (réponse sans `key`, avec deferred:true). "
        "resume_branch = POINT DE DÉPART (le worktree en part, l'agent reste sur une branche "
        "neuve `agent/<ticket>`) ; work_branch = branche EXISTANTE sortie telle quelle, les "
        "commits de l'agent y vont directement. work_branch inconnue ou déjà sortie dans un "
        "autre worktree → {routed:false, error} nommant le worktree occupant, SANS créer de "
        "ticket ni d'agent (jamais de repli silencieux sur une branche neuve). "
        "Aucune déduction LLM : sans project_slug la réponse est {needs_project:true, routed:false, "
        "suggestions:[{slug,name}]}. Sinon → {routed:true, ticket_id, title, project_slug, "
        "project_name, typology, model, isolation, isolation_reason, needs_project:false} plus "
        "`key: 'agent/<id>'` et `isolated` en mode synchrone, ou `deferred:true` en mode différé. "
        "400 si prompt vide, 503 si l'env API est KO."
    ),
    "POST /api/agents/launch": "{prompt, model?, cwd?, typology?, parent?} — lancer un agent libre HORS ticket (typology applique un profil) → {key, agent_id}. 400 si prompt vide, 503 si l'env API est KO.",
    "POST /api/agents/<agent_id>/continue": "{text} — follow-up, ou réponse à un AskUserQuestion, ou simple reprise si text vide. 404 agent inconnu, 409 si l'agent tourne encore.",
    "POST /api/agents/<agent_id>/kill": "tuer l'agent (process). 404 si agent inconnu.",
    "POST /api/agents/<agent_id>/interrupt": "interruption DOUCE puis ESCALADE : pose cancel.flag (le tour en cours s'arrête proprement, process gardé et gardé CHAUD → le /continue suivant le réveille sans cold-start) ; si l'agent TIENT ENCORE SON TOUR après ~1,5 s de grâce, son process est TUÉ comme /kill → {ok, escalated}. Un refus de l'OS (AccessDenied) rend {ok:false, error} et est commenté sur le ticket. 404 si agent inconnu.",
    "POST /api/agent/message": "{ticket_id, text} — ré-instruire l'agent DÉJÀ lancé d'un ticket, contexte gardé (voie du manager). 404 ticket inconnu, 400 text vide, 409 si l'agent tourne encore.",
    "GET /api/agents/<name>/export": "exporte un agent/profil sous forme de YAML partageable → {name, yaml}. 404 si agent inconnu.",
    "POST /api/agents/import": "{yaml, confirm_git?} — importe un agent/profil depuis le YAML produit par /api/agents/<name>/export",
    "POST /api/agents/<name>/upgrade-plugins": "{confirm_git?} — réinstalle/met à jour les plugins dont dépend un profil d'agent. 404 si profil inconnu.",
    "GET /api/conversations/interrupted": "conversations mortes sans fin propre (crash/restart) à relancer MANUELLEMENT",
    "POST /api/conversations/<agent_id>/relaunch": "{text?} — relance manuelle d'une conversation interrompue (reprend sa session)",
    "POST /api/conversations/purge-tests": "{agent_ids: [...]} — soft-delete (corbeille) des conversations de TEST listées ; double filtre heuristique côté service, une vraie conversation n'est jamais touchée. 400 si agent_ids n'est pas une liste.",
    "POST /api/conversations/archive": "{keys: ['agent/<id>', ...]} — archive (soft-delete réversible) une ou plusieurs conversations → {archived:[...], skipped:[{agent_id, reason}]}. Réversible via POST /api/sessions/<key>/restore.",
    "GET /api/conversations/stale-need-input": "conversations bloquées en 'need input' avec un process MORT (orphelines) → {candidates:[...]}, archivables en masse via /api/conversations/archive.",
    "GET /api/agents/awaiting": "les agents qui attendent une réponse de l'utilisateur, AVEC leur question → {agents:[{agent_id, key, title, state, question, options, allow_freetext, asked_at, warm, project_slug, ticket_slug, ticket_id, parent}]}, la plus vieille question d'abord. Répondre via POST /api/agents/<id>/continue (ou les commentaires du ticket, send=true).",
    "GET /api/agents/unreachable": "les tickets OUVERTS dont l'agent est introuvable (enregistrement disparu du parc) → {tickets:[{project_slug, ticket_id, title, agent_ids, trash_dir}]}. Tout envoi vers ces agents échoue en 404 reason=agent_missing tant que leur fiche n'est pas restaurée.",
    "GET /api/models": "modèles disponibles (menu déroulant) : {name, provider} par modèle du registry",
    "GET /api/builder/catalog": "catalogue agent-builder → {tools:[{name, description, read_only, system}], skills:[{name, description, source}], hooks:[{name, description}], plugins:[{name, package, version, scope, source, enabled, description, tools}]}",
    "GET /api/builder/agents": "tous les agents/profils existants (toutes sources) → {agents:[{name, kind, source, editable, description, model, tools, skills, hooks, system_prompt_extra, requires_plugins}]}",
    "POST /api/builder/preview": "{system_prompt_extra?, model?, tools?, skills?, hooks?} — system prompt complet calculé (lecture seule) + bits runtime (tools/hooks/skills)",
    "GET /api/profiles": "profils d'agent globaux (~/.bouzecode/profiles/*.yaml), accessibles partout → {profiles:[{name, description, model, tools, skills, hooks, system_prompt_extra, requires_plugins}]}",
    "GET /api/profiles/<name>": "détail d'un profil d'agent → {name, description, model, tools, skills, hooks, system_prompt_extra, requires_plugins}. 404 si inconnu.",
    "POST /api/profiles": "{name, tools?, skills?, hooks?, model?, system_prompt_extra?} — créer/écraser un profil d'agent global (`name` seul est obligatoire; les listes se donnent par nom, cf. GET /api/builder/catalog)",
    "DELETE /api/profiles/<name>": "supprimer un profil d'agent global",
    "GET /api/skills": "toutes les skills découvertes, toutes sources → {skills:[{name, description, source, editable}]} — `editable` vaut true pour les skills globales (~/.bouzecode/skills), seules modifiables par cette API",
    "GET /api/skills/<name>": "contenu markdown brut d'une skill → {name, content, source, editable}. `?new=1` renvoie un gabarit de nouvelle skill au lieu d'un contenu existant.",
    "POST /api/skills": "{name, content} — créer/écraser une skill globale (~/.bouzecode/skills/<name>.md) → {name, path}; `name` en minuscules/chiffres/-/_ et `content` non vide, sinon 400 {error}",
    "DELETE /api/skills/<name>": "supprimer une skill globale (~/.bouzecode/skills/<name>.md); 404 si ce n'est pas une skill globale — les skills builtin/projet ne sont pas supprimables par cette API",
    "GET /api/plugins": "plugins installés → {plugins:[{name, package, version, scope, source, enabled, description, tools}]}",
    "POST /api/plugins": "{package, source?, confirm_git?} — installer un plugin (index de paquets par nom, ou source git/local)",
    "POST /api/plugins/from-gitlab": "{input, confirm_git?} — installer un plugin depuis une URL de repo GitLab OU un dossier git local (index de paquets d'abord, repo git en fallback confirmé)",
    "GET /api/version": "dérive de version → {boot_sha, boot_version, current_head_sha, sha_drift, source_drift, drift} : état figé au boot (SHA + empreinte du source) vs HEAD et fichiers du disque relus toutes les 10 s max (le bandeau UI alerte quand le serveur tourne du code périmé)",
    "GET /api/env-sanity": "verdict du sanity-check de l'env API fait au boot → {ok, detail, base_url_present, key_present} (ANTHROPIC_BASE_URL/clé présentes et base_url joignable) — alimente le bandeau rouge et les gardes 503 des endpoints de spawn",
    "GET /api/search": "?q=<mots séparés par des espaces, match ET>&scope=open|all (défaut open) — recherche par mots-clés dans les conversations d'agents → {results:[...]}",
    "GET /api/interrupted": "snapshot FIGÉ au boot des travaux interrompus par le dernier arrêt serveur → {boot_at, items:[...], dismissed}",
    "POST /api/interrupted/dismiss": "masque le bandeau des travaux interrompus (choix persisté : il ne réapparaît pas seul)",
}
