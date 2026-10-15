"""Lecture SEULE de l'activite personnelle Microsoft 365 : mails Outlook et chats Teams.

Pourquoi un module a part alors que `services/work/teams/` parle deja a Graph : le
transport Teams sert la BOITE DU BUREAU (envoi, abonnements, websocket) avec les scopes
`Chat.Read` / `ChatMessage.Send`. Ici on lit ce que l'HUMAIN a recu, en lecture seule, avec les scopes
minimaux `Mail.Read` / `Chat.Read`. Meme plomberie, autre script, autres droits : on
reutilise `PowerShellTransport` (dont `script` est un parametre) au lieu de dupliquer le
parsing, les timeouts et la traduction des erreurs.

Consequences pratiques :

* les erreurs sont des TYPES, pas des chaines : `TeamsAuthError` quand le tenant refuse le
  consentement (`Mail.Read`/`Chat.Read` ne sont PAS accordes par le scope Teams existant),
  `TeamsTransportError` pour tout le reste. Un outil qui ne peut pas lire doit le DIRE.
* la fenetre de temps est decidee ICI et passee au script en ISO UTC : le .ps1 ne calcule
  aucune date lui-meme (une seule source de verite pour « ces 30 derniers jours »).
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import ms_activite_cache as _cache
from .teams.graph_transport import PowerShellTransport
#  Les deux erreurs sont levees par `graph_transport._lever` (et non par `reader`) :
#  TeamsAuthError herite de TeamsTransportError, donc attraper la seconde attrape tout.
from .teams.graph_transport import TeamsAuthError, TeamsTransportError  # noqa: F401

#: Script de lecture, dans `ps/` pour partager `ps/proxy.ps1` et `ps/graph_auth.ps1`.
GRAPH_ACTIVITE_PS1 = Path(__file__).parent / "teams" / "ps" / "graph_activite.ps1"

#: Fenetres acceptees, en jours. Meme vocabulaire que l'outil `ResteAFaire` du Bureau
#: (`2j`, `7j`, `30j`) : l'assistant n'a pas deux grammaires de duree a retenir.
FENETRES: dict[str, int] = {"2j": 2, "7j": 7, "30j": 30}
FENETRE_DEFAUT = "30j"

#: Graph pagine ; on borne pour ne pas faire pendre un tour d'agent sur une boite chargee.
TOP_MAILS = 50
TOP_CHATS = 30
#: Canaux d'equipe visites au plus. Un tenant a vite 10 equipes x 5 canaux : sans plafond,
#: la lecture pendrait un tour d'agent entier (un GET de messages par canal).
TOP_CANAUX = 30
MESSAGES_PAR_CHAT = 20

#: Plafond de TEXTE par message Teams. Graph rend `body.content` en HTML COMPLET : mesure du
#: 2026-09-09 sur le tenant reel, 30 chats sur 30 jours = 271 103 caracteres injectes d'un
#: coup dans le prompt de l'assistant (~68 000 tokens), qui s'arretait sans jamais montrer
#: le resultat. Un message utile se lit en quelques phrases ; le reste est du balisage.
BODY_MAX = 400
#: Plafond GLOBAL de la reponse `chats`. Sans lui, le pire cas reste TOP_CHATS x
#: MESSAGES_PAR_CHAT = 600 messages : le symptome reviendrait des que l'humain a du trafic.
SORTIE_MAX = 50_000
#: Nombre de messages gardes PAR CHAT, essaye dans l'ordre jusqu'a tenir SORTIE_MAX. Un
#: plafond fixe unique ne tient pas la promesse de budget : 5 messages/chat pesaient encore
#: ~67 000 caracteres sur la mesure reelle, 3 en pesent ~40 000.
PLAFONDS_DEGRESSIFS: tuple[int, ...] = (10, 5, 3, 2, 1, 0)


#: Plafond du mode DETAIL (`messages_conversation`) : 10x le mode liste. Une seule
#: conversation est demandee a la fois, donc le risque de saturer le contexte disparait
#: et l'assistant a droit au corps quasi entier de ce qu'il a decide de relire.
BODY_DETAIL = 4_000


def texte_lisible(brut: Any, plafond: int = BODY_MAX) -> str:
    """Le HTML d'un message Teams rendu en texte lisible et borne.

    L'assistant doit lire des PHRASES, pas des `<div>` : les balises ne l'aident pas a
    decider et elles pesent une bonne part des ~480 caracteres moyens d'un message mesures
    sur le tenant. On enleve le balisage AVANT de desechapper les entites, sinon un
    `&lt;div&gt;` desechappe se ferait passer pour du balisage a re-enlever.
    """
    texte = re.sub(r"<[^>]+>", " ", str(brut or ""))
    texte = re.sub(r"\s+", " ", html.unescape(texte)).strip()
    if len(texte) <= plafond:
        return texte
    return texte[:plafond] + "\u2026"


def _poids(charge: Any) -> int:
    """Le cout REEL de la charge pour le prompt : sa taille une fois serialisee."""
    return len(json.dumps(charge, ensure_ascii=False))


def _alleger(chats: list[dict], budget: int = SORTIE_MAX) -> list[dict]:
    """Les conversations rendues lisibles, sous un budget de caracteres garanti.

    Deux gestes, dans cet ordre : chaque `body` devient du texte borne, puis SI la charge
    depasse encore le budget on garde moins de messages par chat. Deux invariants :

    * toutes les conversations restent LISTEES (id, topic, kind) meme videes de leurs
      messages : l'assistant doit voir qu'il y a du trafic qu'il n'a pas lu ;
    * une coupe est ANNONCEE (`messages_omis`) : couper en silence lui ferait croire
      qu'il a tout lu, et c'est exactement comme ca qu'on invente des taches.

    On garde la TETE de liste : Graph rend les messages du plus recent au plus ancien, donc
    tronquer par la fin garde les plus recents sans avoir a re-trier des dates.
    """
    bruts: list[tuple[dict, list[dict]]] = []
    for chat in chats:
        messages = [
            dict(message, body=texte_lisible(message.get("body")))
            for message in (chat.get("messages") or [])
            if isinstance(message, dict)
        ]
        entete = {cle: valeur for cle, valeur in chat.items() if cle != "messages"}
        bruts.append((entete, messages))

    def rendre(plafond: int | None) -> list[dict]:
        sortie = []
        for entete, messages in bruts:
            gardes = messages if plafond is None else messages[:plafond]
            element = dict(entete)
            element["messages"] = gardes
            omis = len(messages) - len(gardes)
            if omis:
                element["messages_omis"] = omis
            sortie.append(element)
        return sortie

    allegees = rendre(None)
    if _poids(allegees) <= budget:
        return allegees
    for plafond in PLAFONDS_DEGRESSIFS:
        allegees = rendre(plafond)
        if _poids(allegees) <= budget:
            return allegees
    return allegees


#  Nombre d'appels PowerShell simultanes quand `rapport_canaux` decoupe par equipe.
#  Chaque appel est un process independant : le parallelisme est ce qui rachete le cout
#  des N appels (sans lui, decouper serait N fois plus lent que l'appel global).
PARALLELE_CANAUX = 6


def borne_iso(fenetre: str = FENETRE_DEFAUT, maintenant: datetime | None = None) -> str:
    """Rend la borne basse ISO 8601 UTC (`2026-08-10T00:00:00Z`) de `fenetre`.

    Leve `ValueError` sur une fenetre inconnue : mieux vaut refuser que lire silencieusement
    une periode que personne n'a demandee (un « 90j » avale par defaut en `30j` serait un
    mensonge dans la reponse rendue a l'humain)."""
    if fenetre not in FENETRES:
        connues = ", ".join(sorted(FENETRES))
        raise ValueError(f"fenetre inconnue : {fenetre!r} (attendu : {connues})")
        # noqa
    reference = maintenant or datetime.now(timezone.utc)
    debut = reference - timedelta(days=FENETRES[fenetre])
    return debut.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ActiviteTransport(PowerShellTransport):
    """`PowerShellTransport` vise sur `graph_activite.ps1`.

    On herite `_call` / `_parse` / `_lever` : timeouts, JSON compact, codes d'erreur auth
    sont deja resolus la-bas et n'ont pas a etre re-ecrits ici."""

    def __init__(
        self,
        runner: Any = None,
        timeout: int | None = None,
        cache: bool = True,
        maintenant: datetime | None = None,
        racine_cache: Path | None = None,
    ) -> None:
        if timeout is None:
            super().__init__(runner=runner, script=GRAPH_ACTIVITE_PS1)
        else:
            super().__init__(runner=runner, script=GRAPH_ACTIVITE_PS1, timeout=timeout)
        #  `maintenant` est INJECTE (et non lu via datetime.now dans _call) pour que les
        #  tests decident quel jour est « aujourd'hui » sans monkeypatcher l'horloge du
        #  process : le jour courant est la seule chose que le cache ne fige jamais.
        self._cache_actif = cache
        self._maintenant = maintenant
        self._racine_cache = racine_cache

    #  ------------------------------------------------------------------ cache par jour
    def _call(self, action: str, **parametres: Any) -> dict:
        """Meme contrat que `PowerShellTransport._call`, mais un jour REVOLU ne se
        re-telecharge jamais.

        Le cache vit ICI et pas dans `PowerShellTransport` : ce dernier est generique (un
        script par transport) et toutes les actions n'ont pas de fenetre de temps.

        Un seul appel PowerShell par lecture, meme apres 30 jours d'absence : les items
        rendus par le script portent tous leur date (`received` / `created`), donc UN appel
        borne au plus ancien jour manquant suffit a reconstituer toutes les tranches. Un
        appel par jour aurait coute 30 authentifications Graph.
        """
        since = parametres.get("Since")
        if (
            not self._cache_actif
            or not _cache.cache_actif()
            or action not in _cache.ACTIONS_CACHABLES
            or not since
            or parametres.get("MessageId")
        ):
            return super()._call(action, **parametres)

        maintenant = self._maintenant or datetime.now(timezone.utc)
        aujourdhui = _cache.jour_courant(maintenant)
        jours = _cache.jours_couverts(str(since), maintenant)
        if not jours:
            return super()._call(action, **parametres)

        deja: list[dict] = []
        manquants: list[str] = []
        for jour in [jour for jour in jours if jour < aujourdhui]:
            tranche = _cache.lire_tranche(action, parametres, jour, self._racine_cache)
            if tranche is None:
                manquants.append(jour)
            else:
                deja.append(tranche)

        #  Rien ne manque => on ne redemande QUE le jour courant.
        depart = manquants[0] if manquants else aujourdhui
        frais = super()._call(
            action, **{**parametres, "Since": _cache.minuit_iso(depart)}
        )

        if _cache.figeable(action, frais):
            decoupe = _cache.decouper(action, frais, maintenant)
            for jour in _cache.jours_couverts(_cache.minuit_iso(depart), maintenant):
                if jour >= aujourdhui:
                    continue
                #  Un jour revolu SANS activite est fige VIDE : sinon il resterait
                #  « manquant » a jamais et chaque lecture rouvrirait la fenetre entiere.
                _cache.ecrire_tranche(
                    action,
                    parametres,
                    jour,
                    decoupe.get(jour) or {"value": []},
                    self._racine_cache,
                )

        return _cache.fusionner(action, [*deja, frais])

    def mail_brut(self, depuis_iso: str, top: int = TOP_MAILS) -> dict:
        """La charge COMPLETE : les mails ET le signal « il en restait derriere ».

        Defaut du 2026-09-09 : seul `value` etait garde, le `has_more` de Graph partait
        a la poubelle. L'assistant recevait 50 mails couvrant 3 jours en croyant tenir
        les 30 jours qu'il avait demandes."""
        charge = self._call("mail", Since=depuis_iso, Top=top)
        mails = [element for element in (charge.get("value") or []) if isinstance(element, dict)]
        return {"mails": mails, "has_more": bool(charge.get("has_more"))}

    def mail(self, depuis_iso: str, top: int = TOP_MAILS) -> list[dict]:
        return self.mail_brut(depuis_iso, top=top)["mails"]

    def mail_un(self, message_id: str) -> dict:
        """UN mail avec son corps ENTIER : ce que la liste ne rend jamais.

        La liste ne porte que le `bodyPreview` de Graph (~250 caracteres) : c'est un
        choix de budget (131 mails x corps entier noierait le prompt), pas une limite
        de l'API. Ce chemin est la porte de sortie ciblee. Aucun `Since` n'est envoye :
        un mail demande par son id rend la fenetre sans objet."""
        charge = self._call("mail", MessageId=message_id)
        lus = [element for element in (charge.get("value") or []) if isinstance(element, dict)]
        return lus[0] if lus else {}

    def agenda_brut(self, depuis_iso: str, jusqu_iso: str, top: int) -> dict:
        """Les evenements de l'agenda entre deux bornes UTC, et le signal de coupe
        (`ms_agenda.rapport_agenda` en fait la reponse de l'outil `Agenda`)."""
        charge = self._call("agenda", Since=depuis_iso, Until=jusqu_iso, Top=top)
        lus = [element for element in (charge.get("value") or []) if isinstance(element, dict)]
        return {"evenements": lus, "has_more": bool(charge.get("has_more"))}

    def chats_brut(self, depuis_iso: str, top: int = TOP_CHATS,
                   messages: int = MESSAGES_PAR_CHAT,
                   budget: int = SORTIE_MAX) -> dict:
        """Idem pour les chats : la liste allegee PLUS le signal de page suivante."""
        charge = self._call("chats", Since=depuis_iso, Top=top, Messages=messages)
        bruts = [element for element in (charge.get("value") or []) if isinstance(element, dict)]
        #  Le budget s'applique ICI, a la frontiere du process : ce qui sort de cette
        #  methode part tel quel dans le prompt de l'assistant.
        return {"chats": _alleger(bruts, budget), "has_more": bool(charge.get("has_more"))}

    def chats(self, depuis_iso: str, top: int = TOP_CHATS,
              messages: int = MESSAGES_PAR_CHAT,
              budget: int = SORTIE_MAX) -> list[dict]:
        return self.chats_brut(depuis_iso, top=top, messages=messages, budget=budget)["chats"]

    def canaux_brut(self, depuis_iso: str, top: int = TOP_CANAUX,
                    messages: int = MESSAGES_PAR_CHAT,
                    budget: int = SORTIE_MAX) -> dict:
        """Les CANAUX d'equipe et leurs messages recents, plus le signal de coupe.

        Trou du 2026-09-13 : `chats` ne lit que /me/chats. Une demande postee dans un
        canal d'equipe n'existait pour l'assistant dans AUCUNE de ses sources."""
        charge = self._call("canaux", Since=depuis_iso, Top=top, Messages=messages)
        bruts = [element for element in (charge.get("value") or []) if isinstance(element, dict)]
        return {"canaux": _alleger(bruts, budget),
                "has_more": bool(charge.get("has_more")),
                #  LISTER un canal (Team/Channel.ReadBasic.All) et le LIRE
                #  (ChannelMessage.Read.All, consentement admin) sont deux droits
                #  distincts : le script rend la liste meme quand le second manque.
                "messages_indisponibles": bool(charge.get("messages_indisponibles"))}

    def equipes_ids(self, top: int = TOP_CANAUX, depuis_iso: str = "") -> list[dict]:
        """L'AMORCE de la decomposition : juste `{id, equipe}`, en UNE requete Graph.

        `equipes()` liste aussi tous les canaux de chaque equipe (N+1 requetes) : bien
        trop lourd quand on veut seulement savoir quelles equipes paralleliser.
        `Since` est envoye meme s'il ne sert pas : le script exige ce parametre pour
        TOUTES ses actions (`Require-Param $Since`), et le relacher la-bas serait une
        regression pour les autres actions."""
        charge = self._call("equipes_ids", Since=depuis_iso or "1970-01-01T00:00:00Z",
                            Top=top)
        equipes = []
        for element in (charge.get("value") or []):
            if not isinstance(element, dict):
                continue
            identifiant = str(element.get("id") or "")
            if not identifiant:
                continue
            equipes.append({"id": identifiant,
                            "equipe": str(element.get("equipe")
                                          or element.get("displayName") or identifiant)})
        return equipes

    def canaux_equipe_brut(self, team_id: str, team_name: str = "",
                           depuis_iso: str = "", top: int = TOP_CANAUX,
                           messages: int = MESSAGES_PAR_CHAT,
                           budget: int = SORTIE_MAX) -> dict:
        """Les canaux d'UNE SEULE equipe — le grain que `rapport_canaux` parallelise.

        Un appel global sur 30j meurt au timeout et `subprocess.run` TUE PowerShell :
        son stdout est perdu, donc il n'y a RIEN a rendre. Decoupe par equipe, chaque
        appel termine est un acquis conserve, et une equipe manquante peut etre NOMMEE."""
        charge = self._call("canaux", Since=depuis_iso, Top=top, Messages=messages,
                            TeamId=team_id, TeamName=team_name)
        bruts = [element for element in (charge.get("value") or []) if isinstance(element, dict)]
        return {"canaux": _alleger(bruts, budget),
                "has_more": bool(charge.get("has_more")),
                "messages_indisponibles": bool(charge.get("messages_indisponibles"))}

    def equipes(self, top: int = TOP_CANAUX) -> list[dict]:
        """Les equipes de l'humain et LEURS CANAUX, sans lire un seul message.

        Chemin volontairement separe : il ne demande que `Team.ReadBasic.All` et
        `Channel.ReadBasic.All`, deux droits legers. « Liste les canaux ou je suis »
        doit donc marcher meme sur un tenant qui refuse la lecture des messages."""
        charge = self._call("equipes", Top=top)
        return [element for element in (charge.get("value") or []) if isinstance(element, dict)]

    def canaux(self, depuis_iso: str, top: int = TOP_CANAUX,
               messages: int = MESSAGES_PAR_CHAT,
               budget: int = SORTIE_MAX) -> list[dict]:
        return self.canaux_brut(depuis_iso, top=top, messages=messages,
                                budget=budget)["canaux"]

    def messages(self, chat_id: str, depuis_iso: str, message_id: str = "",
                 top: int = MESSAGES_PAR_CHAT) -> list[dict]:
        """Les messages d'UNE conversation, ou UN message precis, a la demande.

        Pas de `_alleger` ici : le budget global existe pour empecher une LISTE de 30
        conversations de saturer le prompt. Une conversation demandee nommement, elle,
        doit etre lue pour de vrai."""
        charge = self._call("messages", ChatId=chat_id, Since=depuis_iso,
                            MessageId=message_id, Top=top)
        return [element for element in (charge.get("value") or []) if isinstance(element, dict)]


