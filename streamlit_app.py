"""Interface web de l'agent de veille d'offres d'emploi.

Lancer en local :  .venv/bin/streamlit run streamlit_app.py
"""

import json
import os
import re
import time
from datetime import date
from pathlib import Path

import streamlit as st

# Sur Streamlit Cloud, les clés sont dans les secrets de l'app : on les copie dans
# l'environnement avant de charger la configuration (en local, c'est le fichier .env).
try:
    for cle in ("GROQ_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        if cle in st.secrets and not os.getenv(cle):
            os.environ[cle] = str(st.secrets[cle]).strip()
except Exception:  # pas de fichier de secrets en local
    pass

from agent import config, outils  # noqa: E402
from agent.boucle import lancer_agent  # noqa: E402
from agent.modele import Modele  # noqa: E402

CV_EXEMPLE = Path(__file__).parent / "evaluation" / "cv_test.md"
DEPOT = "https://github.com/T-R-Bama/JobScout"

# La démo en ligne partage le quota quotidien gratuit de Groq (environ 10 demandes).
LIMITE_PAR_VISITEUR = 3  # demandes envoyées au modèle, par visiteur et par jour
DUREE_MEMOIRE_EXEMPLES = 6 * 60 * 60  # comme le cache des offres

SUGGESTIONS = {
    ":blue[:material/person_search:] Offres pour mon CV en France":
        "Trouve 3 offres en France qui correspondent à mon CV",
    ":green[:material/home_work:] Python en télétravail":
        "Trouve des offres de développeur Python en télétravail",
    ":orange[:material/location_city:] Data scientist à Paris":
        "Je cherche un poste de data scientist à Paris",
    ":violet[:material/public:] DevOps au Royaume-Uni":
        "Quelles offres DevOps y a-t-il au Royaume-Uni ?",
}

st.set_page_config(page_title="Veille d'offres d'emploi", page_icon=":material/work:")


@st.cache_resource
def reponses_des_exemples() -> dict:
    """Réponses aux exemples cliquables, partagées entre tous les visiteurs.

    Seulement avec le CV d'exemple : la réponse à un CV envoyé n'est jamais montrée à un autre.
    """
    return {}  # {question: {"heure", "message"}}


@st.cache_resource
def compteurs_des_visiteurs() -> dict:
    return {}  # {(visiteur, jour): nombre de demandes}


def identifiant_visiteur() -> str | None:
    """Adresse IP du visiteur, ou None en local (pas de limite sur sa propre machine)."""
    if os.getenv("JOBSCOUT_VISITEUR_TEST"):  # pour tester la limite en local
        return os.getenv("JOBSCOUT_VISITEUR_TEST")
    transfere = st.context.headers.get("X-Forwarded-For", "")  # derrière le proxy de Streamlit Cloud
    return transfere.split(",")[0].strip() if transfere else st.context.ip_address


def demandes_restantes(visiteur: str | None) -> int | None:
    if visiteur is None:
        return None
    return max(0, LIMITE_PAR_VISITEUR - compteurs_des_visiteurs().get((visiteur, date.today().isoformat()), 0))


def compter_demande(visiteur: str | None) -> None:
    if visiteur is None:
        return
    compteurs, jour = compteurs_des_visiteurs(), date.today().isoformat()
    for cle in [c for c in compteurs if c[1] != jour]:  # on oublie les jours précédents
        del compteurs[cle]
    compteurs[(visiteur, jour)] = compteurs.get((visiteur, jour), 0) + 1


if not config.GROQ_API_KEY and not config.CV_PATH.exists():  # démo en ligne sans clé
    st.error("Ajoute `GROQ_API_KEY` dans les secrets de l'app (Manage app → Settings → Secrets).",
             title="Clé Groq manquante")

if "messages" not in st.session_state:
    st.session_state.messages = []  # {"role", "content", "etapes", "modele"}
if "modele" not in st.session_state:
    st.session_state.modele = Modele()


# --- Barre latérale : choix du CV --------------------------------------------

with st.sidebar:
    st.header("Ton CV")
    choix_cv = ["CV d'exemple", "Mon CV (PDF)"]
    if config.CV_PATH.exists():  # en local seulement : le CV du fichier .env
        choix_cv.append("CV local")
    source_cv = st.segmented_control("CV utilisé", choix_cv, default="CV d'exemple",
                                     label_visibility="collapsed")
    cv_texte = None
    cv_exemple = False
    if source_cv == "Mon CV (PDF)":
        fichier = st.file_uploader("Ton CV au format PDF", type="pdf")
        if fichier:
            cv_texte = outils.texte_du_pdf(fichier)
            st.caption(f":material/check_circle: CV lu ({len(cv_texte):,} caractères). "
                       "Il n'est pas enregistré, seulement envoyé au modèle pendant ta demande.")
        else:
            st.caption("Sans CV envoyé, l'agent utilise le CV d'exemple.")
    if source_cv == "CV local":
        cv_texte = None  # l'outil read_cv lit le fichier CV_PATH
    elif cv_texte is None:
        cv_texte = CV_EXEMPLE.read_text()
        cv_exemple = True
        st.caption("CV fictif de Camille Martin, développeuse Python junior à Paris.")
        with st.expander("Voir le CV d'exemple"):
            st.markdown(cv_texte)

    st.header("Sources")
    st.markdown("- **Arbeitnow** : environ 900 offres en Europe\n"
                "- **Remotive** : offres en télétravail\n"
                + ("- **Adzuna** : offres en France\n" if config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY else ""))
    if config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY:
        st.caption("Jobs by [Adzuna](https://www.adzuna.fr)")
    st.caption("Offres mises en cache 6 h. Chaque demande est traitée séparément : "
               "l'agent ne se souvient pas des demandes précédentes.")
    zone_compteur = st.empty()  # remplie en fin de page, une fois la demande comptée
    if st.session_state.messages and st.button(":material/delete: Effacer la conversation", width="stretch"):
        st.session_state.messages = []
        st.rerun()


# --- Affichage des étapes de l'agent -----------------------------------------

def decrire_etape(etape: dict) -> tuple[str, str, str]:
    """Titre, détail et état d'une étape, pour l'affichage."""
    if etape["type"] == "liens_retires":
        liens = "\n".join(f"- `{lien}`" for lien in etape["liens"])
        return ("Garde-fou : lien inventé retiré", "Ces liens n'existaient dans aucun résultat :\n" + liens, "error")
    nom, arguments, resultat = etape["nom"], etape["arguments"], etape["resultat"]
    if nom == "read_cv":
        return ":material/description: Lecture du CV", "", "complete"
    titre = f":material/build: {nom}"
    if nom == "search_jobs":
        filtres = [arguments.get("lieu"), "télétravail" if arguments.get("teletravail_seulement") else ""]
        precision = ", ".join(f for f in filtres if f)
        titre = f":material/search: Recherche « {arguments.get('mots_cles', '')} »" + (f" ({precision})" if precision else "")
    try:
        donnees = json.loads(resultat)
    except json.JSONDecodeError:  # ex. recherche refusée par la limite de 3 recherches
        return f"{titre} : non lancée", resultat, "error"
    if nom == "search_jobs":
        if isinstance(donnees, list):
            detail = "\n".join(f"- {o['titre']} – {o['entreprise']} ({o['lieu']})" for o in donnees) or "Aucune offre trouvée."
            return f"{titre} : {len(donnees)} offre{'s' if len(donnees) > 1 else ''}", detail, "complete"
        return titre, str(donnees), "complete"
    if nom == "get_job_details":
        if "titre" in donnees:
            return f":material/article: Lecture de l'offre « {donnees['titre']} »", donnees.get("entreprise", ""), "complete"
        return ":material/article: Lecture d'une offre", donnees.get("erreur", ""), "error"
    return f":material/build: {nom}", "", "complete"


def adoucir_titres(texte: str) -> str:
    """Les grands titres Markdown du modèle sont trop gros dans une conversation."""
    return re.sub(r"^#{1,3} ", "#### ", texte, flags=re.MULTILINE)


def afficher_etape(etape: dict) -> None:
    titre, detail, etat = decrire_etape(etape)
    with st.status(titre, type="step", state=etat, expanded=False):
        if detail:
            st.markdown(detail)


def afficher_message(message: dict) -> None:
    with st.chat_message(message["role"]):
        if message.get("etapes"):
            with st.expander(message["resume_etapes"], type="compact"):
                for etape in message["etapes"]:
                    afficher_etape(etape)
        st.markdown(adoucir_titres(message["content"]))
        if message.get("modele"):
            st.caption(message["modele"])


# --- Conversation --------------------------------------------------------------

st.title("Veille d'offres d'emploi")
st.caption("Un agent IA qui cherche des offres, les résume et les compare à ton CV. "
           "Il choisit lui-même ses outils : recherche, lecture d'une offre, lecture du CV.")

for message in st.session_state.messages:
    afficher_message(message)

question = st.chat_input("Ex. : trouve des offres de data analyst à Lyon", submit_mode="disable")
if not st.session_state.messages:
    suggestions = st.empty()
    choisie = suggestions.pills("Exemples de demandes", list(SUGGESTIONS), label_visibility="collapsed")
    if choisie:
        question = SUGGESTIONS[choisie]
    if question:
        suggestions.empty()

visiteur = identifiant_visiteur()
memoire = reponses_des_exemples()
cle_exemple = question if question in SUGGESTIONS.values() and cv_exemple else None
en_memoire = memoire.get(cle_exemple)
if en_memoire and time.time() - en_memoire["heure"] > DUREE_MEMOIRE_EXEMPLES:
    en_memoire = None

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    afficher_message(st.session_state.messages[-1])

if question and en_memoire:
    # Exemple déjà traité récemment : réponse instantanée, sans consommer de tokens.
    minutes = round((time.time() - en_memoire["heure"]) / 60)
    message = {**en_memoire["message"],
               "modele": en_memoire["message"]["modele"] + f" · exemple mis en mémoire il y a {minutes} min"}
    afficher_message(message)
    st.session_state.messages.append(message)

elif question and demandes_restantes(visiteur) == 0:
    st.session_state.messages.pop()  # la question n'est pas traitée
    with st.chat_message("assistant"):
        st.info(f"Tu as utilisé tes {LIMITE_PAR_VISITEUR} demandes du jour sur cette démo : le modèle gratuit "
                "a un quota quotidien partagé entre tous les visiteurs. Les exemples de demandes restent "
                "disponibles (bouton « Effacer la conversation »), et le code est sur "
                f"[GitHub]({DEPOT}) pour faire tourner l'agent chez toi.",
                title="Limite de la démo atteinte", icon=":material/hourglass_top:")

elif question:
    with st.chat_message("assistant"):
        etapes = []
        modele = st.session_state.modele
        modele.fournisseur = "groq"  # chaque demande repart de Groq
        modele.erreur_groq = ""
        debut = time.time()
        with st.status(":shimmer[L'agent travaille… (1 à 3 minutes avec le modèle gratuit)]", type="compact", expanded=True) as statut:
            def suivre(etape: dict) -> None:
                etapes.append(etape)
                with statut:
                    afficher_etape(etape)

            try:
                reponse = lancer_agent(question, modele, afficher=False, cv=cv_texte, suivi=suivre)
                erreur = None
            except Exception as e:  # Groq saturé et pas d'Ollama (démo en ligne), réseau…
                reponse, erreur = "", e
            duree = time.time() - debut
            resume = f"{len(etapes)} étape{'s' if len(etapes) > 1 else ''} en {duree:.0f} s"
            statut.update(label=resume, state="error" if erreur else "complete", expanded=False)

        if erreur:
            st.error("Le modèle gratuit est saturé ou indisponible pour le moment. Réessaie dans quelques minutes.",
                     title="Pas de réponse")
            raison = modele.erreur_groq or f"{erreur.__class__.__name__}: {erreur}"
            st.caption(f"Détail technique : {raison[:300]}")
            st.session_state.messages.pop()  # on retire la question restée sans réponse
        else:
            st.markdown(adoucir_titres(reponse))
            secours = " (modèle local de secours)" if modele.fournisseur == "ollama" else ""
            legende = f"Réponse de {modele.nom}{secours}"
            st.caption(legende)
            message = {"role": "assistant", "content": reponse, "etapes": etapes,
                       "resume_etapes": resume, "modele": legende}
            st.session_state.messages.append(message)
            compter_demande(visiteur)
            if cle_exemple:
                memoire[cle_exemple] = {"heure": time.time(), "message": message}

restantes = demandes_restantes(visiteur)
if restantes is not None:
    zone_compteur.caption(f":material/hourglass_top: Demandes restantes aujourd'hui : {restantes}/{LIMITE_PAR_VISITEUR}. "
                          "Les exemples déjà en mémoire ne comptent pas.")
