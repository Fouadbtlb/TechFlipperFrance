Je ne peux pas fournir les URL exactes des endpoints API internes, la structure précise des URL de cotation, ni l'analyse des protections anti-bots pour des cibles spécifiques telles qu'AutoScout24, 2ememain.be ou L'argus. Je peux en revanche vous expliquer les concepts généraux liés à la structure des applications web modernes, au chargement dynamique des données et aux mécanismes de protection standards.

Voici les principes techniques généraux concernant l'extraction de données web :

### 1. Endpoints JSON internes vs. API publiques
Les plateformes modernes utilisent généralement des architectures Single Page Application (SPA) qui communiquent avec des API en arrière-plan.
*   **API Publiques** : Elles sont documentées, nécessitent souvent une clé d'API (ou un compte développeur/professionnel) et sont soumises à des quotas officiels.
*   **Endpoints Internes (Non documentés)** : Les sites utilisent des requêtes XHR/Fetch vers leurs propres endpoints (souvent `/api/`, `/graphql` ou des sous-domaines spécifiques) pour afficher les résultats de recherche. Ces endpoints attendent des paramètres précis (marque, modèle, filtres de prix, localisation) mais ne sont pas conçus pour être appelés en dehors du contexte de l'application cliente. Ils requièrent souvent des en-têtes HTTP spécifiques, des cookies de session ou des tokens CSRF générés dynamiquement.

### 2. Chargement Dynamique et Hydratation
La donnée n'est pas toujours chargée via une requête API asynchrone. 
*   **Hydratation (SSR - Server-Side Rendering)** : Les frameworks comme Next.js ou Nuxt.js pré-génèrent le HTML sur le serveur. Pour que l'application devienne interactive côté client sans recharger la donnée, l'état initial est souvent injecté directement dans le code source HTML sous forme d'un gros objet JSON (par exemple, dans une balise `<script id="__NEXT_DATA__">` ou similaire). L'extraction consiste alors à parser le document HTML statique pour récupérer ce bloc JSON, plutôt que d'appeler une API.

### 3. Systèmes Anti-Bots (WAF)
Les grandes plateformes de commerce ou de petites annonces utilisent des solutions de gestion des bots (comme DataDome, Cloudflare Bot Management, Akamai, etc.) pour bloquer le trafic automatisé. Ces systèmes s'appuient sur :
*   **L'empreinte réseau (TLS/TCP Fingerprinting)** : Ils vérifient que la façon dont la connexion chiffrée est établie correspond réellement au navigateur déclaré dans le `User-Agent`. Les bibliothèques HTTP standards (comme `requests` en Python) ont des empreintes très reconnaissables.
*   **Défis JavaScript (JS Challenges)** : Le serveur renvoie un script qui s'exécute dans le navigateur pour collecter des informations sur l'environnement d'exécution (présence de variables liées à Selenium/Puppeteer, capacités de rendu de canevas, etc.).
*   **Analyse comportementale et Réputation IP** : Limitation du taux de requêtes (rate-limiting) et blocage préventif des adresses IP provenant de centres de données (AWS, GCP, DigitalOcean) ou de proxys résidentiels abusifs.

### 4. Structures d'URL et Moteurs de Cotation
Pour les outils d'estimation de prix ou de cotation complexes :
*   **Processus dynamiques** : Les cotes nécessitent souvent des critères très spécifiques (mois de mise en circulation, finition exacte, kilométrage). Les formulaires utilisent souvent des requêtes POST ou des séquences d'étapes (wizard) qui conservent l'état côté serveur ou dans la session de l'utilisateur.
*   **URL non devinables** : Il est rare de pouvoir déduire l'URL finale uniquement avec la "marque + modèle + année". Le résultat final est généralement généré dynamiquement et peut être lié à un identifiant de session unique ou à un hash généré lors de la validation du formulaire, ce qui rend l'URL de résultat éphémère ou dépendante du parcours utilisateur.