def mails(fenetre: str = FENETRE_DEFAUT, top: int = TOP_MAILS,
          transport: ActiviteTransport | None = None) -> list[dict]:
    """Les mails Outlook recus depuis `fenetre`, du plus recent au plus ancien."""
    canal = transport or ActiviteTransport()
    return canal.mail(borne_iso(fenetre), top=top)


def _borne_dates(elements: list[dict], champ: str) -> tuple[str, str]:
    """La plus ancienne et la plus recente des dates rendues, en ISO comparable."""
    dates = sorted(str(element.get(champ) or "") for element in elements
                   if element.get(champ))
    return (dates[0], dates[-1]) if dates else ("", "")


def mail_complet(message_id: str, transport: ActiviteTransport | None = None) -> dict:
    """Le retour a la source pour les mails, sur le modele de `messages_conversation`.

    Le mode liste ne rend qu'un apercu : un agent voyait passer le mail sans pouvoir le
    citer ni y repondre, et devait demander a l'humain de recoller le texte (constat du
    2026-09-21). Ici le corps n'est PAS plafonne -- et comme ailleurs, "complet" qualifie
    le TEXTE, jamais le balisage HTML.
    """
    canal = transport or ActiviteTransport()
    brut = canal.mail_un(message_id)
    if not brut:
        raise ValueError(
            f"aucun mail ne porte l'id {message_id!r} : reprends l'`id` tel que `Mails` "
            f"l'a rendu dans sa liste.")
    corps = str(brut.get("body") or brut.get("preview") or "")
    return {**brut, "body": texte_lisible(corps, plafond=max(len(corps), 1))}


