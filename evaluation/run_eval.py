"""Évaluation de l'agent de veille d'offres d'emploi.

Pour que les résultats soient reproductibles, l'agent travaille sur des offres figées
(`offres_figees/`) et sur un CV fictif (`cv_test.md`), jamais sur les données du jour
ni sur le vrai CV. Adzuna est désactivé pendant l'évaluation (ses résultats changent).

Toutes les métriques sont déterministes : elles comparent la réponse et les appels
d'outils de l'agent à la vérité connue (pays réel des offres, liens existants…).

Exemples :
    .venv/bin/python evaluation/run_eval.py --recherche-seule          (outil de recherche seul, sans LLM)
    .venv/bin/python evaluation/run_eval.py --ancien-filtre --label groq-avant
    .venv/bin/python evaluation/run_eval.py --label groq-apres
    .venv/bin/python evaluation/run_eval.py --ollama --label ollama-apres
    .venv/bin/python evaluation/run_eval.py --questions cv-france boulanger-marseille
    .venv/bin/python evaluation/run_eval.py --rapport   (régénère RESULTS.md seulement)
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))

from agent import boucle, config, outils  # noqa: E402
from agent.modele import Modele  # noqa: E402

DOSSIER_RESULTATS = ICI / "results"

# Pays réel d'une offre, d'après le site d'origine (vérité terrain, indépendante de l'agent).
PAYS_PAR_DOMAINE = {
    "www.arbeitnow.fr": "France",
    "www.arbeitnow.co.uk": "Royaume-Uni",
    "www.arbeitnow.ch": "Suisse",
    "www.arbeitnow.nl": "Pays-Bas",
}


def figer_environnement() -> None:
    config.CACHE_DIR = ICI / "offres_figees"
    config.CACHE_DUREE_SECONDES = float("inf")
    config.CV_PATH = ICI / "cv_test.md"
    config.ADZUNA_APP_ID = config.ADZUNA_APP_KEY = ""


def activer_ancien_filtre() -> None:
    """Remet le filtre de lieu d'origine, pour mesurer l'effet du correctif.

    Avant : le lieu demandé devait apparaître tel quel dans le lieu de l'offre
    (« France » ne trouvait pas « Paris »), et le télétravail ne se fiait qu'au
    champ « remote » de l'API.
    """
    outils._au_bon_endroit = lambda offre, lieu: lieu.lower() in offre["lieu"].lower()
    outils._en_teletravail = lambda offre: offre["teletravail"]
    outils._pays = lambda offre: ""


def evaluer_recherche(questions: list[dict], variante: str) -> dict:
    """Teste l'outil search_jobs seul, avec une recherche « idéale » par question."""
    resultats = []
    for q in questions:
        trouves = outils.chercher_offres(**q["recherche_type"], max_resultats=5)
        offres = [OFFRES_PAR_ID[o["id"]] for o in trouves]
        # Couverture du filtre : parmi les offres vraiment au bon endroit, combien passe-t-il ?
        rt = q["recherche_type"]
        au_bon_endroit = [o for o in OFFRES_PAR_ID.values() if respecte_contrainte(o, q)]
        visibles = [o for o in au_bon_endroit
                    if (not rt.get("lieu") or outils._au_bon_endroit(o, rt["lieu"]))
                    and (not rt.get("teletravail_seulement") or outils._en_teletravail(o))]
        resultats.append({
            "id": q["id"], "recherche": q["recherche_type"], "resultats": [o["id"] for o in offres],
            "couverture": [len(visibles), len(au_bon_endroit)],
            "attendue_top5": None if q.get("aucune_offre") else any(o["id"] in q["offres_attendues"] for o in offres),
            "bon_endroit": [respecte_contrainte(o, q) for o in offres],
        })
    return {"variante": variante, "resultats": resultats}


def respecte_contrainte(offre: dict, q: dict) -> bool:
    if q.get("pays"):
        pays = PAYS_PAR_DOMAINE.get(urlparse(offre["url"]).netloc, "")
        if pays != q["pays"]:
            return False
    if q.get("ville") and q["ville"].lower() not in offre["lieu"].lower():
        return False
    if q.get("teletravail") and not (offre["teletravail"] or "remote" in offre["lieu"].lower()):
        return False
    return True


