"""Outils de l'agent : filtre de lieu, télétravail, recherche, détail d'une offre."""

import json

import pytest

from agent import outils
from tests.conftest import OFFRES

PARIS, LONDRES, ZURICH, BERLIN, REMOTIVE = OFFRES


# --- Filtre de lieu (le bug qui cachait 77 % des offres françaises) -----------

@pytest.mark.parametrize("lieu", ["Paris", "paris", "France", "france"])
def test_offre_parisienne_trouvee_par_ville_ou_par_pays(lieu):
    # Le lieu de l'offre ne dit que « Paris » : le pays vient du site d'origine (.fr).
    assert outils._au_bon_endroit(PARIS, lieu)


@pytest.mark.parametrize("lieu", ["Royaume-Uni", "UK", "united kingdom", "Angleterre"])
def test_pays_ecrit_en_francais_ou_en_anglais(lieu):
    assert outils._au_bon_endroit(LONDRES, lieu)


def test_accents_ignores():
    assert outils._au_bon_endroit(ZURICH, "Zurich")
    assert outils._au_bon_endroit(ZURICH, "Suisse")


def test_mauvais_lieu_refuse():
    assert not outils._au_bon_endroit(PARIS, "Berlin")
    assert not outils._au_bon_endroit(LONDRES, "France")
    # Arbeitnow .com : pays inconnu, seule la ville compte.
    assert not outils._au_bon_endroit(BERLIN, "Allemagne")


def test_pays_deduit_du_site_d_origine():
    assert outils._pays(PARIS) == "France"
    assert outils._pays(LONDRES) == "Royaume-Uni"
    assert outils._pays(BERLIN) == ""
    assert outils._pays({**PARIS, "source": "Adzuna", "url": "https://www.adzuna.fr/x"}) == "France"


def test_teletravail():
    assert outils._en_teletravail(REMOTIVE)
    assert not outils._en_teletravail(PARIS)
    assert outils._en_teletravail({**PARIS, "titre": "Développeur Python (remote)"})


def test_mot_entier_seulement():
    # « ai » ne doit pas trouver « maintain ».
    assert not outils._contient("maintain the product roadmap", "ai")
    assert outils._contient("junior ai consultant", "ai")


# --- Recherche ---------------------------------------------------------------

def test_recherche_filtre_par_pays():
    resultats = outils.chercher_offres("python", lieu="France")
    assert [r["id"] for r in resultats] == [PARIS["id"]]


def test_recherche_teletravail_seulement():
    resultats = outils.chercher_offres("python", teletravail_seulement=True)
    assert [r["id"] for r in resultats] == [REMOTIVE["id"]]


def test_recherche_classe_par_nombre_de_mots_cles_trouves():
    # L'offre Remotive contient « python » et « fastapi » : elle passe devant.
    resultats = outils.chercher_offres("python fastapi")
    assert resultats[0]["id"] == REMOTIVE["id"]
    assert {r["id"] for r in resultats} == {REMOTIVE["id"], PARIS["id"], ZURICH["id"]}


def test_recherche_renvoie_le_vrai_lien():
    # Le lien est fourni pour que le modèle n'ait jamais à l'inventer.
    resultat = outils.chercher_offres("devops", lieu="UK")[0]
    assert resultat["url"] == LONDRES["url"]
    assert resultat["pays"] == "Royaume-Uni"


def test_recherche_sans_resultat():
    assert outils.chercher_offres("boulanger", lieu="Marseille") == []


def test_recherche_limitee_a_10_resultats(monkeypatch):
    nombreuses = [{**PARIS, "id": f"arbeitnow:{i}"} for i in range(30)]
    monkeypatch.setattr(outils, "_toutes_les_offres", lambda: nombreuses)
    assert len(outils.chercher_offres("python", max_resultats=50)) == 10


# --- Détail d'une offre et exécution des outils ------------------------------

def test_lire_offre():
    assert outils.lire_offre(LONDRES["id"])["entreprise"] == "Acme"
    assert "erreur" in outils.lire_offre("arbeitnow:inexistante")


def test_lire_offre_tronque_la_description(monkeypatch):
    longue = {**PARIS, "description": "x" * 10_000}
    monkeypatch.setattr(outils, "_toutes_les_offres", lambda: [longue])
    assert len(outils.lire_offre(PARIS["id"])["description"]) == 2500


def test_executer_renvoie_du_json():
    resultat = json.loads(outils.executer("search_jobs", {"mots_cles": "python", "lieu": "Paris"}))
    assert resultat[0]["id"] == PARIS["id"]


def test_executer_outil_inconnu_ou_arguments_invalides():
    assert "n'existe pas" in outils.executer("ler_offre", {})
    assert outils.executer("search_jobs", {"mauvais_argument": 1}).startswith("Erreur pendant search_jobs")

