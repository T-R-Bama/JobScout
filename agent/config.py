"""Lecture de la configuration depuis le fichier .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()  # un espace collé avec la clé fait échouer l'appel
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

CV_PATH = RACINE / os.getenv("CV_PATH", "data/cv.pdf")

# Les offres téléchargées sont gardées 6 h (Remotive demande max. 4 appels par jour).
CACHE_DIR = RACINE / "data" / "cache"
CACHE_DUREE_SECONDES = 6 * 60 * 60
