"""Les outils que l'agent peut appeler, et leur description pour le modèle.

Chaque outil est une fonction Python ordinaire qui renvoie du texte (ou un dict
transformé en JSON). Le modèle ne fait que *demander* un appel : c'est la boucle
de l'agent qui exécute la fonction et lui renvoie le résultat.
"""

import hashlib
import html
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from agent import config

URL_ARBEITNOW = "https://www.arbeitnow.com/api/job-board-api"
URL_REMOTIVE = "https://remotive.com/api/remote-jobs"
URL_ADZUNA = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
PAGES_ARBEITNOW = 3  # 300 offres par page


# --- Téléchargement des offres, avec cache sur disque -----------------------


def _lire_cache(nom: str) -> list[dict] | None:
    fichier = config.CACHE_DIR / f"{nom}.json"
    if not fichier.exists():
        return None
    contenu = json.loads(fichier.read_text())
    if time.time() - contenu["horodatage"] > config.CACHE_DUREE_SECONDES:
        return None
    return contenu["offres"]


def _ecrire_cache(nom: str, offres: list[dict]) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fichier = config.CACHE_DIR / f"{nom}.json"
    fichier.write_text(json.dumps({"horodatage": time.time(), "offres": offres}))


def _texte_brut(code_html: str) -> str:
    """Retire les balises HTML d'une description d'offre."""
    texte = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", code_html)
    texte = re.sub(r"<[^>]+>", "", texte)
    texte = html.unescape(texte)
    return re.sub(r"\n\s*\n+", "\n\n", texte).strip()


def _offres_arbeitnow() -> list[dict]:
    offres = _lire_cache("arbeitnow")
    if offres is not None:
        return offres
    offres = []
    for page in range(1, PAGES_ARBEITNOW + 1):
        reponse = requests.get(URL_ARBEITNOW, params={"page": page}, timeout=20)
        reponse.raise_for_status()
        for o in reponse.json()["data"]:
            offres.append({
                "id": f"arbeitnow:{o['slug']}",
                "source": "Arbeitnow",
                "titre": o["title"],
                "entreprise": o["company_name"],
                "lieu": o["location"],
                "teletravail": bool(o["remote"]),
                "date": datetime.fromtimestamp(o["created_at"], timezone.utc).date().isoformat(),
                "tags": o["tags"] + o["job_types"],
                "url": o["url"],
                "description": _texte_brut(o["description"]),
            })
    _ecrire_cache("arbeitnow", offres)
    return offres


def _offres_remotive() -> list[dict]:
    offres = _lire_cache("remotive")
    if offres is not None:
        return offres
    reponse = requests.get(URL_REMOTIVE, timeout=30)
    reponse.raise_for_status()
    offres = [
        {
            "id": f"remotive:{o['id']}",
            "source": "Remotive",
            "titre": o["title"],
            "entreprise": o["company_name"],
            "lieu": o["candidate_required_location"],
            "teletravail": True,
            "date": o["publication_date"][:10],
            "tags": o["tags"] + [o["category"], o["job_type"]],
            "url": o["url"],
            "salaire": o.get("salary", ""),
            "description": _texte_brut(o["description"]),
        }
        for o in reponse.json()["jobs"]
    ]
    _ecrire_cache("remotive", offres)
    return offres


