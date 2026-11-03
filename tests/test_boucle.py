"""Boucle de l'agent, avec un faux modèle qui joue un scénario écrit à l'avance (sans LLM)."""

import json

from agent import boucle
from tests.conftest import OFFRES


class FauxModele:
    """Renvoie les réponses prévues, dans l'ordre, et garde les messages reçus."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels_recus = []
        self.fournisseur, self.nom, self.tokens = "faux", "faux-modele", 0

    def repondre(self, messages, schemas):
        self.appels_recus.append({"messages": [dict(m) for m in messages], "schemas": schemas})
        return self.reponses.pop(0)


def outil(nom, n=1, **arguments):
    return {"texte": "", "appels": [{"id": f"appel-{nom}-{n}", "nom": nom, "arguments": arguments}], "tokens": 0}


def texte(contenu):
    return {"texte": contenu, "appels": [], "tokens": 0}


def test_scenario_complet_recherche_puis_reponse():
    url = OFFRES[0]["url"]
    modele = FauxModele([outil("search_jobs", mots_cles="python", lieu="France"),
                         texte(f"Une offre : [Développeur Python]({url}), source Arbeitnow.")])
    etapes = []
    reponse = boucle.lancer_agent("Offres Python en France", modele, afficher=False, suivi=etapes.append)
    assert url in reponse and "lien retiré" not in reponse
    # Le résultat de l'outil est bien renvoyé au modèle au tour suivant.
    dernier_message = modele.appels_recus[1]["messages"][-1]
    assert dernier_message["role"] == "tool" and url in dernier_message["content"]
    assert [e["nom"] for e in etapes] == ["search_jobs"]


def test_le_garde_fou_retire_un_lien_invente():
    invente = "https://www.arbeitnow.fr/jobs/inventee/offre-123"
    modele = FauxModele([outil("search_jobs", mots_cles="python"), texte(f"Voir {invente}")])
    etapes = []
    reponse = boucle.lancer_agent("Offres Python", modele, afficher=False, suivi=etapes.append)
    assert invente not in reponse
    assert etapes[-1] == {"type": "liens_retires", "liens": [invente]}


def test_garde_fou_desactivable(monkeypatch):
    monkeypatch.setattr(boucle, "GARDE_FOU_LIENS", False)
    invente = "https://www.arbeitnow.fr/jobs/inventee/offre-123"
    modele = FauxModele([texte(f"Voir {invente}")])
    assert invente in boucle.lancer_agent("Offres", modele, afficher=False)


def test_au_dela_de_3_recherches_la_recherche_est_refusee():
    modele = FauxModele([outil("search_jobs", n=i, mots_cles="python") for i in range(1, 5)] + [texte("Fini")])
    etapes = []
    boucle.lancer_agent("Offres", modele, afficher=False, suivi=etapes.append)
    assert len(etapes) == 4
    assert etapes[3]["resultat"].startswith("Limite de recherches atteinte")


def test_derniere_etape_reponse_forcee_sans_outils():
    # Un modèle qui demanderait des outils indéfiniment est obligé de conclure.
    reponses = [outil("get_job_details", n=i, id_offre=OFFRES[0]["id"]) for i in range(boucle.MAX_ETAPES - 1)]
    modele = FauxModele(reponses + [texte("Réponse finale")])
    assert boucle.lancer_agent("Offres", modele, afficher=False) == "Réponse finale"
    assert modele.appels_recus[-1]["schemas"] == []  # plus aucun outil proposé


def test_cv_fourni_par_l_interface():
    modele = FauxModele([outil("read_cv"), texte("Profil lu")])
    boucle.lancer_agent("Offres pour moi", modele, afficher=False, cv="CV de test : Python, Django")
    assert modele.appels_recus[1]["messages"][-1]["content"] == "CV de test : Python, Django"


def test_memoire_courte_garde_le_cv(monkeypatch):
    monkeypatch.setattr(boucle, "TAILLE_MAX_HISTORIQUE", 1_000)
    cv = "CV " + "x" * 800
    modele = FauxModele([outil("read_cv"), outil("get_job_details", id_offre=OFFRES[0]["id"]),
                         outil("search_jobs", mots_cles="python " * 50), texte("ok")])
    boucle.lancer_agent("Offres pour moi", modele, afficher=False, cv=cv)
    messages_outils = [m for m in modele.appels_recus[-1]["messages"] if m["role"] == "tool"]
    assert messages_outils[0]["content"] == cv  # le CV n'est jamais raccourci


# --- Mémoire de conversation ------------------------------------------------------

def test_deuxieme_demande_voit_la_premiere_et_les_offres_trouvees():
    conversation = boucle.Conversation()
    url = OFFRES[0]["url"]
    premier = FauxModele([outil("search_jobs", mots_cles="python", lieu="France"),
                          texte(f"1. [Développeur Python]({url})")])
    boucle.lancer_agent("Offres Python en France", premier, afficher=False, conversation=conversation)

    second = FauxModele([texte("Détail de la 1re")])
    boucle.lancer_agent("Parle-moi de la 1re", second, afficher=False, conversation=conversation)
    messages = second.appels_recus[0]["messages"]
    contenus = [m["content"] for m in messages]
    assert any(OFFRES[0]["id"] in c and url in c for c in contenus if c)  # liste des offres vues
    assert [m["content"] for m in messages if m["role"] == "user"] == ["Offres Python en France", "Parle-moi de la 1re"]


def test_le_garde_fou_accepte_un_lien_trouve_lors_d_une_demande_precedente():
    conversation = boucle.Conversation()
    url = OFFRES[0]["url"]
    boucle.lancer_agent("Offres", FauxModele([outil("search_jobs", mots_cles="python"), texte("ok")]),
                        afficher=False, conversation=conversation)
    # Seconde demande sans aucun appel d'outil : le lien vient de la mémoire.
    reponse = boucle.lancer_agent("Redonne le lien de la 1re", FauxModele([texte(f"Le voici : {url}")]),
                                  afficher=False, conversation=conversation)
    assert url in reponse and "lien retiré" not in reponse


def test_memoire_bornee():
    conversation = boucle.Conversation()
    for i in range(5):
        conversation.ajouter_echange(f"Question {i}", "x" * 10_000)
    assert [q for q, _ in conversation.echanges] == ["Question 3", "Question 4"]
    assert all(len(m["content"]) < 3_100 for m in conversation.messages())

    nombreuses = [{"id": f"arbeitnow:{i}", "titre": "t", "entreprise": "e", "lieu": "l", "url": f"https://x/{i}"}
                  for i in range(40)]
    conversation.noter_resultat("search_jobs", json.dumps(nombreuses))
    assert len(conversation.offres_vues) == boucle.Conversation.MAX_OFFRES
    assert "arbeitnow:39" in conversation.offres_vues  # les plus récentes sont gardées


def test_memoire_ignore_les_resultats_sans_offre():
    conversation = boucle.Conversation()
    conversation.noter_resultat("read_cv", "CV")
    conversation.noter_resultat("search_jobs", "Limite de recherches atteinte.")
    conversation.noter_resultat("get_job_details", json.dumps({"erreur": "Aucune offre"}))
    assert conversation.offres_vues == {}


def test_sans_conversation_chaque_demande_est_independante():
    modele = FauxModele([texte("a"), texte("b")])
    boucle.lancer_agent("Première", modele, afficher=False)
    boucle.lancer_agent("Seconde", modele, afficher=False)
    assert [m["role"] for m in modele.appels_recus[1]["messages"]] == ["system", "user"]
