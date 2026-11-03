"""Garde-fou : les liens que le modèle invente sont retirés de la réponse finale."""

from agent.boucle import MENTION_LIEN_RETIRE, extraire_liens, verifier_liens

VRAI = "https://www.arbeitnow.fr/jobs/margo/dev-python-paris"
FAUX = "https://www.arbeitnow.fr/jobs/sfeir/forward-deployed-engineer-266086"


def test_extraire_liens_sans_ponctuation_ni_doublon():
    texte = f"Voir {VRAI}. Et encore {VRAI}, puis [ici]({FAUX})."
    assert extraire_liens(texte) == [VRAI, FAUX]


def test_lien_connu_conserve():
    texte = f"[Développeur Python]({VRAI})"
    assert verifier_liens(texte, {VRAI}) == (texte, [])


def test_lien_invente_retire_partout():
    texte = f"1. [Forward Deployed Engineer]({FAUX})\n2. Lien : {FAUX}.\n3. <{FAUX}>"
    corrige, retires = verifier_liens(texte, {VRAI})
    assert retires == [FAUX]
    assert FAUX not in corrige
    assert "Forward Deployed Engineer " + MENTION_LIEN_RETIRE in corrige  # le titre reste
    assert corrige.count(MENTION_LIEN_RETIRE) == 3
    assert "Liens retirés : 1" in corrige  # l'utilisateur est prévenu


def test_seul_le_lien_invente_est_retire():
    texte = f"[A]({VRAI}) et [B]({FAUX})"
    corrige, retires = verifier_liens(texte, {VRAI})
    assert VRAI in corrige and FAUX not in corrige
    assert retires == [FAUX]


def test_un_lien_plus_long_n_est_pas_confondu_avec_un_lien_connu():
    # Le lien connu est le début du lien inventé : il ne doit pas le « valider ».
    invente = VRAI + "-bis"
    corrige, retires = verifier_liens(f"Voir {invente}", {VRAI})
    assert retires == [invente]


def test_page_d_accueil_autorisee():
    texte = "Source : Remotive (https://remotive.com)"
    assert verifier_liens(texte, set()) == (texte, [])
