# Architecture du backend

Ce document explique **où est quoi** et **comment faire chaque modification
courante**. Si tu ne lis qu'une partie, lis « Où changer quoi ».

## Vue d'ensemble

```
 Leboncoin / 2ememain
        │
        ▼
 ┌──────────────┐  écrit   ┌──────────────────┐  lit   ┌───────────────┐
 │   Scanner    │ ───────► │  SQLite (1 fichier)│ ◄────── │      API      │ ◄──── app mobile
 │ cli loop     │          │  techflip.db      │        │ cli serve     │
 └──────────────┘          └──────────────────┘        └───────────────┘
        │                                                     ▲
        └────────── notifications push (Expo) ────────────────┘ (abonnés)
        └────────── alertes Telegram (propriétaire)
```

Deux processus, une base :

- **Le scanner** (`python -m techflip.cli loop`) lit les annonces, estime leur
  valeur, enregistre tout, prévient le propriétaire sur Telegram et les abonnés
  par notification.
- **L'API** (`python -m techflip.cli serve`) ne fait que lire et répondre à
  l'app, après avoir vérifié l'appareil et l'abonnement.

Toute l'intelligence est côté serveur. L'app ne fait qu'afficher.

## Les fichiers, un rôle chacun

```
techflip/
├── cli.py            Les commandes (check, once, loop, serve, health, ...)
├── config.py         Réglages de déploiement, lus depuis .env
├── tuning.py         Règles métier réglables (seuils, limites, délais)
├── db.py             Connexion SQLite + migrations
├── storage.py        Tout ce que le scanner lit et écrit en base
├── domain.py         Le modèle Listing (une annonce, quelle que soit la source)
│
├── pipeline.py       Le cycle du scanner : récupérer, enregistrer, alerter
├── valuation.py      Ce que vaut une annonce (étapes nommées, rejets explicites)
├── viewer.py         Pour qui c'est une affaire (distance, trajet, seuil perso)
├── decision.py       La règle « affaire ou pas » selon la zone
├── geo.py            Distances, zones, coût du trajet ou de l'envoi
├── filters.py        Filtres rapides (prix, mots exclus, arnaques évidentes)
│
├── pricing/
│   ├── catalog.py    Le catalogue des composants (config/pricebook.yaml)
│   ├── extract.py    Reconnaître les composants dans un titre
│   ├── tracker.py    Le prix de marché d'un composant (annonces parties > prix demandés)
│   └── appraise.py   Additionner les pièces en une valeur de revente
├── scoring/
│   ├── ai.py         Le modèle de vision (photos + texte), optionnel
│   └── seller.py     Confiance vendeur (ancienneté, avis)
├── sources/          Une classe par site (leboncoin.py, deuxememain.py)
├── notify/           Telegram (propriétaire) et Expo push (abonnés)
│
└── api/
    ├── app.py        Assemble l'API (rien d'autre)
    ├── services.py   Objets partagés : jetons, limiteur, client HTTP, attestation
    ├── deps.py       Qui appelle et a-t-il le droit (chaîne de vérifications)
    ├── schemas.py    Les corps de requête et leur validation
    ├── routes/       Un fichier par domaine : auth, me, feed, system
    ├── deals.py      Transformer une estimation en affaire pour un abonné
    ├── accounts.py   Comptes, appareils, jetons, favoris (tables de l'API)
    ├── attest.py     Vérification App Attest (iOS) et Play Integrity (Android)
    ├── entitlements.py  L'abonnement, vérifié auprès de RevenueCat
    └── fanout.py     Quelles notifications envoyer à qui
```

## Le parcours d'une annonce

1. **pipeline.run_once** récupère les annonces de chaque recherche de
   `config/searches.yaml`.
2. **pipeline._ingest** l'enregistre, la place sur la carte, et note son
   composant principal si c'est une pièce seule (elle sert alors de référence
   de prix).
3. **valuation.Valuer.value** décide ce qu'elle vaut, en étapes :
   `filtres → contexte (distance de l'abonné le plus proche) → estimation par
   pièces → [vérification photo | estimation de l'objet entier] → vendeur`.
   Chaque étape peut renvoyer un `Rejection("raison")`. `discard=True` veut dire
   « ce ne sera jamais une affaire » (échange, photo trompeuse).
