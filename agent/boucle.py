"""La boucle de l'agent, codée à la main.

1. On envoie au modèle la conversation et la liste des outils.
2. Si le modèle demande des outils, on les exécute et on ajoute leurs résultats
   à la conversation, puis on recommence.
3. S'il répond par du texte sans demander d'outil, c'est la réponse finale.
"""

import json
import re
from collections.abc import Callable
from urllib.parse import urlparse

from agent import outils
from agent.modele import Modele

PROMPT_SYSTEME = """Tu es un assistant de veille d'offres d'emploi. Tu réponds en français.

Tu disposes d'outils pour chercher des offres, lire le détail d'une offre et lire le CV de l'utilisateur.
Méthode :
- Lis le CV (read_cv) seulement si la demande parle explicitement de l'utilisateur ou de son profil
  (« pour moi », « mon CV », « qui me correspondent », « est-ce que je corresponds »…).
  Pour une simple recherche (« offres Python en télétravail », « data scientist à Paris »), ne lis PAS le CV :
  présente les offres sans score d'adéquation.
- Cherche des offres avec des mots-clés adaptés (surtout en anglais). Si les résultats sont maigres, essaie d'autres mots-clés,
  mais fais au maximum 3 recherches : les sources sont limitées, mieux vaut présenter les offres les plus proches
  (même imparfaites) en le disant honnêtement que chercher indéfiniment.
- Lis le détail (get_job_details) des offres que tu retiens avant de les résumer ou de les noter.
- Recopie les liens exactement tels que les outils les donnent (champ « url ») : n'en fabrique jamais.
- N'invente jamais d'offre : n'utilise que celles renvoyées par les outils.
- Si l'utilisateur parle d'une offre déjà présentée (« la 2e », « celle de Margo »), retrouve-la dans la liste
  des offres déjà trouvées et utilise son id avec get_job_details, sans relancer de recherche.

Pour chaque offre retenue, donne :
- le titre, l'entreprise, le lieu et un lien cliquable vers l'annonce ;
- la source (Arbeitnow, Remotive ou Adzuna) : c'est obligatoire ;
- un résumé en deux ou trois phrases ;
- si le CV a été lu : un score d'adéquation sur 100, les points forts et les compétences manquantes.
Termine par une courte recommandation."""

MAX_ETAPES = 10
MAX_RECHERCHES = 3
# Au-delà, on raccourcit les vieux résultats d'outils (limite de tokens de Groq).
TAILLE_MAX_HISTORIQUE = 14_000  # en caractères, environ 4 000 tokens
# Garde-fou : retire de la réponse finale les liens qu'aucun outil n'a renvoyés.
GARDE_FOU_LIENS = True

MOTIF_LIEN = r"https?://[^\s<>()\[\]\"'`|]+"
MENTION_LIEN_RETIRE = "(lien retiré : introuvable dans les résultats des outils)"


PONCTUATION_FINALE = ".,;:*_"


def extraire_liens(texte: str) -> list[str]:
    """Liens présents dans un texte, sans doublons ni ponctuation finale."""
    liens = re.findall(MOTIF_LIEN, texte)
    return list(dict.fromkeys(lien.rstrip(PONCTUATION_FINALE) for lien in liens))


def _lien_autorise(lien: str, liens_connus: set[str]) -> bool:
    # Une page d'accueil (« https://remotive.com ») ne désigne pas une offre : on la laisse.
    return lien in liens_connus or urlparse(lien).path in ("", "/")


