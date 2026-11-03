"""Capture d'écran de l'interface pour le README (docs/capture.png).

Pose une vraie question à l'agent dans l'interface locale, déplie ses étapes et
photographie la page en haute résolution. Refuse d'enregistrer la capture si Groq
a basculé sur le modèle local de secours (la démo en ligne utilise Groq).

Prérequis (hors requirements.txt, uniquement pour cet outil) :
    pip install playwright==1.55.0       (utilise le Chrome déjà installé)
Puis, dans un autre terminal, l'interface sans CV local et sans barre d'outils :
    CV_PATH=data/absent.pdf .venv/bin/streamlit run streamlit_app.py --server.port 8504 --client.toolbarMode minimal
Et enfin :
    python docs/capture_ecran.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8504"
QUESTION = "Trouve 3 offres en France qui correspondent à mon CV"
SORTIE = Path(__file__).parent / "capture.png"

with sync_playwright() as p:
    navigateur = p.chromium.launch(channel="chrome")
    page = navigateur.new_page(viewport={"width": 1280, "height": 1150}, device_scale_factor=2)
    page.goto(URL)
    champ = page.get_by_placeholder("Ex. : trouve des offres de data analyst à Lyon")
    champ.wait_for(timeout=60_000)
    champ.fill(QUESTION)
    champ.press("Enter")
    legende = page.get_by_text("Réponse de")
    legende.wait_for(timeout=400_000)
    if "secours" in legende.inner_text():
        raise SystemExit("Groq a basculé sur le modèle local (quota ?) : capture non enregistrée.")
    page.get_by_text("étapes en").click()  # déplie la chronologie des étapes
    page.wait_for_timeout(1500)
    # Streamlit fait défiler la réponse : on remonte en haut de la conversation.
    page.evaluate("document.querySelectorAll('*').forEach(e => { if (e.scrollTop) e.scrollTop = 0; })")
    page.wait_for_timeout(500)
    page.screenshot(path=SORTIE)
    print(f"Capture enregistrée : {SORTIE}")
    navigateur.close()