4. L'estimation est enregistrée **une seule fois**, indépendamment de qui la
   regarde.
5. **viewer.judge** calcule ensuite, pour chaque personne, le bénéfice depuis
   chez elle. Le propriétaire (Telegram) et chaque abonné passent par la même
   fonction.
6. En fin de cycle : vérification de quelques annonces parties
   (`_watch_departures`), notifications (`fanout`), purge quotidienne
   (`_housekeeping`) et signal de vie (`set_meta("scanner")`).

## Le parcours d'une requête de l'app

Une route déclare ce dont elle a besoin, la chaîne de `deps.py` fait le reste :

```python
@router.get("/deals")
def list_deals(user: ThrottledUser, viewer: ViewerDep, store: StoreDep, ...):
```

`ThrottledUser` = utilisateur connecté (jeton valide) → abonné (RevenueCat) →
sous la limite de requêtes. `ViewerDep` = son point de vue (domicile, seuil).
Chaque étape échoue avec une erreur claire, toujours de la même forme :

```json
{"detail": {"code": "subscription_required", "message": "Abonnement requis"}}
```

`code` sert à l'app, `message` (en français) aux gens.

## Où changer quoi

| Je veux... | Où |
|---|---|
| Changer un seuil métier (confiance minimale, limite de notifications, heures calmes, remise de négociation...) | `techflip/tuning.py`, une ligne |
| Changer un réglage de mon déploiement (domicile, seuils de bénéfice, clés, rythme de scan) | `.env` (liste complète dans `.env.example`) |
| Ajouter une recherche surveillée | `config/searches.yaml` |
| Ajouter un composant reconnu (une carte graphique, une console...) | `config/pricebook.yaml` : clé, libellé, catégorie, prix de départ, alias |
| Ajouter un site | Un fichier dans `techflip/sources/` avec `fetch(search, page)` (et si possible `is_online(id)` et `fetch_seller(id)`), puis une ligne dans `pipeline._make_source` |
| Ajouter un endpoint | Une fonction dans le bon fichier de `techflip/api/routes/` ; les vérifications se déclarent dans la signature |
| Ajouter une colonne ou une table | Ajouter une étape à la fin de `MIGRATIONS` dans `storage.py` (ou `accounts.py`). Ne jamais modifier une étape déjà déployée |
| Changer un texte vu par les utilisateurs | Messages d'erreur : `api/deps.py` et `api/routes/` ; notifications : `api/fanout.py` |

## Légèreté

- **Requêtes vers les sites** : une page par recherche et par cycle, des pauses
  aléatoires, arrêt immédiat au premier blocage, et au plus `DEPARTURE_CHECKS`
  vérifications d'annonces parties par cycle.
- **Taille de la base** : purge quotidienne de ce qui ne sert plus (annonces
  parties au-delà de la fenêtre du tracker, annonces jamais exploitées, journal
  des notifications de plus de 30 jours). L'espace libéré est rendu au disque.
- **Données mobiles** : réponses compressées (gzip), pages de 30 affaires, carte
  limitée aux 250 meilleures.
- **IA** : le modèle de vision ne tourne que sur les candidats douteux ou
  lointains, et son verdict est gardé tant que le prix ne change pas.

## Vérifier que tout va bien

| Quoi | Commande |
|---|---|
| Tout le code passe (lint + tests, backend et app) | `scripts/check.sh` |
| Le scanner tourne-t-il ? | `python -m techflip.cli health` ou `GET /v1/health` (champ `scanner.stale`) |
| Que vaut une pièce selon le tracker ? | `python -m techflip.cli price rtx 4070` |

Branche un outil de surveillance (UptimeRobot, Better Stack...) sur
`/v1/health` et alerte sur `scanner.stale = true` : c'est le signal que plus
aucune affaire n'arrive.

## Conventions

- Le code et ses commentaires sont en anglais, tout ce que voit un utilisateur
  est en français.
- Les règles métier vivent dans `tuning.py`, les réglages de déploiement dans
  `.env` : jamais de nombre magique ailleurs.
- Chaque comportement important a un test. `tests/test_platform.py` couvre la
  plomberie, `tests/test_wins.py` les fonctions récentes, `tests/test_api.py`
  la sécurité et le paywall.
