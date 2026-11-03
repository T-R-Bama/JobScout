# Évaluation de l'agent

Un agent peut échouer à plusieurs endroits : ses **outils** ne trouvent pas les bonnes
offres, le **modèle** utilise mal les outils (oublie le CV, cherche au mauvais endroit),
ou la **réponse** est fausse (lien inventé, offre hors du lieu demandé, source oubliée).
Cette évaluation mesure ces niveaux séparément, pour savoir où améliorer le système.

Résultats détaillés : [RESULTS.md](RESULTS.md).

## Rendre l'évaluation reproductible

Les offres d'emploi changent tous les jours. Pour comparer deux versions de l'agent
sur la même base :

- les offres sont **figées** dans `offres_figees/` (912 offres Arbeitnow et Remotive du
  2 novembre 2026). Ce dossier n'est pas publié sur GitHub, car les conditions de
  Remotive interdisent de republier ses offres ;
- l'agent lit un **CV fictif** ([`cv_test.md`](cv_test.md)), jamais le vrai CV de l'utilisateur ;
- Adzuna est désactivé pendant l'évaluation, car ses résultats changent à chaque appel.

## Le jeu de questions

[`questions.json`](questions.json) contient **8 questions** qui couvrent les situations clés :

| Question | Ce qu'elle teste |
|---|---|
| Développeur Python en France | Filtre par **pays** |
| Data scientist à Paris | Filtre par **ville** |
| Product manager à Berlin | Ville hors de France |
| Développeur React en télétravail | Filtre **télétravail** |
| DevOps au Royaume-Uni | Pays écrit en français alors que les offres sont en anglais |
| 3 offres en France pour mon CV | Lecture du **CV**, puis comparaison |
| « Junior AI Consultant » me correspond-elle ? | CV et **détail** d'une offre précise |
| Boulanger à Marseille | **Aucune offre** n'existe : l'agent ne doit rien inventer |

Chaque question précise la vérité attendue : les offres pertinentes (`offres_attendues`),
la contrainte de lieu ou de télétravail, et si l'agent doit lire le CV ou le détail
d'une offre. Une recherche « idéale » (`recherche_type`) sert à tester l'outil de
recherche seul.

## Les métriques

Toutes les métriques sont **déterministes**. Contrairement à AskMyDocs, il n'y a pas
de LLM juge : chaque critère peut être vérifié directement à partir des appels d'outils
et des liens présents dans la réponse. Le **pays réel** d'une offre est déduit du site
d'origine (`arbeitnow.fr`, `.co.uk`…), indépendamment de ce que fait l'agent.

**Outil de recherche seul** (sans LLM, gratuit, instantané) :
- **Offres du bon lieu visibles par le filtre** : parmi les offres réellement situées
  au lieu demandé, part que le filtre laisse passer.
- **Offre attendue dans le top 5** : la recherche idéale fait remonter une offre pertinente.
- **Résultats au bon endroit** : part des 5 premiers résultats qui respectent la contrainte.

**Agent complet** :

| Métrique | Vérification |
|---|---|
| Offre pertinente trouvée | La réponse cite (par son lien) au moins une des `offres_attendues` |
| Lieu / télétravail respecté | Toutes les offres citées respectent la contrainte de la question |
| Aucun lien inventé par le modèle | Tous les liens écrits par le modèle existent dans la base d'offres (mesuré avant le garde-fou) |
| Aucun lien inventé affiché | Tous les liens de la réponse affichée existent (mesuré après le garde-fou) |
| Source citée | La source (Arbeitnow, Remotive) de chaque offre citée est nommée |
| CV lu à bon escient | L'outil `read_cv` est appelé si, et seulement si, la question parle du profil |
| Détail de l'offre lu | `get_job_details` est appelé sur l'offre demandée |
| N'invente pas d'offre | Pour « boulanger à Marseille », la réponse ne cite aucune offre |

On mesure aussi le nombre de liens retirés par le garde-fou, le nombre de recherches, les tokens consommés et le temps par question.

## Lancer l'évaluation

Outil de recherche seul, avant et après le correctif du filtre de lieu (quelques secondes) :
```bash
.venv/bin/python evaluation/run_eval.py --recherche-seule
```

