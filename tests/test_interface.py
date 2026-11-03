"""Interface Streamlit : affichage, mémoire des exemples et limite par visiteur (sans LLM)."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from agent import boucle

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
EXEMPLE = "Je cherche un poste de data scientist à Paris"


class _Appels(list):
    """Liste des questions reçues par le faux agent, plus ce dont il se souvenait."""


@pytest.fixture
def faux_agent(monkeypatch):
    """Remplace l'agent par une fonction instantanée qui compte ses appels."""
    appels = _Appels()

    def lancer_agent(question, modele, afficher=True, cv=None, suivi=None, conversation=None):
        appels.append(question)
        appels_avec_memoire.append([q for q, _ in conversation.echanges])  # ce dont l'agent se souvient
        suivi({"type": "outil", "nom": "read_cv", "arguments": {}, "resultat": "CV"})
        reponse = f"Réponse à : {question}"
        conversation.ajouter_echange(question, reponse)
        return reponse

    appels_avec_memoire = []

    monkeypatch.setattr(boucle, "lancer_agent", lancer_agent)
    monkeypatch.setenv("CV_PATH", "data/absent.pdf")
    st.cache_resource.clear()  # mémoire des exemples et compteurs remis à zéro
    appels.memoires = appels_avec_memoire
    return appels


def demander(question):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.chat_input[0].set_value(question).run()
    assert not at.exception
    return at


def textes(at):
    return " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption) \
        + " ".join(i.value for i in at.info)


def test_la_page_s_affiche():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Veille d'offres d'emploi"


def test_une_question_affiche_la_reponse(faux_agent):
    at = demander("Offres Python à Lyon")
    assert "Réponse à : Offres Python à Lyon" in textes(at)
    assert faux_agent == ["Offres Python à Lyon"]


def test_exemple_mis_en_memoire(faux_agent):
    demander(EXEMPLE)
    at = demander(EXEMPLE)  # autre visiteur, même exemple
    assert faux_agent == [EXEMPLE]  # l'agent n'a travaillé qu'une fois
    assert "exemple mis en mémoire" in textes(at)


def test_limite_de_3_demandes_par_visiteur(faux_agent, monkeypatch):
    monkeypatch.setenv("JOBSCOUT_VISITEUR_TEST", "visiteur-1")
    for i in range(3):
        demander(f"Question {i}")
    at = demander("Question de trop")
    assert faux_agent == ["Question 0", "Question 1", "Question 2"]
    assert "Tu as utilisé tes 3 demandes" in textes(at)
    # Un autre visiteur n'est pas concerné.
    monkeypatch.setenv("JOBSCOUT_VISITEUR_TEST", "visiteur-2")
    demander("Question d'un autre visiteur")
    assert faux_agent[-1] == "Question d'un autre visiteur"


def test_pas_de_limite_en_local(faux_agent):
    for i in range(5):
        demander(f"Question {i}")
    assert len(faux_agent) == 5


def test_l_agent_se_souvient_de_la_question_precedente(faux_agent):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.chat_input[0].set_value("Offres Python à Lyon").run()
    at.chat_input[0].set_value("Compare la 2e à mon CV").run()
    assert not at.exception
    assert faux_agent.memoires == [[], ["Offres Python à Lyon"]]


def test_exemple_en_memoire_puis_question_de_suite(faux_agent):
    demander(EXEMPLE)  # premier visiteur : l'exemple est calculé et mis en mémoire
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.chat_input[0].set_value(EXEMPLE).run()  # second visiteur : réponse en mémoire
    at.chat_input[0].set_value("Et la 2e ?").run()
    # La question de suite connaît l'exemple, bien que l'agent ne l'ait pas recalculé.
    assert faux_agent == [EXEMPLE, "Et la 2e ?"]
    assert faux_agent.memoires[-1] == [EXEMPLE]


def test_quota_epuise_message_avec_le_vrai_delai(faux_agent, monkeypatch):
    def lancer_agent(question, modele, **kwargs):
        modele.attente_groq = 648  # délai annoncé par Groq
        raise ConnectionError("Groq indisponible et pas d'Ollama")

    monkeypatch.setattr(boucle, "lancer_agent", lancer_agent)
    at = demander("Trouve moi des offres AI engineer")
    assert "réessaie dans environ 11 minutes" in at.warning[0].value
    # Pas le message générique « indisponible » (le bandeau « Clé Groq manquante » peut exister sans clé).
    assert not any("indisponible" in e.value for e in at.error)