#: Cles dont le contenu n'est PAS du texte a chercher : un identifiant ou une URL
#: contenant « zen » ferait matcher n'importe quoi (GUID, webLink Graph). Toute cle
#: finissant par `_id` est ecartee en plus de cette liste.
_CLES_NON_CHERCHABLES = {"id", "weblink", "web_link", "url", "lien", "odata"}


def _sans_accents(texte: str) -> str:
    """Le texte comparable : minuscules ET sans diacritiques.

    `RÉUNION` doit trouver `reunion` et l'inverse : l'humain tape ce qu'il a en tete, pas
    l'orthographe exacte du mail. NFD separe la lettre de son accent, on jette l'accent."""
    decompose = unicodedata.normalize("NFD", texte.casefold())
    return "".join(lettre for lettre in decompose if not unicodedata.combining(lettre))


def _cle_cherchable(cle: str) -> bool:
    minuscule = str(cle).lower()
    return minuscule not in _CLES_NON_CHERCHABLES and not minuscule.endswith("_id")


def _texte_cherchable(objet: Any, sauf: tuple[str, ...] = ()) -> str:
    """Toutes les valeurs textuelles d'un objet, concatenees, identifiants exclus.

    On ne nomme PAS les cles (`subject`, `topic`, `preview`...) : elles sont fabriquees
    par `_alleger` et par le script, et une liste nominative deviendrait silencieusement
    fausse au premier renommage — la recherche ne trouverait plus rien sans qu'aucun test
    ne le dise. `sauf` sert a exclure une branche entiere (les `messages` d'un fil, que
    l'appelant traite separement)."""
    if isinstance(objet, str):
        return objet
    if isinstance(objet, dict):
        morceaux = [_texte_cherchable(valeur, sauf) for cle, valeur in objet.items()
                    if _cle_cherchable(cle) and str(cle).lower() not in sauf]
        return " ".join(morceau for morceau in morceaux if morceau)
    if isinstance(objet, (list, tuple)):
        morceaux = [_texte_cherchable(element, sauf) for element in objet]
        return " ".join(morceau for morceau in morceaux if morceau)
    return ""


