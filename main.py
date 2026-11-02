"""Point d'entrée en ligne de commande.

Exemples :
    .venv/bin/python main.py "Trouve des offres Python en France qui correspondent à mon CV"
    .venv/bin/python main.py              (mode conversation)
    .venv/bin/python main.py --verifier   (vérifie l'environnement)
    .venv/bin/python main.py --ollama "…" (force le modèle local)
"""

import argparse

from agent import config


def verifier_groq() -> str:
    if not config.GROQ_API_KEY:
        return "clé absente dans .env"
    from groq import Groq

    reponse = Groq(api_key=config.GROQ_API_KEY).chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[{"role": "user", "content": "Réponds juste : OK"}],
    )
    return f"OK ({config.GROQ_MODEL}) → {reponse.choices[0].message.content.strip()}"


def verifier_ollama() -> str:
    import ollama

    modeles = [m.model for m in ollama.list().models]
    if config.OLLAMA_MODEL in modeles:
        return f"OK ({config.OLLAMA_MODEL})"
    return f"Ollama tourne, mais {config.OLLAMA_MODEL} n'est pas installé (présents : {modeles})"


def verifier_arbeitnow() -> str:
    from agent.outils import _offres_arbeitnow

    return f"OK ({len(_offres_arbeitnow())} offres disponibles, cache de 6 h)"


def verifier_remotive() -> str:
    # Passe par le cache : Remotive demande max. 4 appels par jour.
    from agent.outils import _offres_remotive

    return f"OK ({len(_offres_remotive())} offres en télétravail, cache de 6 h)"


def verifier_adzuna() -> str:
    if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
        return "pas encore configuré (prévu plus tard, optionnel)"
    import requests

    reponse = requests.get(
        "https://api.adzuna.com/v1/api/jobs/fr/search/1",
        params={
            "app_id": config.ADZUNA_APP_ID,
            "app_key": config.ADZUNA_APP_KEY,
            "what": "python",
            "results_per_page": 1,
        },
        timeout=15,
    )
    reponse.raise_for_status()
    return f"OK ({reponse.json()['count']} offres « python » en France)"


def verifier_cv() -> str:
    if not config.CV_PATH.exists():
        return f"à déposer : {config.CV_PATH} introuvable"
    from pypdf import PdfReader

    pages = PdfReader(config.CV_PATH).pages
    texte = "".join(page.extract_text() or "" for page in pages)
    return f"OK ({len(pages)} page(s), {len(texte)} caractères lus)"


def verifier() -> None:
    for nom, test in [
        ("Groq", verifier_groq),
        ("Ollama", verifier_ollama),
        ("Arbeitnow", verifier_arbeitnow),
        ("Remotive", verifier_remotive),
        ("Adzuna", verifier_adzuna),
        ("CV", verifier_cv),
    ]:
        try:
            print(f"{nom} : {test()}")
        except Exception as erreur:
            print(f"{nom} : ÉCHEC ({erreur})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent de veille d'offres d'emploi")
    parser.add_argument("question", nargs="?", help="Ta demande (sinon : mode conversation)")
    parser.add_argument("--verifier", action="store_true", help="Vérifie l'environnement")
    parser.add_argument("--ollama", action="store_true", help="Utilise le modèle local Ollama")
    args = parser.parse_args()

    if args.verifier:
        verifier()
        return

    from agent.boucle import lancer_agent
    from agent.modele import Modele

    modele = Modele("ollama" if args.ollama else "groq")
    print(f"Modèle : {modele.nom}")
    questions = [args.question] if args.question else None
    while True:
        question = questions.pop() if questions else input("\nTa demande (vide pour quitter) : ").strip()
        if not question:
            break
        print()
        print(lancer_agent(question, modele))
        if args.question:
            break


if __name__ == "__main__":
    main()