Agent complet avec Groq, avant et après le correctif (environ 20 000 tokens par question) :
```bash
.venv/bin/python evaluation/run_eval.py --ancien-filtre --label groq-avant
```
```bash
.venv/bin/python evaluation/run_eval.py --label groq-apres
```

Agent complet avec le modèle local Ollama (gratuit, sans limite, plus lent) :
```bash
.venv/bin/python evaluation/run_eval.py --ollama --label ollama-apres
```

Sans le garde-fou qui retire les liens inventés (pour mesurer son effet) : ajouter `--sans-garde-fou`.

Si le quota quotidien de Groq est épuisé en cours de route, l'évaluation s'arrête
proprement et affiche la commande pour reprendre plus tard les questions restantes
(`--questions …`) : les résultats ne mélangent jamais deux modèles.

Chaque exécution enregistre le détail (appels d'outils, réponse, liens) dans `results/`
et régénère `RESULTS.md`.

## Ce que l'évaluation a appris

### 1. Un bug invisible à l'œil : le filtre de lieu cachait la moitié des offres

En explorant les offres pour écrire les questions, un défaut est apparu : le lieu d'une
offre Arbeitnow ne contient souvent que la ville (« Paris »). Quand l'agent cherchait
« France », le filtre exigeait le mot « France » dans le lieu et **ignorait toutes les
offres parisiennes**. Le correctif déduit le pays du site d'origine, accepte les noms
de pays en français et en anglais (« Royaume-Uni », « UK »), et ignore les accents.

Le test de l'outil de recherche seul mesure l'effet, sans LLM :

| Filtre de lieu | Offres du bon lieu visibles | Offre attendue dans le top 5 | Résultats au bon endroit |
|---|---|---|---|
| Avant correctif | 53 % (308/586) | 86 % (6/7) | 100 % |
| **Après correctif** | **100 % (586/586)** | **100 % (7/7)** | **100 %** |

En détail : avec « France », **35 offres sur 150** étaient visibles avant le correctif,
et **0 sur 150** avec « Royaume-Uni ». Les tests manuels du premier jour n'avaient rien
montré d'anormal : l'agent trouvait quelques offres en France, et rien ne signalait
qu'il en manquait 115.

### 2. L'agent complet confirme le correctif

Avec `qwen3:8b` en local, sur les 8 questions :

| Configuration | Offre pertinente trouvée | Lieu respecté | Aucun lien inventé | CV lu à bon escient | Tokens / question |
|---|---|---|---|---|---|
| Avant correctif | 86 % (6/7) | 100 % | 100 % | 100 % | 4 546 |
| **Après correctif** | **100 % (7/7)** | **100 %** | 88 % (7/8) | **100 %** | 5 951 |

La question « DevOps au Royaume-Uni » passe d'échec à réussite. Pour « développeur
Python en France », l'agent cite maintenant « Développeur Senior Python » chez MARGO,
une offre qu'il ne pouvait pas voir avant.

### 3. Le mode « réflexion » de qwen3 rendait l'agent instable

La première évaluation avec `qwen3:8b` utilisait son mode « réflexion » (le modèle
raisonne longuement avant de répondre). Résultat : l'agent lisait le CV sans raison
(62 à 75 % de bons usages), ne lisait pas le détail des offres, et sur une question il a
**réfléchi 19 minutes (43 000 tokens) pour finir sur une réponse vide**. Avec ce mode,
une seule exécution variait tellement que le correctif semblait même dégrader les
résultats. Le mode réflexion est désormais coupé et la longueur des réponses plafonnée :
toutes les métriques d'usage des outils passent à 100 %, et le temps moyen tombe à
30 s par question. Les résultats avec réflexion sont conservés dans `RESULTS.md`.

### 4. La vérification des liens attrape de vraies hallucinations

Après correctif, sur la question « 3 offres pour mon CV », `qwen3:8b` a cité un lien
qui n'existe pas : il mélange le nom d'une entreprise absente des résultats, le titre
d'une offre et le numéro d'une autre, alors qu'il venait de lire le détail de la bonne
offre. Seul un contrôle automatique peut repérer ce genre d'erreur, qui a l'air
parfaitement plausible.

D'où un **garde-fou dans le code** : la boucle de l'agent retient tous les liens
renvoyés par les outils pendant la demande, puis retire de la réponse finale tout lien
qui n'en fait pas partie, avec un avertissement visible pour l'utilisateur. Le modèle
n'est pas plus fiable, mais l'utilisateur ne voit plus de lien inventé :

| Configuration | Aucun lien inventé par le modèle | Aucun lien inventé affiché | Liens retirés |
|---|---|---|---|
| Sans garde-fou (`ollama-apres`) | 88 % (7/8) | 88 % (7/8) | – |
| **Avec garde-fou** (`ollama-garde-fou`) | 88 % (7/8) | **100 % (8/8)** | 1 |

Dans la nouvelle exécution, `qwen3:8b` a de nouveau fabriqué un lien sur la même
question (même entreprise, autre numéro) : l'erreur est répétable, et le garde-fou l'a
retirée. Les autres métriques sont restées identiques, sauf « Détail de l'offre lu »
sur une question, une variation d'une exécution à l'autre sans lien avec le garde-fou.

### 5. Groq lisait le CV sans raison

Sur la démo en ligne, pour « offres Python en télétravail », `gpt-oss-120b` lisait le
CV alors que la question ne parlait pas du profil : des tokens et du temps perdus, et
un score d'adéquation que personne n'avait demandé. Les consignes disaient quand lire
le CV, mais pas quand ne pas le lire. Le prompt système et la description de l'outil
`read_cv` le précisent désormais, avec des exemples des deux cas.

Pour mesurer l'effet sans épuiser le quota, un test ciblé ne regarde que la première
décision du modèle sur les 8 questions et la question de la démo : la lecture inutile
du CV pour « data scientist à Paris » disparaît. L'évaluation complète confirme sur
l'ensemble des étapes.

### 6. Avec Groq, l'agent complet réussit toutes les questions

L'évaluation complète avec `gpt-oss-120b` (le modèle de la démo en ligne), avec tous
les correctifs (filtre de lieu, garde-fou des liens, consigne sur le CV) :

| Métrique | `groq-apres` |
|---|---|
| Offre pertinente trouvée | **100 % (7/7)** |
| Lieu / télétravail respecté | **100 % (7/7)** |
| Aucun lien inventé (modèle et réponse affichée) | **100 % (8/8)** |
| Source citée | **100 % (7/7)** |
| CV lu à bon escient | **100 % (8/8)**, contre 50 % (1/2) avant la consigne |
| Détail de l'offre lu / n'invente pas d'offre | **100 %** |
| Tokens / question | 22 626 |
| Temps / question | 125 s |

Le modèle de Groq est plus fiable que `qwen3:8b` (aucun lien inventé) mais coûte
4 fois plus de tokens : il fait plus de recherches et lit plus d'offres en détail.

### 7. Le quota gratuit de Groq limite l'évaluation

Les 8 questions consomment environ **180 000 tokens**, presque tout le quota quotidien
gratuit, partagé avec la démo en ligne. Le premier jour, l'évaluation Groq s'est
arrêtée au bout de 2 questions ; le script s'arrête proprement dans ce cas et indique
la commande pour reprendre. Il faut donc une journée de quota par évaluation complète.

## Limites

- 8 questions seulement, et une seule exécution par configuration : avec un petit
  modèle, une exécution peut varier d'une fois sur l'autre. Le test de l'outil de
  recherche, lui, est parfaitement déterministe.
- Les offres attendues ont été choisies à la main dans la base figée ; d'autres offres
  pertinentes existent parfois (par exemple « Lead Platform Engineer » à Manchester
  pour la question DevOps). Citer d'autres offres en plus ne pénalise pas l'agent, mais
  une réponse qui ne citerait *que* des offres pertinentes hors de la liste serait
  comptée comme un échec à tort.
  Les questions et les offres attendues n'ont pas été modifiées après avoir vu les
  résultats.
- La pertinence des scores d'adéquation au CV n'est pas mesurée : il faudrait un LLM
  juge ou une relecture humaine.
- Le pays réel n'est connu que pour les offres Arbeitnow (d'après le site d'origine) :
  le filtre par pays ne s'applique pas aux offres Remotive, qui sont toutes en télétravail.