def _termes(recherche: str) -> list[str]:
    """Les mots-cles normalises. Combines en ET : « zen condor » exige les DEUX, sinon une
    recherche a deux mots rendrait tout ce qui parle de l'un OU de l'autre, donc rien d'utile."""
    return [_sans_accents(mot) for mot in str(recherche or "").split() if mot]


def _correspond(objet: Any, termes: list[str], sauf: tuple[str, ...] = ()) -> bool:
    if not termes:
        return True
    texte = _sans_accents(_texte_cherchable(objet, sauf))
    return all(terme in texte for terme in termes)


def _filtrer_fils(fils: list[dict], termes: list[str]) -> list[dict]:
    """Les fils (chats ou canaux) retenus par la recherche.

    Deux portes volontairement differentes : si l'EN-TETE du fil matche (son sujet, son
    equipe), le fil est rendu INTACT — on ne mutile pas une conversation dont le titre est
    exactement ce qui etait cherche. Sinon on ne garde que les messages qui matchent :
    rendre 20 messages hors sujet parce qu'un seul parlait de CONDOR noierait la reponse."""
    if not termes:
        return fils
    gardes = []
    for fil in fils:
        if not isinstance(fil, dict):
            continue
        if _correspond(fil, termes, sauf=("messages",)):
            gardes.append(fil)
            continue
        messages = [message for message in (fil.get("messages") or [])
                    if _correspond(message, termes)]
        if messages:
            gardes.append({**fil, "messages": messages})
    return gardes