def verifier_liens(texte: str, liens_connus: set[str]) -> tuple[str, list[str]]:
    """Retire les liens que le modèle a fabriqués.

    Renvoie le texte corrigé et la liste des liens retirés. Un lien Markdown
    [titre](lien) garde son titre ; seul le lien est remplacé par une mention.
    """
    inconnus = [lien for lien in extraire_liens(texte) if not _lien_autorise(lien, liens_connus)]
    if not inconnus:
        return texte, []

    def remplacer_markdown(trouve: re.Match) -> str:  # [titre](lien) : on garde le titre
        if trouve.group(2).rstrip(PONCTUATION_FINALE) not in inconnus:
            return trouve.group(0)
        return f"{trouve.group(1)} {MENTION_LIEN_RETIRE}"

    def remplacer_seul(trouve: re.Match) -> str:  # lien seul, éventuellement entre < >
        lien = trouve.group(1)
        nettoye = lien.rstrip(PONCTUATION_FINALE)
        if nettoye not in inconnus:
            return trouve.group(0)
        return MENTION_LIEN_RETIRE + lien[len(nettoye):]

    texte = re.sub(rf"\[([^\]]*)\]\(({MOTIF_LIEN})\)", remplacer_markdown, texte)
    texte = re.sub(rf"<?({MOTIF_LIEN})>?", remplacer_seul, texte)
    texte += (f"\n\n⚠️ Liens retirés : {len(inconnus)}. Ils ne figuraient dans aucun résultat "
              "des outils (probablement inventés par le modèle).")
    return texte, inconnus


class Conversation:
    """Mémoire d'une conversation, d'une demande à l'autre.

    Garde les derniers échanges (raccourcis) et la liste compacte des offres déjà
    trouvées, pour que « la 2e offre » ou « celle de Margo » aient un sens. Les liens
    de ces offres restent connus du garde-fou.
    """

    MAX_ECHANGES = 2
    TAILLE_MAX_REPONSE = 3_000  # caractères gardés de chaque réponse passée
    MAX_OFFRES = 15

    def __init__(self):
        self.echanges: list[tuple[str, str]] = []
        self.offres_vues: dict[str, dict] = {}  # id -> {id, titre, entreprise, lieu, url}

    def messages(self) -> list[dict]:
        """Messages à placer avant la nouvelle question."""
        messages = []
        if self.offres_vues:
            lignes = "\n".join(f"- {o['id']} | {o['titre']} | {o['entreprise']} | {o['lieu']} | {o['url']}"
                               for o in self.offres_vues.values())
            messages.append({"role": "system", "content": "Offres déjà trouvées plus tôt dans la conversation "
                             "(id | titre | entreprise | lieu | lien) :\n" + lignes})
        for question, reponse in self.echanges:
            if len(reponse) > self.TAILLE_MAX_REPONSE:
                reponse = reponse[:self.TAILLE_MAX_REPONSE] + " […]"
            messages += [{"role": "user", "content": question}, {"role": "assistant", "content": reponse}]
        return messages

    def liens_connus(self) -> set[str]:
        return {o["url"] for o in self.offres_vues.values()}

    def noter_resultat(self, nom: str, resultat: str) -> None:
        """Retient les offres renvoyées par une recherche ou une lecture de détail."""
        if nom not in ("search_jobs", "get_job_details"):
            return
        try:
            donnees = json.loads(resultat)
        except json.JSONDecodeError:
            return
        for offre in donnees if isinstance(donnees, list) else [donnees]:
            if isinstance(offre, dict) and "id" in offre and "url" in offre:
                self.offres_vues.pop(offre["id"], None)  # la plus récente passe en dernier
                self.offres_vues[offre["id"]] = {c: offre.get(c, "") for c in ("id", "titre", "entreprise", "lieu", "url")}
        while len(self.offres_vues) > self.MAX_OFFRES:
            self.offres_vues.pop(next(iter(self.offres_vues)))

    def ajouter_echange(self, question: str, reponse: str) -> None:
        self.echanges = (self.echanges + [(question, reponse)])[-self.MAX_ECHANGES:]

    def etat(self) -> dict:
        """Copie de la mémoire (pour la rejouer, ex. réponse d'exemple mise en mémoire)."""
        return {"echanges": list(self.echanges), "offres_vues": dict(self.offres_vues)}

    def restaurer(self, etat: dict) -> None:
        self.echanges, self.offres_vues = list(etat["echanges"]), dict(etat["offres_vues"])


