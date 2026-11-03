# Résultats de l'évaluation

Généré par `evaluation/run_eval.py`. Voir `evaluation/README.md` pour la méthode.

## Outil de recherche seul (sans LLM)

| Filtre de lieu | Offres du bon lieu visibles par le filtre | Offre attendue dans le top 5 | Résultats au bon endroit | Résultats pour « boulanger à Marseille » |
|---|---|---|---|---|
| avant correctif | 53 % (308/586) | 86 % (6/7) | 100 % (30/30) | 0 |
| après correctif | 100 % (586/586) | 100 % (7/7) | 100 % (35/35) | 0 |

Détail de la couverture (offres visibles / offres réellement au bon endroit) :

- `lieu = France` : 35/150 avant, 150/150 après
- `lieu = Paris` : 97/97 avant, 97/97 après
- `lieu = Berlin` : 98/98 avant, 98/98 après
- `teletravail_seulement = True` : 76/89 avant, 89/89 après
- `lieu = Royaume-Uni` : 0/150 avant, 150/150 après
- `lieu = Marseille` : 2/2 avant, 2/2 après

## Agent complet

| Configuration | Répond | Offre pertinente trouvée | Lieu / télétravail respecté | Aucun lien inventé par le modèle | Aucun lien inventé affiché | Source citée | CV lu à bon escient | Détail de l'offre lu | N'invente pas d'offre | Liens retirés par le garde-fou | Recherches / question | Tokens / question | Temps / question |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `groq-avant` (groq · openai/gpt-oss-120b, 2/8 questions) | 100 % (2/2) | 100 % (2/2) | 100 % (2/2) | 100 % (2/2) | – | 100 % (2/2) | 50 % (1/2) | – | – | – | 2.0 | 15,386 | 75 s |
| `ollama-reflexion-avant` (ollama · qwen3:8b (mode réflexion)) | 100 % (8/8) | 86 % (6/7) | 100 % (6/6) | 100 % (8/8) | – | 100 % (6/6) | 75 % (6/8) | 0 % (0/1) | 100 % (1/1) | – | 1.5 | 4,769 | 36 s |
| `ollama-reflexion-apres` (ollama · qwen3:8b (mode réflexion)) | 88 % (7/8) | 71 % (5/7) | 83 % (5/6) | 100 % (8/8) | – | 100 % (6/6) | 62 % (5/8) | 0 % (0/1) | 100 % (1/1) | – | 1.4 | 10,421 | 188 s |
| `ollama-avant` (ollama · qwen3:8b) | 100 % (8/8) | 86 % (6/7) | 100 % (6/6) | 100 % (8/8) | – | 100 % (6/6) | 100 % (8/8) | 100 % (1/1) | 100 % (1/1) | – | 1.4 | 4,546 | 40 s |
| `ollama-apres` (ollama · qwen3:8b) | 100 % (8/8) | 100 % (7/7) | 100 % (7/7) | 88 % (7/8) | – | 100 % (7/7) | 100 % (8/8) | 100 % (1/1) | 100 % (1/1) | – | 1.0 | 5,951 | 29 s |
| `ollama-garde-fou` (ollama · qwen3:8b) | 100 % (8/8) | 100 % (7/7) | 100 % (7/7) | 88 % (7/8) | 100 % (8/8) | 100 % (7/7) | 100 % (8/8) | 0 % (0/1) | 100 % (1/1) | 1 | 1.0 | 5,591 | 25 s |
| `groq-apres` (groq · openai/gpt-oss-120b) | 100 % (8/8) | 100 % (7/7) | 100 % (7/7) | 100 % (8/8) | 100 % (8/8) | 100 % (7/7) | 100 % (8/8) | 100 % (1/1) | 100 % (1/1) | 0 | 2.6 | 22,626 | 125 s |

## Détail par question

### `groq-avant`

- **Trouve des offres de développeur Python en France.** : ✅
- **Je cherche un poste de data scientist à Paris.** : ❌ CV lu à bon escient

### `ollama-reflexion-avant`