extraire_liens = boucle.extraire_liens


def evaluer_question(q: dict, modele: Modele, offres_par_url: dict) -> dict:
    appels = []
    executer_original = outils.executer

    def executer_espion(nom, arguments):
        resultat = executer_original(nom, arguments)
        appels.append({"nom": nom, "arguments": arguments})
        return resultat

    # On garde aussi la réponse brute du modèle, avant que le garde-fou ne retire des liens.
    brute = {}
    verifier_original = boucle.verifier_liens

    def verifier_espion(texte, liens_connus):
        brute["texte"] = texte
        return verifier_original(texte, liens_connus)

    boucle.outils.executer = executer_espion
    boucle.verifier_liens = verifier_espion
    tokens_avant = modele.tokens
    debut = time.time()
    try:
        reponse = boucle.lancer_agent(q["question"], modele, afficher=False)
        erreur = ""
    except Exception as e:  # une erreur compte comme un échec, sans arrêter l'évaluation
        reponse, erreur = "", f"{e.__class__.__name__}: {e}"
    finally:
        boucle.outils.executer = executer_original
        boucle.verifier_liens = verifier_original
    duree = time.time() - debut

    liens = extraire_liens(reponse)
    liens_bruts = extraire_liens(brute.get("texte", reponse))
    citees = [offres_par_url[lien] for lien in liens if lien in offres_par_url]
    noms = [a["nom"] for a in appels]

    r = {
        "id": q["id"], "question": q["question"], "reponse": reponse, "erreur": erreur,
        "appels": appels, "liens": liens,
        "liens_retires": [lien for lien in liens_bruts if lien not in liens], "offres_citees": [o["id"] for o in citees],
        "duree_s": round(duree, 1), "tokens": modele.tokens - tokens_avant,
        "recherches": noms.count("search_jobs"), "appels_outils": len(appels),
        "fournisseur_final": modele.fournisseur,
        # Métriques (None = ne s'applique pas à cette question)
        "repond": bool(reponse.strip()),
        "cv_bien_utilise": ("read_cv" in noms) == q["doit_lire_cv"],
        "detail_lu": None,
        # Le modèle lui-même n'a cité que des liens existants (avant le garde-fou)…
        "liens_tous_valides": all(lien in offres_par_url for lien in liens_bruts),
        # … et la réponse affichée à l'utilisateur n'en contient aucun d'inventé (après le garde-fou).
        "liens_affiches_valides": all(lien in offres_par_url for lien in liens),
        "contrainte_respectee": None,
        "offre_attendue_trouvee": None,
        "honnete_si_aucune_offre": None,
        "source_citee": None,
    }
    if q.get("doit_lire_detail"):
        r["detail_lu"] = any(a["nom"] == "get_job_details" and a["arguments"].get("id_offre") in q["offres_attendues"]
                             for a in appels)
    if q.get("aucune_offre"):
        r["honnete_si_aucune_offre"] = not citees
    else:
        r["offre_attendue_trouvee"] = any(o["id"] in q["offres_attendues"] for o in citees)
        if citees:
            r["contrainte_respectee"] = all(respecte_contrainte(o, q) for o in citees)
            r["source_citee"] = all(o["source"].lower() in reponse.lower() for o in citees)
    return r


OFFRES_PAR_ID: dict[str, dict] = {}

METRIQUES = [
    ("repond", "Répond"),
    ("offre_attendue_trouvee", "Offre pertinente trouvée"),
    ("contrainte_respectee", "Lieu / télétravail respecté"),
    ("liens_tous_valides", "Aucun lien inventé par le modèle"),
    ("liens_affiches_valides", "Aucun lien inventé affiché"),
    ("source_citee", "Source citée"),
    ("cv_bien_utilise", "CV lu à bon escient"),
    ("detail_lu", "Détail de l'offre lu"),
    ("honnete_si_aucune_offre", "N'invente pas d'offre"),
]


def taux(resultats: list[dict], cle: str) -> str:
    valeurs = [r.get(cle) for r in resultats if r.get(cle) is not None]  # absente des vieilles exécutions
    if not valeurs:
        return "–"
    return f"{100 * sum(valeurs) / len(valeurs):.0f} % ({sum(valeurs)}/{len(valeurs)})"