def _alleger_historique(messages: list[dict]) -> None:
    """Mémoire courte : raccourcit les plus anciens résultats d'outils si besoin.

    Le CV et le dernier résultat sont toujours gardés en entier.
    """
    ids_cv = {
        appel["id"]
        for m in messages if m["role"] == "assistant"
        for appel in m.get("tool_calls", []) if appel["function"]["name"] == "read_cv"
    }
    for message in messages[:-1]:
        taille = sum(len(m.get("content") or "") for m in messages)
        if taille <= TAILLE_MAX_HISTORIQUE:
            return
        if message["role"] == "tool" and message["tool_call_id"] not in ids_cv \
                and len(message["content"]) > 300:
            message["content"] = message["content"][:300] + " […résultat raccourci pour économiser la mémoire]"


def _resume(texte: str, longueur: int = 120) -> str:
    texte = texte.replace("\n", " ")
    return texte if len(texte) <= longueur else texte[:longueur] + "…"


def lancer_agent(question: str, modele: Modele | None = None, afficher: bool = True,
                 cv: str | None = None, suivi: Callable[[dict], None] | None = None,
                 conversation: Conversation | None = None) -> str:
    """Fait travailler l'agent sur une question et renvoie sa réponse finale.

    cv : texte du CV à utiliser à la place du fichier CV_PATH (CV envoyé sur l'interface).
    suivi : fonction appelée à chaque étape, pour que l'interface affiche ce que fait l'agent.
    conversation : mémoire des demandes précédentes, mise à jour avec cette demande.
    """
    modele = modele or Modele()
    conversation = conversation or Conversation()
    messages = [
        {"role": "system", "content": PROMPT_SYSTEME},
        *conversation.messages(),
        {"role": "user", "content": question},
    ]
    recherches = 0
    # Liens renvoyés par les outils pendant cette demande et les précédentes.
    liens_connus: set[str] = conversation.liens_connus()

    def conclure(texte: str) -> str:
        if GARDE_FOU_LIENS:
            texte, retires = verifier_liens(texte, liens_connus)
            if afficher and retires:
                print(f"  🛡️ Liens inventés retirés de la réponse : {', '.join(retires)}")
            if suivi and retires:
                suivi({"type": "liens_retires", "liens": retires})
        conversation.ajouter_echange(question, texte)
        return texte

    for etape in range(1, MAX_ETAPES + 1):
        _alleger_historique(messages)
        if etape == MAX_ETAPES:
            # Dernière étape : plus d'outils, le modèle doit conclure avec ce qu'il a.
            messages.append({"role": "user", "content": "Tu as utilisé tous tes appels d'outils. "
                             "Donne maintenant ta réponse finale avec les informations déjà obtenues."})
            return conclure(modele.repondre(messages, [])["texte"])
        reponse = modele.repondre(messages, outils.SCHEMAS)

        if not reponse["appels"]:
            return conclure(reponse["texte"])

        # On garde la demande du modèle dans l'historique (format OpenAI).
        messages.append({
            "role": "assistant",
            "content": reponse["texte"],
            "tool_calls": [
                {"id": a["id"], "type": "function",
                 "function": {"name": a["nom"], "arguments": json.dumps(a["arguments"], ensure_ascii=False)}}
                for a in reponse["appels"]
            ],
        })
        for appel in reponse["appels"]:
            if afficher:
                print(f"  🔧 [{etape}] {appel['nom']}({json.dumps(appel['arguments'], ensure_ascii=False)})")
            if appel["nom"] == "search_jobs":
                recherches += 1
            if appel["nom"] == "search_jobs" and recherches > MAX_RECHERCHES:
                # Garde-fou dans le code : le modèle ne respecte pas toujours la consigne.
                resultat = ("Limite de recherches atteinte. Choisis parmi les offres déjà trouvées, "
                            "lis leur détail si besoin, puis réponds.")
            elif appel["nom"] == "read_cv" and cv is not None:
                resultat = cv
            else:
                resultat = outils.executer(appel["nom"], appel["arguments"])
            # Avant que la mémoire courte ne raccourcisse ce résultat.
            liens_connus.update(extraire_liens(resultat))
            conversation.noter_resultat(appel["nom"], resultat)
            if afficher:
                print(f"       → {_resume(resultat)}")
            if suivi:
                suivi({"type": "outil", "nom": appel["nom"], "arguments": appel["arguments"], "resultat": resultat})
            messages.append({"role": "tool", "tool_call_id": appel["id"], "content": resultat})