def _aveu_recherche(recherche: str, lus: int, tronque: bool) -> str:
    """Ce que la recherche NE prouve pas. Filtrer apres coup dans un echantillon plafonne
    et rendre « 0 resultat » laisserait croire que le mot-cle est absent de la boite : il
    n'est absent que des `lus` elements remontes. Le module entier existe pour ne jamais
    laisser passer ce mensonge, la recherche n'y echappe pas."""
    if not recherche or not tronque:
        return ""
    return (f" RECHERCHE PARTIELLE : « {recherche} » n'a ete cherche que dans les {lus} "
            f"elements effectivement lus, PAS dans toute la source. Une liste vide ne "
            f"prouve donc RIEN : rappelle l'outil avec un `top` plus grand avant de dire "
            f"a l'humain que ce mot-cle n'apparait nulle part.")


def rapport_mails(fenetre: str = FENETRE_DEFAUT, top: int = TOP_MAILS,
                  transport: ActiviteTransport | None = None,
                  recherche: str = "") -> dict:
    """Les mails AVEC leur couverture reelle : ce que `mails()` seul ne pouvait pas dire.

    Rendre une liste nue laissait l'appelant annoncer la fenetre DEMANDEE. Ici, quand le
    plafond est atteint, `tronque` est vrai, la couverture reelle est datee, et
    `avertissement` dit en clair quoi faire (rappeler avec un `top` plus grand).
    """
    canal = transport or ActiviteTransport()
    brut = canal.mail_brut(borne_iso(fenetre), top=top)
    lus = brut["mails"]
    debut, fin = _borne_dates(lus, "received")
    #  `has_more` quand le script le dit ; sinon le plafond atteint pile est deja l'aveu
    #  qu'il y avait une page derriere (mesure du 2026-09-09 : 50 mails sur 50).
    tronque = bool(brut.get("has_more")) or len(lus) >= top
    #  La recherche filtre APRES la lecture (Graph refuse `$orderby` avec `$search`, or le
    #  tri par date porte la couverture datee). `tronque` reste donc calcule sur les LUS :
    #  ce qui a ete coupe l'a ete par le plafond, pas par le mot-cle.
    termes = _termes(recherche)
    retenus = [mail for mail in lus if _correspond(mail, termes)]
    rapport = {"ok": True, "fenetre": fenetre, "plafond": top, "total": len(retenus),
               "total_lus": len(lus), "recherche": str(recherche or ""),
               "tronque": tronque, "couverture_debut": debut, "couverture_fin": fin,
               "avertissement": "", "mails": retenus}
    if tronque:
        rapport["avertissement"] = (
            f"COUVERTURE INCOMPLETE : le plafond de {top} mails est atteint, tu ne tiens "
            f"donc que du {debut} au {fin}, PAS la fenetre {fenetre} entiere. N'annonce "
            f"jamais {fenetre} sur cette base : cite la couverture reelle, et rappelle "
            f"Mails avec un `top` plus grand pour remonter plus loin.")
    rapport["avertissement"] += _aveu_recherche(rapport["recherche"], len(lus), tronque)
    return rapport


