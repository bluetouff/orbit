# Orbit2

Favoris et carte de marché crypto, par l0g Lab. Logiciel sous [licence MIT](LICENSE).

[English](README.md) · [Application](https://orbit.l0g.fr/) · [Guide utilisateur FR](https://orbit.l0g.fr/docs/) · [User guide EN](https://orbit.l0g.fr/docs/en/)

## Utilisation

- Jusqu’à 50 favoris crypto, conservés sur votre appareil.
- Vue Crypto (jusqu’à 100 actifs), catalogue consultable par nom ou symbole.
- Pour les cryptos : variations sur 1H, 24H, 7D et 30D ; taille des tuiles selon la performance, la capitalisation ou le volume.
- Fiches de marché, dates des sources et états explicites lorsque les données sont anciennes ou indisponibles.
- Interface FR/EN, navigation au clavier, import et export JSON locaux.

Orbit ne passe aucun ordre et ne connecte aucun portefeuille.

## Architecture et confidentialité

Un collecteur Python, limité à la bibliothèque standard, récupère les données côté serveur. Un timer systemd déclenche les collectes ; Apache sert un instantané JSON commun et des logos locaux. Les visiteurs ne multiplient pas les appels aux fournisseurs.

Le navigateur contacte uniquement la même origine. Aucune clé API, police distante, publicité ou bibliothèque tierce n’est nécessaire côté client. Favoris, réglages et langue restent dans le stockage local du navigateur. Les journaux techniques du serveur sont décrits dans les [mentions de confidentialité](https://orbit.l0g.fr/legal/).

CoinGecko conserve la collecte crypto actuelle, avec un cache minimal de 60 secondes. LunarCrush et FRED apportent un contexte séparé, lorsqu’il est disponible. Chaque flux conserve son état et ses dates. Un échec ne produit jamais de prix de remplacement.

## Aperçu local

Sans identifiants fournisseur, en réutilisant l’instantané public existant :

```bash
python3 scripts/preview.py --port 8767
```

Ouvrir <http://127.0.0.1:8767/web/>. Le serveur écoute uniquement sur la boucle locale et n’expose pas les fichiers du dépôt. Pour utiliser un instantané réel déjà généré :

```bash
python3 scripts/preview.py --port 8767 --snapshot /chemin/orbit.json --logos /chemin/logos
```

Les dates d’origine sont préservées. Un fichier ancien reste signalé comme ancien.

## Vérification

```bash
node --check web/core.js
node --check web/app.js
node --check web/i18n.js
node --test tests/*.test.cjs
python3 -m unittest discover -s tests -p 'test_*.py'
```

Les suites navigateur utilisent une installation existante de Playwright : `tests/browser.cjs`, `tests/experience-browser.cjs`, `tests/crypto-only-browser.cjs` et `tests/docs-browser.cjs`. Démarrer l’aperçu auparavant. La suite crypto vérifie aussi l’exclusion des anciens tokens. Les données synthétiques sont réservées aux tests isolés des erreurs et des protections.

Avant publication, appliquer les contrôles de [SECURITY.md](SECURITY.md), dont le scan de secrets du répertoire de travail et de l’historique Git complet.

## Déploiement et documentation

Le [RUNBOOK.md](RUNBOOK.md) détaille l’installation et les mises à jour. `scripts/deploy_release.py` coordonne le collecteur et les quatre pages publiques : application, mentions légales, guide FR et guide EN. Il vérifie le serveur, sauvegarde les fichiers, valide une nouvelle collecte réelle, publie les assets immuables et fournit une commande de retour arrière. L’administrateur effectue l’activation privilégiée.

Ne jamais copier les données d’aperçu, les logos générés ou les identifiants dans un commit ou une archive publique. Le fichier `env.example` décrit les paramètres ; les secrets restent dans l’environnement du serveur. Une publication Git ne suffit pas : le SHA et les données effectivement servis doivent être vérifiés après activation.

Les guides utilisateur sont dans `web/docs/index.html` et `web/docs/en/index.html`. Ils fonctionnent sans JavaScript et sont versionnés avec l’application. Le README anglais décrit plus précisément le contrat des données, les formules et les limites des signaux.

En cas de réponse HTTP 429 de CoinGecko, le collecteur diffère tous les appels
à ce fournisseur et respecte `Retry-After`. La temporisation persiste entre
les passages du timer ; les prix et leurs dates de collecte réussie restent
inchangés. Un nouvel instantané peut publier l’échec et actualiser les autres
sources. Les appels CoinGecko sont espacés d’au moins deux secondes ; les pages
crypto sont mises en cache 60 secondes par défaut (`ORBIT_MARKETS_REFRESH_SEC`).
Un échec de page conserve l’univers crypto précédent au complet. Le fichier
privé de temporisation ne contient qu’une date de reprise et un compteur, hors du webroot et
ignorés par Git. Le [runbook](RUNBOOK.md#coingecko-http-429-recovery) précise les
attentes bornées du déploiement et la reprise après restauration.

Les pages crypto sont publiées atomiquement dès leur collecte complète, avant les requêtes sociales, macro et les logos. Une seconde publication complète le contexte sans changer les dates des prix ni de la collecte crypto.

Le déploiement arrête et désactive l’ancien timer Kraken, puis retire son service et son collecteur. La cadence crypto et le fichier de secrets sont conservés. Les anciens tokens sont exclus des données publiées et du navigateur, y compris à partir d’un cache. Les caches privés devenus inutiles restent hors de la racine web et ne sont plus lus. Le retour arrière restaure les fichiers et l’état précédent des unités. Après activation, `python3 scripts/verify_collection.py` vérifie deux renouvellements crypto et l’absence de tokens, en lisant seulement le site public.