def _offres_adzuna(mots_cles: str, lieu: str) -> list[dict]:
    """Interroge Adzuna (offres en France). Désactivé tant que les clés sont absentes.

    Contrairement aux deux autres sources, Adzuna est un moteur de recherche :
    on l'appelle à chaque recherche, avec un cache par couple (mots-clés, lieu).
    """
    if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
        return []
    cle = hashlib.md5(f"{mots_cles.lower()}|{lieu.lower()}".encode()).hexdigest()[:12]
    offres = _lire_cache(f"adzuna-{cle}")
    if offres is None:
        params = {
            "app_id": config.ADZUNA_APP_ID, "app_key": config.ADZUNA_APP_KEY,
            "what": mots_cles, "results_per_page": 20, "content-type": "application/json",
        }
        if lieu and lieu.lower() != "france":  # l'API Adzuna utilisée ne couvre que la France
            params["where"] = lieu
        reponse = requests.get(URL_ADZUNA, params=params, timeout=20)
        reponse.raise_for_status()
        offres = [
            {
                "id": f"adzuna:{o['id']}",
                "source": "Adzuna",
                "titre": _texte_brut(o["title"]),
                "entreprise": o.get("company", {}).get("display_name", ""),
                "lieu": o.get("location", {}).get("display_name", "") + ", France",
                "teletravail": False,
                "date": o.get("created", "")[:10],
                "tags": [o.get("category", {}).get("label", ""), o.get("contract_type", ""),
                         o.get("contract_time", "")],
                "url": o["redirect_url"],
                "salaire": f"{o['salary_min']:.0f}–{o.get('salary_max', o['salary_min']):.0f} €"
                           if o.get("salary_min") else "",
                "description": _texte_brut(o.get("description", "")) + " (extrait : annonce complète sur le lien)",
            }
            for o in reponse.json()["results"]
        ]
        _ecrire_cache(f"adzuna-{cle}", offres)
    _ADZUNA_VUES.update({o["id"]: o for o in offres})
    return offres


# Offres Adzuna déjà renvoyées, pour que get_job_details les retrouve.
_ADZUNA_VUES: dict[str, dict] = {}


def _toutes_les_offres() -> list[dict]:
    return _offres_arbeitnow() + _offres_remotive()


# Le lieu d'une offre Arbeitnow ne cite souvent que la ville (« Paris »), mais le site
# d'origine indique le pays de façon fiable.
PAYS_PAR_DOMAINE = {
    "www.arbeitnow.fr": "France",
    "www.arbeitnow.co.uk": "Royaume-Uni",
    "www.arbeitnow.ch": "Suisse",
    "www.arbeitnow.nl": "Pays-Bas",
}
NOMS_DE_PAYS = {
    "France": ["france"],
    "Royaume-Uni": ["royaume-uni", "royaume uni", "uk", "united kingdom", "angleterre", "england", "great britain"],
    "Suisse": ["suisse", "switzerland", "schweiz"],
    "Pays-Bas": ["pays-bas", "pays bas", "netherlands", "nederland", "holland", "hollande"],
}


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower()) if unicodedata.category(c) != "Mn")


def _pays(offre: dict) -> str:
    if offre["source"] == "Adzuna":
        return "France"
    return PAYS_PAR_DOMAINE.get(urlparse(offre["url"]).netloc, "")


def _au_bon_endroit(offre: dict, lieu: str) -> bool:
    """Vrai si l'offre correspond au lieu demandé : ville, région ou pays."""
    lieu = _sans_accents(lieu.strip())
    if lieu in _sans_accents(offre["lieu"]):
        return True
    pays = _pays(offre)
    return bool(pays) and lieu in NOMS_DE_PAYS[pays]


def _en_teletravail(offre: dict) -> bool:
    texte = _sans_accents(offre["lieu"] + " " + offre["titre"])
    return offre["teletravail"] or "remote" in texte or "teletravail" in texte


def _contient(texte: str, mot: str) -> bool:
    """Vrai si le mot apparaît en entier (« ai » ne doit pas trouver « maintain »)."""
    return re.search(rf"\b{re.escape(mot)}\b", texte) is not None


# --- Les outils -------------------------------------------------------------


def chercher_offres(mots_cles: str, lieu: str = "", teletravail_seulement: bool = False,
                    max_resultats: int = 5) -> list[dict]:
    """Cherche des offres et les classe : d'abord celles qui contiennent le plus de
    mots-clés différents, puis par pertinence (titre > tags > description)."""
    mots = [m for m in re.split(r"\W+", mots_cles.lower()) if len(m) > 1]
    resultats = []
    for offre in _toutes_les_offres() + _offres_adzuna(mots_cles, lieu):
        if teletravail_seulement and not _en_teletravail(offre):
            continue
        if lieu and not _au_bon_endroit(offre, lieu):
            continue
        titre = offre["titre"].lower()
        tags = " ".join(offre["tags"]).lower()
        description = offre["description"].lower()
        points = [3 * _contient(titre, m) + 2 * _contient(tags, m) + _contient(description, m) for m in mots]
        mots_trouves = sum(p > 0 for p in points)
        if mots_trouves:
            resultats.append(((mots_trouves, sum(points), offre["date"]), offre))
    resultats.sort(key=lambda r: r[0], reverse=True)
    # Résultat volontairement compact (le modèle gratuit de Groq a une petite limite
    # de tokens), mais avec le vrai lien pour que le modèle n'ait pas à l'inventer.
    return [
        {"id": offre["id"], "source": offre["source"], "titre": offre["titre"], "entreprise": offre["entreprise"],
         "lieu": offre["lieu"], "pays": _pays(offre), "teletravail": _en_teletravail(offre),
         "date": offre["date"], "url": offre["url"]}
        for _, offre in resultats[:min(max_resultats, 10)]
    ]