def rapport_chats(fenetre: str = FENETRE_DEFAUT, top: int = TOP_CHATS,
                  messages: int = MESSAGES_PAR_CHAT,
                  transport: ActiviteTransport | None = None,
                  budget: int = SORTIE_MAX, recherche: str = "") -> dict:
    """Les chats AVEC le compte de ce qui a ete coupe, agrege et donc visible.

    `messages_omis` existait deja par conversation, mais noye au milieu de 30 chats :
    un total et la liste des conversations VIDEES rendent la coupe impossible a manquer.
    """
    canal = transport or ActiviteTransport()
    brut = canal.chats_brut(borne_iso(fenetre), top=top, messages=messages, budget=budget)
    chats = brut["chats"]
    omis = sum(int(chat.get("messages_omis") or 0) for chat in chats)
    vides = [str(chat.get("topic") or chat.get("id") or "")
             for chat in chats if not (chat.get("messages") or [])]
    tronque = bool(brut.get("has_more")) or len(chats) >= top or omis > 0
    retenus = _filtrer_fils(chats, _termes(recherche))
    rapport = {"ok": True, "fenetre": fenetre, "plafond": top, "total": len(retenus),
               "total_lus": len(chats), "recherche": str(recherche or ""),
               "tronque": tronque, "messages_omis_total": omis,
               "conversations_vides": len(vides), "avertissement": "",
               "conversations": retenus}
    if tronque:
        rapport["avertissement"] = (
            f"COUVERTURE INCOMPLETE : {len(chats)} conversations rendues (plafond {top}), "
            f"{omis} messages omis, {len(vides)} conversation(s) videe(s) de tous leurs "
            f"messages pour tenir le budget. Tu n'as PAS tout lu : relis les "
            f"conversations utiles une par une avec `conversation_id` avant de conclure, "
            f"et ne presente pas cette liste comme exhaustive.")
    rapport["avertissement"] += _aveu_recherche(rapport["recherche"], len(chats), tronque)
    return rapport


def canaux_equipes(fenetre: str = FENETRE_DEFAUT, top: int = TOP_CANAUX,
                   messages: int = MESSAGES_PAR_CHAT,
                   transport: ActiviteTransport | None = None,
                   budget: int = SORTIE_MAX) -> list[dict]:
    """Les messages recents des CANAUX d'equipe Teams, canal par canal.

    `conversations_teams` ne lit que /me/chats : un canal d'equipe n'y figure pas. Sans
    cette source, une tache donnee dans un canal n'existait dans AUCUNE des vues de
    l'assistant (constat du 2026-09-13 sur la conversation d7c83ee6)."""
    pont = transport or ActiviteTransport()
    return pont.canaux(borne_iso(fenetre), top=top, messages=messages, budget=budget)


def _amorcer_equipes(pont, top: int, depuis: str) -> tuple[list[dict], str]:
    """La liste des équipes (1 requête), ou `([], raison)` si elle échoue : on retombe alors
    sur l'appel global plutôt que de ne rien rendre. Un refus de consentement remonte tel quel."""
    try:
        return pont.equipes_ids(top=top, depuis_iso=depuis), ""
    except TeamsTransportError as souci:
        return [], str(souci)