- **Trouve des offres de développeur Python en France.** : ✅
- **Je cherche un poste de data scientist à Paris.** : ❌ CV lu à bon escient
- **Quelles offres de product manager y a-t-il à Berlin ?** : ✅
- **Trouve des offres de développeur React en télétravail.** : ✅
- **Trouve des offres de DevOps ou de platform engineer au Royaume-Uni.** : ❌ Offre pertinente trouvée
- **Trouve 3 offres en France qui correspondent à mon CV.** : ✅
- **L'offre « Junior AI Consultant » à Paris correspond-elle à mon profil ?** : ❌ Détail de l'offre lu
- **Trouve des offres de boulanger à Marseille.** : ❌ CV lu à bon escient

### `ollama-reflexion-apres`

- **Trouve des offres de développeur Python en France.** : ❌ CV lu à bon escient
- **Je cherche un poste de data scientist à Paris.** : ❌ CV lu à bon escient
- **Quelles offres de product manager y a-t-il à Berlin ?** : ✅
- **Trouve des offres de développeur React en télétravail.** : ✅
- **Trouve des offres de DevOps ou de platform engineer au Royaume-Uni.** : ❌ Répond, Offre pertinente trouvée
- **Trouve 3 offres en France qui correspondent à mon CV.** : ❌ Offre pertinente trouvée, Lieu / télétravail respecté
- **L'offre « Junior AI Consultant » à Paris correspond-elle à mon profil ?** : ❌ Détail de l'offre lu
- **Trouve des offres de boulanger à Marseille.** : ❌ CV lu à bon escient

### `ollama-avant`

- **Trouve des offres de développeur Python en France.** : ✅
- **Je cherche un poste de data scientist à Paris.** : ✅
- **Quelles offres de product manager y a-t-il à Berlin ?** : ✅
- **Trouve des offres de développeur React en télétravail.** : ✅
- **Trouve des offres de DevOps ou de platform engineer au Royaume-Uni.** : ❌ Offre pertinente trouvée
- **Trouve 3 offres en France qui correspondent à mon CV.** : ✅
- **L'offre « Junior AI Consultant » à Paris correspond-elle à mon profil ?** : ✅
- **Trouve des offres de boulanger à Marseille.** : ✅

### `ollama-apres`

- **Trouve des offres de développeur Python en France.** : ✅
- **Je cherche un poste de data scientist à Paris.** : ✅
- **Quelles offres de product manager y a-t-il à Berlin ?** : ✅
- **Trouve des offres de développeur React en télétravail.** : ✅
- **Trouve des offres de DevOps ou de platform engineer au Royaume-Uni.** : ✅
- **Trouve 3 offres en France qui correspondent à mon CV.** : ❌ Aucun lien inventé par le modèle
- **L'offre « Junior AI Consultant » à Paris correspond-elle à mon profil ?** : ✅
- **Trouve des offres de boulanger à Marseille.** : ✅

### `ollama-garde-fou`

- **Trouve des offres de développeur Python en France.** : ✅
- **Je cherche un poste de data scientist à Paris.** : ✅
- **Quelles offres de product manager y a-t-il à Berlin ?** : ✅
- **Trouve des offres de développeur React en télétravail.** : ✅
- **Trouve des offres de DevOps ou de platform engineer au Royaume-Uni.** : ✅
- **Trouve 3 offres en France qui correspondent à mon CV.** : ❌ Aucun lien inventé par le modèle
- **L'offre « Junior AI Consultant » à Paris correspond-elle à mon profil ?** : ❌ Détail de l'offre lu
- **Trouve des offres de boulanger à Marseille.** : ✅

### `groq-apres`

- **Trouve des offres de développeur Python en France.** : ✅
- **Je cherche un poste de data scientist à Paris.** : ✅
- **Quelles offres de product manager y a-t-il à Berlin ?** : ✅
- **Trouve des offres de développeur React en télétravail.** : ✅
- **Trouve des offres de DevOps ou de platform engineer au Royaume-Uni.** : ✅
- **Trouve 3 offres en France qui correspondent à mon CV.** : ✅
- **L'offre « Junior AI Consultant » à Paris correspond-elle à mon profil ?** : ✅
- **Trouve des offres de boulanger à Marseille.** : ✅
