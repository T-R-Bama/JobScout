"""Appel au modèle : Groq par défaut, Ollama en secours local.

Les deux fournisseurs savent appeler des outils, mais avec des formats un peu
différents. Ce module cache ces différences : la boucle de l'agent garde
l'historique au format OpenAI (celui de Groq) et reçoit toujours une réponse
de la même forme : {"texte": ..., "appels": [{"id", "nom", "arguments"}]}.
"""

import json
import time

from agent import config

ATTENTE_MAX_SECONDES = 30


def _appeler_groq(messages: list[dict], schemas: list[dict]) -> dict:
    from groq import Groq

    options = {"tools": schemas} if schemas else {}
    reponse = Groq(api_key=config.GROQ_API_KEY).chat.completions.create(
        model=config.GROQ_MODEL, messages=messages, temperature=0.2, **options,
    )
    message = reponse.choices[0].message
    return {
        "texte": message.content or "",
        "appels": [
            {"id": a.id, "nom": a.function.name, "arguments": json.loads(a.function.arguments or "{}")}
            for a in message.tool_calls or []
        ],
        "tokens": reponse.usage.total_tokens,
    }


def _vers_format_ollama(messages: list[dict]) -> list[dict]:
    """Ollama attend des arguments en dict et le nom de l'outil dans ses réponses."""
    noms_par_id = {}
    convertis = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            appels = []
            for a in m["tool_calls"]:
                noms_par_id[a["id"]] = a["function"]["name"]
                appels.append({"function": {
                    "name": a["function"]["name"],
                    "arguments": json.loads(a["function"]["arguments"]),
                }})
            convertis.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": appels})
        elif m["role"] == "tool":
            convertis.append({"role": "tool", "content": m["content"], "tool_name": noms_par_id.get(m["tool_call_id"], "")})
        else:
            convertis.append(m)
    return convertis


def _appeler_ollama(messages: list[dict], schemas: list[dict]) -> dict:
    import ollama

    # Sans « réflexion » (think) et avec une longueur plafonnée : en évaluation, qwen3
    # a déjà réfléchi 19 minutes (43 000 tokens) pour finir sur une réponse vide.
    reponse = ollama.chat(
        model=config.OLLAMA_MODEL, messages=_vers_format_ollama(messages), tools=schemas or None,
        think=False, options={"temperature": 0.2, "num_predict": 2048},
    )
    message = reponse.message
    return {
        "texte": message.content or "",
        "appels": [
            {"id": f"ollama_{i}", "nom": a.function.name, "arguments": dict(a.function.arguments)}
            for i, a in enumerate(message.tool_calls or [])
        ],
        "tokens": (reponse.prompt_eval_count or 0) + (reponse.eval_count or 0),
    }


class Modele:
    """Choisit le fournisseur et bascule sur Ollama si Groq échoue."""

    def __init__(self, fournisseur: str = "groq"):
        self.fournisseur = fournisseur if config.GROQ_API_KEY else "ollama"
        self.tokens = 0  # total consommé, utile pour suivre les limites de Groq
        self.erreur_groq = ""  # raison de la dernière bascule sur Ollama, pour l'interface

    @property
    def nom(self) -> str:
        return config.GROQ_MODEL if self.fournisseur == "groq" else config.OLLAMA_MODEL

    def repondre(self, messages: list[dict], schemas: list[dict]) -> dict:
        reponse = self._repondre(messages, schemas)
        self.tokens += reponse["tokens"]
        return reponse

    def _repondre(self, messages: list[dict], schemas: list[dict]) -> dict:
        if self.fournisseur == "groq":
            from groq import BadRequestError, RateLimitError

            for essai in range(3):
                try:
                    return _appeler_groq(messages, schemas)
                except BadRequestError as erreur:
                    # Raté ponctuel du modèle (ex. nom d'outil mal écrit) : on réessaie.
                    if "tool_use_failed" not in str(erreur) or essai == 2:
                        self.erreur_groq = str(erreur)
                        print(f"  ⚠️  Groq a refusé la requête ({erreur}), bascule sur Ollama.")
                        break
                    print("  🔁 Appel d'outil mal formé par le modèle, nouvel essai.")
                except RateLimitError as erreur:
                    # Limite de tokens par minute : on attend le délai indiqué par Groq.
                    attente = float(erreur.response.headers.get("retry-after", 10))
                    if essai == 2 or attente > ATTENTE_MAX_SECONDES:
                        self.erreur_groq = f"limite de Groq atteinte, réessayer dans {attente:.0f} s"
                        print("  ⚠️  Limite Groq atteinte, bascule sur Ollama.")
                        break
                    print(f"  ⏳ Limite Groq atteinte, nouvel essai dans {attente:.0f} s.")
                    time.sleep(attente)
                except Exception as erreur:
                    self.erreur_groq = f"{erreur.__class__.__name__}: {erreur}"
                    print(f"  ⚠️  Groq indisponible ({erreur}), bascule sur Ollama.")
                    break
            self.fournisseur = "ollama"
        return _appeler_ollama(messages, schemas)