def _lire_equipes(pont, equipes: list[dict], depuis: str, top: int, messages: int,
                  budget: int) -> list[tuple[dict, dict | None, str]]:
    """Un appel PAR ÉQUIPE, en parallèle : chaque process a son propre timeout, donc chaque
    équipe lue est un acquis (un seul appel global mourait au timeout sur 30 jours)."""
    from concurrent.futures import ThreadPoolExecutor

    def _lire(equipe: dict) -> tuple[dict, dict | None, str]:
        try:
            return equipe, pont.canaux_equipe_brut(
                equipe["id"], equipe.get("equipe", ""), depuis,
                top=top, messages=messages, budget=budget), ""
        except TeamsTransportError as echec:
            return equipe, None, str(echec)

    with ThreadPoolExecutor(max_workers=min(len(equipes), PARALLELE_CANAUX)) as pool:
        return list(pool.map(_lire, equipes))


def _est_refus_de_droit(echec: str) -> bool:
    return "consentement" in echec.lower() or "authoriz" in echec.lower()


def _cle_canal(canal: dict) -> str:
    return str(canal.get("id") or f"{canal.get('equipe')}/{canal.get('canal')}")


def _non_lues(resultats: list) -> tuple[list[dict], str]:
    """Les équipes non lues, NOMMÉES, et la dernière raison qui est un refus de droit."""
    non_lues, auth_refusee = [], ""
    for equipe, brut, echec in resultats:
        if brut is None:
            non_lues.append({"equipe": equipe.get("equipe", "") or equipe["id"], "raison": echec})
            if _est_refus_de_droit(echec):
                auth_refusee = echec
    return non_lues, auth_refusee


def _canaux_uniques(lus: list[dict]) -> list[dict]:
    """Le même canal peut revenir de deux appels : compté UNE fois, sinon le total ment."""
    canaux, vus = [], set()
    for brut in lus:
        for canal in brut["canaux"]:
            if _cle_canal(canal) not in vus:
                vus.add(_cle_canal(canal))
                canaux.append(canal)
    return canaux


def _fusionner(resultats: list, equipes: list[dict]) -> tuple[dict, list[dict]]:
    """Les canaux lus et les équipes non lues."""
    lus = [brut for _, brut, _ in resultats if brut is not None]
    non_lues, auth_refusee = _non_lues(resultats)
    canaux = _canaux_uniques(lus)
    if not canaux and auth_refusee and len(non_lues) == len(equipes):
        #  Toutes les équipes refusées pour un droit manquant : zéro canal avec `ok: True`
        #  ferait croire à un vide RÉEL.
        raise TeamsAuthError(auth_refusee)
    return {"canaux": canaux, "has_more": any(b.get("has_more") for b in lus),
            "messages_indisponibles": any(b.get("messages_indisponibles") for b in lus)}, non_lues


def _alerte_interdits(nb: int) -> str:
    return (f"LISTE SEULE : ces {nb} canaux sont bien ceux dont l'humain est "
            f"membre, mais leurs MESSAGES n'ont PAS pu etre lus (consentement "
            f"ChannelMessage.Read.All non accorde sur le tenant). Lister un canal ne "
            f"demande aucun droit special, le lire si. Cite les canaux a l'humain et "
            f"demande-lui d'y regarder ou de faire accorder ChannelMessage.Read.All ; "
            f"n'affirme SURTOUT pas qu'aucune demande n'y a ete postee.")


def _alerte_tronque(nb: int, top: int, omis: int, vides: int) -> str:
    return (f"COUVERTURE INCOMPLETE : {nb} canaux d'equipe rendus (plafond "
            f"{top}), {omis} messages omis, {vides} canal(aux) vide(s) de tous "
            f"leurs messages pour tenir le budget. Tu n'as PAS tout lu : rappelle "
            f"`Canaux` avec un `top` plus grand avant de conclure, et ne presente pas "
            f"cette liste comme exhaustive.")


def _alerte_non_lues(non_lues: list[dict], nb_equipes: int) -> str:
    noms = ", ".join(str(item["equipe"]) for item in non_lues)
    return (f"EQUIPES NON LUES : {len(non_lues)} equipe(s) sur {nb_equipes} n'ont PAS "
            f"repondu ({noms}) — les canaux ci-dessus sont ceux des autres equipes. "
            f"Rappelle `Canaux` avec un `timeout` plus grand (ex. timeout=300) ou une "
            f"fenetre plus courte, et dis a l'humain que ces equipes n'ont pas ete "
            f"lues ; n'affirme SURTOUT pas que rien n'y a ete demande.")


def _alerte_amorce(raison: str) -> str:
    return (f"LISTE DES EQUIPES INDISPONIBLE : impossible d'enumerer les equipes "
            f"({raison}), la reponse vient d'un appel global non decoupe et peut "
            f"donc etre incomplete. Relance avec un `timeout` plus grand.")


