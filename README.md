# JobScout : agent de veille d'offres d'emploi

Un agent IA qui **cherche des offres d'emploi, les résume et les compare à ton CV**.
Il décide lui-même quels outils appeler et dans quel ordre. La boucle de l'agent est
codée à la main, sans framework : le modèle choisit un outil, le programme l'exécute,
renvoie le résultat au modèle, et ainsi de suite jusqu'à la réponse finale.

> Projet en cours de construction. Étape actuelle : agent fonctionnel en ligne de commande et dans une interface web Streamlit (en local), avec une évaluation chiffrée.

## Exemple

```
$ .venv/bin/python main.py "Trouve 3 offres en France qui correspondent à mon CV"
  🔧 [1] read_cv({})
  🔧 [2] search_jobs({"mots_cles": "Python developer", "lieu": "France", ...})
  🔧 [3] search_jobs({"mots_cles": "Python web developer", "lieu": "France", ...})
  🔧 [4] search_jobs({"mots_cles": "AI developer", "lieu": "France", ...})
  🔧 [6] get_job_details({"id_offre": "arbeitnow:vo2-force-developpeurse-ia-ai-engineer-..."})
  ...
1️⃣ Développeur(se) IA / AI Engineer – VO2 Group – Paris
Source : Arbeitnow – https://www.arbeitnow.fr/jobs/companies/vo2-group/...
Score d'adéquation : 85 / 100
- Points forts : Python, API d'IA, LangChain/RAG…
- À renforcer : Google Cloud, architecture cloud-native…
```

## Choix techniques

| Élément | Choix |
|---|---|
| Modèle principal | Groq, `openai/gpt-oss-120b` (gratuit, rapide, bon en appel d'outils) |
| Modèle de secours | Ollama en local (`qwen3:8b`), utilisé automatiquement si Groq échoue |
| Sources des offres | Arbeitnow et Remotive (gratuites, sans clé), Adzuna (gratuite, avec clé, offres en France) |
| CV | Fichier PDF lu avec `pypdf` |
| Interface | Terminal, et interface web Streamlit qui montre les étapes de l'agent en direct |

## Les outils de l'agent

| Outil (nom vu par le modèle) | Fonction Python | Rôle |
|---|---|---|
| `search_jobs` | `chercher_offres` | Cherche dans Arbeitnow, Remotive et Adzuna (mots-clés, ville ou pays, télétravail) |
| `get_job_details` | `lire_offre` | Renvoie le détail complet d'une offre |
| `read_cv` | `lire_cv` | Extrait le texte du CV |

La comparaison avec le CV et le score d'adéquation sont faits par le modèle lui-même,
à partir du CV et du détail des offres.

## Ce que j'ai appris en le construisant

Chaque problème rencontré pendant les tests a donné lieu à une correction dans le code :

| Problème observé | Correction |
|---|---|
| Groq gratuit refuse les requêtes de plus de 8 000 tokens, or l'historique grossit à chaque étape | Résultats d'outils compacts et **mémoire courte** : les vieux résultats sont raccourcis (le CV est toujours gardé) |
| Le modèle relançait des recherches sans fin quand les offres étaient rares | Limite de 3 recherches **imposée dans le code**, et réponse forcée à la dernière étape |
| Le modèle inventait des liens vers les offres | Le vrai lien est renvoyé directement dans les résultats de recherche |
| `gpt-oss` déformait les noms d'outils français (`lire_offre` → `ler_offre`) | Noms d'outils en anglais, et nouvel essai automatique si un appel est mal formé |
| Limite de tokens par minute de Groq | Attente du délai indiqué par Groq avant de réessayer, puis bascule sur Ollama |
| Chercher « France » ignorait les offres dont le lieu est seulement « Paris » (77 % des offres françaises invisibles) | Pays déduit du site d'origine, noms de pays en français et en anglais, accents ignorés : trouvé grâce à l'évaluation |
| `qwen3` fabriquait parfois un lien plausible en mélangeant deux offres | **Garde-fou** : tout lien de la réponse finale qu'aucun outil n'a renvoyé est retiré, avec un avertissement |
| Le mode « réflexion » de `qwen3` le bloquait parfois 19 minutes pour une réponse vide | Mode réflexion coupé et longueur des réponses plafonnée |

## Évaluation

L'agent est évalué sur 8 questions (pays, ville, télétravail, CV, offre précise, et une
question sans réponse possible), avec des offres figées et un CV fictif pour que les
résultats soient reproductibles. Toutes les métriques sont déterministes : offre
pertinente trouvée, lieu respecté, aucun lien inventé, source citée, CV lu à bon escient…

