"""Données de test communes : quelques offres fictives, sans réseau ni LLM."""

import pytest

from agent import config, outils

OFFRES = [
    {"id": "arbeitnow:dev-python-paris", "source": "Arbeitnow", "titre": "Développeur Python",
     "entreprise": "Margo", "lieu": "Paris", "teletravail": False, "date": "2026-11-01",
     "tags": ["python", "django"], "url": "https://www.arbeitnow.fr/jobs/margo/dev-python-paris",
     "description": "Backend Python, Django et PostgreSQL."},
    {"id": "arbeitnow:devops-london", "source": "Arbeitnow", "titre": "DevOps Engineer",
     "entreprise": "Acme", "lieu": "London", "teletravail": False, "date": "2026-10-30",
     "tags": ["kubernetes"], "url": "https://www.arbeitnow.co.uk/jobs/acme/devops-london",
     "description": "Kubernetes, Terraform, AWS."},
    {"id": "arbeitnow:data-zurich", "source": "Arbeitnow", "titre": "Data Scientist",
     "entreprise": "Helvetia", "lieu": "Zürich", "teletravail": False, "date": "2026-10-29",
     "tags": ["python", "machine learning"], "url": "https://www.arbeitnow.ch/jobs/helvetia/data-zurich",
     "description": "Machine learning en Python."},
    {"id": "arbeitnow:pm-berlin", "source": "Arbeitnow", "titre": "Product Manager",
     "entreprise": "Zalando", "lieu": "Berlin", "teletravail": False, "date": "2026-10-28",
     "tags": ["product"], "url": "https://www.arbeitnow.com/jobs/zalando/pm-berlin",
     "description": "Maintain the product roadmap."},
    {"id": "remotive:42", "source": "Remotive", "titre": "Senior Python Developer",
     "entreprise": "Remote Co", "lieu": "Worldwide", "teletravail": True, "date": "2026-11-02",
     "tags": ["python", "fastapi"], "url": "https://remotive.com/remote-jobs/software-dev/senior-python-42",
     "description": "Python et FastAPI, 100 % à distance."},
]


@pytest.fixture(autouse=True)
def offres_fictives(monkeypatch):
    """Remplace les vraies sources par les offres ci-dessus et désactive Adzuna."""
    monkeypatch.setattr(outils, "_toutes_les_offres", lambda: [dict(o) for o in OFFRES])
    monkeypatch.setattr(config, "ADZUNA_APP_ID", "")
    monkeypatch.setattr(config, "ADZUNA_APP_KEY", "")
    return OFFRES