def lire_offre(id_offre: str) -> dict:
    """Renvoie le détail complet d'une offre trouvée avec chercher_offres."""
    for offre in _toutes_les_offres() + list(_ADZUNA_VUES.values()):
        if offre["id"] == id_offre:
            return {**offre, "description": offre["description"][:2500]}
    return {"erreur": f"Aucune offre avec l'identifiant {id_offre}."}


def texte_du_pdf(fichier) -> str:
    """Texte d'un PDF (chemin ou fichier déjà ouvert, comme un fichier envoyé sur l'interface)."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(fichier).pages)


def lire_cv() -> str:
    """Renvoie le texte du CV de l'utilisateur."""
    if not config.CV_PATH.exists():
        return f"Erreur : CV introuvable ({config.CV_PATH})."
    if config.CV_PATH.suffix.lower() in (".md", ".txt"):
        return config.CV_PATH.read_text()
    return texte_du_pdf(config.CV_PATH)


# --- Description des outils pour le modèle (format « function calling ») -----

# Les noms vus par le modèle sont en anglais : gpt-oss déforme les noms français
# (« lire_offre » devenait « ler_offre » ou « leer_offre »).
OUTILS = {
    "search_jobs": chercher_offres,
    "get_job_details": lire_offre,
    "read_cv": lire_cv,
}

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": (
                "Cherche des offres d'emploi sur Arbeitnow (Europe, dont la France) et Remotive (télétravail)"
                # Adzuna n'est cité que s'il est actif : sinon le modèle dit l'avoir consulté.
                + (" et Adzuna (France)" if config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY else "")
                + ". Les offres sont surtout en anglais : privilégie "
                "des mots-clés en anglais (ex. 'python developer'), et réessaie avec d'autres mots-clés "
                "si les résultats sont maigres. Renvoie une liste résumée (id, source, lien…) ; "
                "la description complète s'obtient avec get_job_details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mots_cles": {"type": "string", "description": "Mots-clés, de préférence en anglais."},
                    "lieu": {"type": "string", "description": "Ville ou pays à filtrer (ex. 'Paris', 'Berlin', 'France', 'Royaume-Uni'). Vide = partout."},
                    "teletravail_seulement": {"type": "boolean", "description": "true pour ne garder que le télétravail."},
                    "max_resultats": {"type": "integer", "description": "Nombre maximum d'offres (défaut 5, max 10)."},
                },
                "required": ["mots_cles"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job_details",
            "description": "Renvoie le détail complet d'une offre (description, tags, salaire…) à partir de son id.",
            "parameters": {
                "type": "object",
                "properties": {"id_offre": {"type": "string", "description": "L'id renvoyé par search_jobs."}},
                "required": ["id_offre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_cv",
            "description": (
                "Renvoie le texte du CV de l'utilisateur. À appeler UNIQUEMENT si la demande parle de son profil "
                "(« pour moi », « mon CV », « qui me correspondent »). Inutile pour une simple recherche d'offres."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def executer(nom: str, arguments: dict) -> str:
    """Exécute un outil demandé par le modèle et renvoie le résultat en texte."""
    if nom not in OUTILS:
        return f"Erreur : l'outil {nom} n'existe pas."
    try:
        resultat = OUTILS[nom](**arguments)
    except Exception as erreur:
        return f"Erreur pendant {nom} : {erreur}"
    return resultat if isinstance(resultat, str) else json.dumps(resultat, ensure_ascii=False)