| Mesure | Avant correctif | Après correctif |
|---|---|---|
| Offres du bon lieu visibles par l'outil de recherche | 53 % | **100 %** |
| Agent (`qwen3:8b`) : offre pertinente trouvée | 86 % | **100 %** |

| Mesure | Sans garde-fou | Avec garde-fou |
|---|---|---|
| Réponses sans lien inventé affiché | 88 % | **100 %** |

Méthode, résultats et enseignements : [evaluation/README.md](evaluation/README.md)
et [evaluation/RESULTS.md](evaluation/RESULTS.md).

## Conditions d'utilisation des sources

- **Remotive** : chaque offre affichée doit citer Remotive comme source, avec le lien
  vers l'annonce d'origine. L'API ne doit pas être appelée plus de 4 fois par jour
  environ, donc l'agent garde les résultats en cache 6 h. L'API gratuite ne renvoie
  que les 12 dernières offres, avec 24 h de retard.
- **Arbeitnow** : API publique et gratuite, sans clé (environ 900 offres récupérées,
  en cache 6 h). Les offres viennent d'Allemagne, de France (environ 150), du Royaume-Uni,
  de Suisse et des Pays-Bas, ou sont en télétravail.
- **Adzuna** : API gratuite avec identifiants (developer.adzuna.com), centrée ici sur la
  France. Elle est activée automatiquement dès que `ADZUNA_APP_ID` et `ADZUNA_APP_KEY`
  sont remplis dans `.env`. C'est un moteur de recherche : elle est appelée à chaque
  recherche, avec un cache de 6 h par recherche. Ses descriptions ne sont que des
  extraits, et ses conditions demandent d'afficher la mention « Jobs by Adzuna »
  dans une interface publique.

## Installation

1. Crée l'environnement Python et installe les dépendances :
   ```bash
   python3.13 -m venv .venv
   ```
   ```bash
   .venv/bin/pip install -r requirements.txt
   ```
2. Copie le fichier de configuration, puis ouvre `.env` et colle ta clé Groq :
   ```bash
   cp .env.example .env
   ```
3. (Optionnel) Ajoute tes identifiants Adzuna dans `.env`, et installe le modèle de secours :
   ```bash
   ollama pull qwen3:8b
   ```
4. Dépose ton CV sous le nom `data/cv.pdf`.
5. Vérifie que tout est prêt :
   ```bash
   .venv/bin/python main.py --verifier
   ```

## Utilisation

Interface web (s'ouvre dans le navigateur) :
```bash
.venv/bin/streamlit run streamlit_app.py
```
On y choisit le CV : un CV fictif d'exemple, son propre CV en PDF (lu en mémoire, jamais
enregistré) ou, en local, le CV indiqué dans `.env`. Chaque étape de l'agent (lecture du CV,
recherches, lecture des offres, liens retirés par le garde-fou) s'affiche pendant qu'il travaille.

En ligne de commande, poser une question directement :
```bash
.venv/bin/python main.py "Trouve 3 offres en France qui correspondent à mon CV"
```

Mode conversation (plusieurs questions à la suite) :
```bash
.venv/bin/python main.py
```

Forcer le modèle local Ollama :
```bash
.venv/bin/python main.py --ollama "Trouve des offres Python en télétravail"
```

Avec la version gratuite de Groq, une demande prend 1 à 3 minutes, à cause de sa limite de tokens par minute.

## Structure

```
agent/
  config.py     # lecture du fichier .env et réglages
  outils.py     # les outils (recherche, détail d'offre, CV), leur description pour le modèle, le cache
  modele.py     # appel au modèle : Groq, avec bascule sur Ollama
  boucle.py     # la boucle de l'agent, le prompt système, la mémoire courte et le garde-fou des liens
data/           # ton CV et le cache des offres (non publiés sur GitHub)
evaluation/     # questions, CV fictif, script d'évaluation et résultats
main.py         # point d'entrée en ligne de commande
streamlit_app.py  # interface web
```

## Feuille de route

- [x] Squelette du projet
- [x] Outils : Arbeitnow et Remotive (recherche + détail) et lecture du CV
- [x] Boucle de l'agent (appel d'outils avec Groq)
- [x] Comparaison offre / CV avec score
- [x] Secours Ollama
- [x] Source Adzuna (activée par les clés ; à tester avec de vraies clés)
- [x] Interface Streamlit
- [ ] Démo en ligne (Streamlit Community Cloud)
- [x] Évaluation chiffrée (outil de recherche + agent complet avec Ollama)
- [ ] Évaluation complète avec Groq (quota quotidien gratuit)
- [x] Garde-fou qui vérifie les liens de la réponse finale