def rapport_canaux(fenetre: str = FENETRE_DEFAUT, top: int = TOP_CANAUX,
                   messages: int = MESSAGES_PAR_CHAT,
                   transport: ActiviteTransport | None = None,
                   budget: int = SORTIE_MAX, recherche: str = "") -> dict:
    """Les canaux AVEC le compte de ce qui a ete coupe — meme contrat que `rapport_chats`.

    Un plafond muet est ce qui a fait croire a l'assistant qu'il avait tout lu : les
    trois sources (mails, chats, canaux) annoncent donc leur coupe dans la meme forme.
    Les alertes sont INDÉPENDANTES : « pas le droit de lire », « lu mais coupé », « équipes
    non lues » et « liste des équipes indisponible » ne demandent pas le même geste."""
    pont = transport or ActiviteTransport()
    depuis = borne_iso(fenetre)
    equipes, amorce_perdue = _amorcer_equipes(pont, top, depuis)
    non_lues: list[dict] = []
    if equipes:
        brut, non_lues = _fusionner(
            _lire_equipes(pont, equipes, depuis, top, messages, budget), equipes)
    else:
        brut = pont.canaux_brut(depuis, top=top, messages=messages, budget=budget)
    canaux = brut["canaux"]
    omis = sum(int(canal.get("messages_omis") or 0) for canal in canaux)
    vides = len([canal for canal in canaux if not (canal.get("messages") or [])])
    interdits = bool(brut.get("messages_indisponibles"))
    tronque = bool(brut.get("has_more")) or len(canaux) >= top or omis > 0
    alertes = [(interdits, lambda: _alerte_interdits(len(canaux))),
               (tronque, lambda: _alerte_tronque(len(canaux), top, omis, vides)),
               (non_lues, lambda: _alerte_non_lues(non_lues, len(equipes))),
               (amorce_perdue, lambda: _alerte_amorce(amorce_perdue))]
    retenus = _filtrer_fils(canaux, _termes(recherche))
    aveu = _aveu_recherche(str(recherche or ""), len(canaux), tronque)
    return {"ok": True, "fenetre": fenetre, "plafond": top, "total": len(retenus),
            "total_lus": len(canaux), "recherche": str(recherche or ""),
            "tronque": tronque, "messages_omis_total": omis,
            "canaux_vides": vides, "messages_indisponibles": interdits,
            "equipes_lues": max(len(equipes) - len(non_lues), 0),
            "equipes_non_lues": non_lues,
            "avertissement": " ".join(texte() for actif, texte in alertes if actif) + aveu,
            "canaux": retenus}


def rapport_equipes(top: int = TOP_CANAUX,
                    transport: ActiviteTransport | None = None) -> dict:
    """Les equipes de l'humain et leurs canaux, SANS lire les messages.

    Le repli demande par l'humain le 2026-09-13 : « il ne peut pas lister les canaux
    dans lesquels je suis simplement ? ». Si — et sans consentement admin. Cette
    fonction n'appelle jamais l'endpoint des messages, donc elle repond meme quand
    `rapport_canaux` doit se contenter de la liste."""
    pont = transport or ActiviteTransport()
    equipes = pont.equipes(top=top)
    total_canaux = sum(len(equipe.get("canaux") or []) for equipe in equipes)
    rapport = {"ok": True, "plafond": top, "total": len(equipes),
               "total_canaux": total_canaux, "avertissement": "", "equipes": equipes}
    if not equipes:
        rapport["avertissement"] = (
            "Aucune equipe rendue : soit l'humain n'appartient a aucune equipe, soit "
            "Team.ReadBasic.All n'est pas accorde. Ne conclus pas qu'il n'a pas de "
            "canaux sans le lui demander.")
    return rapport


def conversations_teams(fenetre: str = FENETRE_DEFAUT, top: int = TOP_CHATS,
                        messages: int = MESSAGES_PAR_CHAT,
                        transport: ActiviteTransport | None = None,
                        budget: int = SORTIE_MAX) -> list[dict]:
    """Les chats Teams ayant recu au moins un message depuis `fenetre`, messages inclus.

    `budget` borne la taille de la reponse en caracteres : elle est injectee entiere dans
    le prompt de l'assistant, qui a un contexte fini.
    """
    canal = transport or ActiviteTransport()
    return canal.chats(borne_iso(fenetre), top=top, messages=messages, budget=budget)


def messages_conversation(conversation_id: str, fenetre: str = FENETRE_DEFAUT,
                          message_id: str = "", top: int = MESSAGES_PAR_CHAT,
                          transport: ActiviteTransport | None = None) -> list[dict]:
    """Le retour a la source : les messages que le mode liste a coupes ou tronques.

    `conversations_teams` annonce `messages_omis` et termine les corps par un `...` :
    sans ce chemin de retour, ce qu'on declare non lu serait perdu pour de bon. Un
    `message_id` precis est rendu SANS plafond (c'est le sens de "contenu complet") ;
    une conversation entiere l'est au plafond large `BODY_DETAIL`.
    """
    canal = transport or ActiviteTransport()
    bruts = canal.messages(conversation_id, borne_iso(fenetre),
                           message_id=message_id, top=top)
    lus = []
    for brut in bruts:
        corps = str(brut.get("body") or "")
        #  Toujours du TEXTE, jamais du HTML : "complet" qualifie le texte, pas le balisage.
        plafond = len(corps) if message_id else BODY_DETAIL
        lus.append({**brut, "body": texte_lisible(corps, plafond=plafond)})
    return lus