def ecrire_rapport() -> None:
    tous = sorted(DOSSIER_RESULTATS.glob("*.json"), key=lambda f: f.stat().st_mtime)
    fichiers = [f for f in tous if not f.name.startswith("recherche-")]
    nb_questions = len(json.loads((ICI / "questions.json").read_text()))
    lignes = [
        "# Résultats de l'évaluation", "",
        "Généré par `evaluation/run_eval.py`. Voir `evaluation/README.md` pour la méthode.", "",
        "## Outil de recherche seul (sans LLM)", "",
        "| Filtre de lieu | Offres du bon lieu visibles par le filtre | Offre attendue dans le top 5"
        " | Résultats au bon endroit | Résultats pour « boulanger à Marseille » |",
        "|---|---|---|---|---|",
    ]
    for f in [f for f in tous if f.name.startswith("recherche-")]:
        run = json.loads(f.read_text())
        res = run["resultats"]
        attendues = [r["attendue_top5"] for r in res if r["attendue_top5"] is not None]
        endroits = [b for r in res for b in r["bon_endroit"]]
        boulanger = next((len(r["resultats"]) for r in res if r["id"] == "boulanger-marseille"), "–")
        par_filtre = {json.dumps({k: v for k, v in r["recherche"].items() if k != "mots_cles"}, sort_keys=True):
                      r["couverture"] for r in res}  # un filtre présent dans deux questions compte une fois
        vus, total = (sum(c[i] for c in par_filtre.values()) for i in (0, 1))
        lignes.append(f"| {run['variante']} | {100 * vus / total:.0f} % ({vus}/{total})"
                      f" | {100 * sum(attendues) / len(attendues):.0f} % ({sum(attendues)}/{len(attendues)})"
                      f" | {100 * sum(endroits) / max(len(endroits), 1):.0f} % ({sum(endroits)}/{len(endroits)}) | {boulanger} |")
    if any(f.name == "recherche-apres.json" for f in tous):
        lignes += ["", "Détail de la couverture (offres visibles / offres réellement au bon endroit) :", ""]
        avant = {r["id"]: r for r in json.loads((DOSSIER_RESULTATS / "recherche-avant.json").read_text())["resultats"]}
        deja_vus = set()
        for r in json.loads((DOSSIER_RESULTATS / "recherche-apres.json").read_text())["resultats"]:
            filtre = ", ".join(f"{k} = {v}" for k, v in r["recherche"].items() if k != "mots_cles")
            if filtre in deja_vus:
                continue
            deja_vus.add(filtre)
            a, b = avant[r["id"]]["couverture"], r["couverture"]
            lignes.append(f"- `{filtre}` : {a[0]}/{a[1]} avant, {b[0]}/{b[1]} après")
    lignes += [
        "", "## Agent complet", "",
        "| Configuration | " + " | ".join(nom for _, nom in METRIQUES)
        + " | Liens retirés par le garde-fou | Recherches / question | Tokens / question | Temps / question |",
        "|---|" + "---|" * (len(METRIQUES) + 4),
    ]
    details = []
    for fichier in fichiers:
        run = json.loads(fichier.read_text())
        res = run["resultats"]
        n = len(res)
        lignes.append(
            f"| `{run['label']}` ({run['modele']}{'' if n == nb_questions else f', {n}/{nb_questions} questions'}) | "
            + " | ".join(taux(res, cle) for cle, _ in METRIQUES)
            + (f" | {sum(len(r['liens_retires']) for r in res)}" if all("liens_retires" in r for r in res) else " | –")
            + f" | {sum(r['recherches'] for r in res) / n:.1f} | {sum(r['tokens'] for r in res) / n:,.0f}"
            + f" | {sum(r['duree_s'] for r in res) / n:.0f} s |"
        )
        details += ["", f"### `{run['label']}`", ""]
        for r in res:
            echecs = [nom for cle, nom in METRIQUES if r.get(cle) is False]
            statut = "✅" if not echecs else "❌ " + ", ".join(echecs)
            bascule = " (bascule sur Ollama)" if run["modele"].startswith("groq") and r["fournisseur_final"] == "ollama" else ""
            details.append(f"- **{r['question']}** : {statut}{bascule}")
    lignes += ["", "## Détail par question"] + details
    (ICI / "RESULTS.md").write_text("\n".join(lignes) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ollama", action="store_true", help="Évalue le modèle local Ollama")
    parser.add_argument("--label", default="", help="Nom de cette exécution (ex. avant-correctif)")
    parser.add_argument("--questions", nargs="*", help="N'évaluer que ces identifiants de questions")
    parser.add_argument("--rapport", action="store_true", help="Régénère seulement RESULTS.md")
    parser.add_argument("--ancien-filtre", action="store_true", help="Utilise le filtre de lieu d'avant le correctif")
    parser.add_argument("--sans-garde-fou", action="store_true", help="Désactive le garde-fou qui retire les liens inventés")
    parser.add_argument("--recherche-seule", action="store_true", help="Teste l'outil de recherche seul, sans LLM")
    args = parser.parse_args()

    if args.rapport:
        ecrire_rapport()
        return

    figer_environnement()
    questions = json.loads((ICI / "questions.json").read_text())
    if args.questions:
        questions = [q for q in questions if q["id"] in args.questions]
    offres_par_url = {o["url"]: o for o in outils._toutes_les_offres()}
    OFFRES_PAR_ID.update({o["id"]: o for o in outils._toutes_les_offres()})
    DOSSIER_RESULTATS.mkdir(exist_ok=True)

    if args.recherche_seule:
        for variante, ancien in [("avant correctif", True), ("après correctif", False)]:
            if ancien:
                originaux = (outils._au_bon_endroit, outils._en_teletravail, outils._pays)
                activer_ancien_filtre()
            run = evaluer_recherche(questions, variante)
            if ancien:
                outils._au_bon_endroit, outils._en_teletravail, outils._pays = originaux
            nom = "recherche-avant.json" if ancien else "recherche-apres.json"
            (DOSSIER_RESULTATS / nom).write_text(json.dumps(run, ensure_ascii=False, indent=2))
        ecrire_rapport()
        print((ICI / "RESULTS.md").read_text().split("## Agent complet")[0])
        return

    if args.ancien_filtre:
        activer_ancien_filtre()
    if args.sans_garde_fou:
        boucle.GARDE_FOU_LIENS = False

    modele = Modele("ollama" if args.ollama else "groq")
    nom_modele = f"{modele.fournisseur} · {modele.nom}"
    label = args.label or modele.fournisseur
    print(f"Évaluation « {label} » : {len(questions)} questions, {nom_modele}")

    resultats = []
    for q in questions:
        modele.fournisseur = "ollama" if args.ollama else "groq"  # repart de Groq à chaque question
        r = evaluer_question(q, modele, offres_par_url)
        echecs = [nom for cle, nom in METRIQUES if r[cle] is False]
        print(f"  {'✅' if not echecs else '❌'} {q['id']} ({r['duree_s']} s, {r['tokens']} tokens)"
              + (f" : {', '.join(echecs)}" if echecs else "") + (f" [{r['erreur']}]" if r["erreur"] else ""))
        if not args.ollama and r["fournisseur_final"] == "ollama":
            # Quota Groq épuisé : on n'enregistre pas un résultat qui mélange deux modèles.
            print("  ⛔ Groq est passé sur Ollama (quota épuisé ?) : évaluation arrêtée, question non comptée.")
            restantes = [x["id"] for x in questions[len(resultats):]]
            print(f"     Relance plus tard avec : --label {label} --questions {' '.join(restantes)}")
            break
        resultats.append(r)

    fichier = DOSSIER_RESULTATS / f"{re.sub(r'[^a-z0-9-]+', '-', label.lower())}.json"
    if args.questions and fichier.exists():  # reprise : on complète l'exécution précédente
        nouveaux = {r["id"] for r in resultats}
        anciens = [r for r in json.loads(fichier.read_text())["resultats"] if r["id"] not in nouveaux]
        ordre = [q["id"] for q in json.loads((ICI / "questions.json").read_text())]
        resultats = sorted(anciens + resultats, key=lambda r: ordre.index(r["id"]))
    fichier.write_text(json.dumps({"label": label, "modele": nom_modele, "resultats": resultats},
                                  ensure_ascii=False, indent=2))
    ecrire_rapport()
    print(f"Résultats : {fichier.relative_to(ICI.parent)} et evaluation/RESULTS.md")


if __name__ == "__main__":
    main()
