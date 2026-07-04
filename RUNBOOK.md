# Déploiement d'Orbit sur l0g.fr (architecture snapshot)

Même patron que yct/us/euro/energie : un timer systemd régénère un JSON statique
hors webroot, Apache sert du statique, le navigateur ne contacte **aucun tiers**
et **aucune clé** n'est exposée. Les logos sont téléchargés une fois côté serveur
et servis en local — donc zéro requête vers le CDN CoinGecko.

```
  timer systemd (toutes les 2 min)
        |
        v
  build_snapshot.py --(HTTPS)--> CoinGecko (+ LunarCrush, + FRED si clés)
        |                          + télécharge les logos manquants
        v
  /var/lib/orbit/orbit.json   (écriture atomique, hors web root)
  /var/lib/orbit/logos/*.png
        ^   ^
        |   | Alias /logos  (lecture seule, cache long)
        | Alias /data.json (lecture seule, cache 30s)
  Apache 443 --> /var/www/orbit/{index.html,app.css,app.js}
```

Arborescence du dépôt : `web/` (front statique), `deploy/` (service, timer, vhost),
`build_snapshot.py` et `env.example` à la racine.

---

## 0. Prérequis

- DNS `A`/`AAAA` : `orbit.l0g.fr` → IP de zen.
- Modules Apache : `sudo a2enmod ssl headers rewrite`
- Python 3 (le builder n'utilise que la stdlib, aucun pip).

---

## 1. Utilisateur système et arborescence

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin orbit

sudo install -d -o orbit -g orbit -m 755 /var/lib/orbit /var/lib/orbit/logos
sudo install -d -m 755 /opt/orbit
sudo install -o root -g root -m 0755 build_snapshot.py /opt/orbit/build_snapshot.py

sudo install -d -m 755 /var/www/orbit
sudo install -o root -g root -m 0644 web/index.html /var/www/orbit/index.html
sudo install -o root -g root -m 0644 web/app.css    /var/www/orbit/app.css
sudo install -o root -g root -m 0644 web/app.js     /var/www/orbit/app.js
# ne PAS copier web/data.json en prod : c'est l'échantillon de démo.
```

---

## 2. Configuration (clés côté serveur uniquement)

```bash
sudo install -d -o orbit -g orbit -m 750 /etc/orbit
sudo cp env.example /etc/orbit/orbit.env
sudo chown orbit:orbit /etc/orbit/orbit.env && sudo chmod 640 /etc/orbit/orbit.env
sudoedit /etc/orbit/orbit.env       # CG_API_TIER/CG_API_KEY, LUNARCRUSH_API_KEY, FRED_API_KEY
```

Sans aucune clé, l'app fonctionne déjà via l'API publique CoinGecko. LunarCrush
active l'axe social réel (Galaxy Score) ; FRED active le bandeau macro réel.

---

## 3. Premier build manuel

```bash
sudo -u orbit ORBIT_OUT_DIR=/var/lib/orbit /usr/bin/python3 /opt/orbit/build_snapshot.py
ls -lh /var/lib/orbit/orbit.json /var/lib/orbit/logos | head
```

---

## 4. Timer systemd

```bash
sudo cp deploy/orbit-snapshot.service deploy/orbit-snapshot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now orbit-snapshot.timer
systemctl list-timers orbit-snapshot.timer
journalctl -u orbit-snapshot.service -n 20 --no-pager
```

---

## 5. Apache + certificat

```bash
sudo cp deploy/orbit.l0g.fr.conf /etc/apache2/sites-available/orbit.l0g.fr.conf
sudo a2ensite orbit.l0g.fr
sudo apache2ctl configtest && sudo systemctl reload apache2
# certificat (webroot) :
sudo certbot --apache -d orbit.l0g.fr      # ou certonly --webroot -w /var/www/orbit
sudo systemctl reload apache2
```

---

## 6. Vérifier la promesse privacy

Sur le site déployé, onglet Réseau des devtools : **toutes** les requêtes doivent
viser `orbit.l0g.fr` (le HTML, `app.css`, `app.js`, `/data.json`, `/logos/*.png`).
Aucune requête vers `coingecko.com`, `coin-images.coingecko.com`, `lunarcrush.com`,
`googleapis.com` ou tout autre tiers. La CSP `connect-src 'self'` l'interdit de toute façon.

---

## 7. Réglages utiles

- **Cadence** : `OnUnitActiveSec` dans le timer (défaut 120 s). Le front relit le
  JSON toutes les 30 s (`REFRESH_MS` dans `app.js`).
- **Profondeur** : `ORBIT_TOP` (univers) et `ORBIT_SPARK_TOP` (coins avec sparkline)
  dans `orbit.env`. Plus c'est grand, plus `orbit.json` est lourd.
- **Favoris / vue** dans `app.js` : `MAX_FAV` (défaut 50, plafond de favoris),
  `TOP_N` (défaut 100, taille de la vue « Top » par défaut). Les favoris sont
  persistés côté navigateur via `localStorage` (clé `orbit.favs.v1`) : aucun compte,
  aucun login, rien n'est envoyé au serveur.
- **Budget API** : un build = ~2 appels CoinGecko (pages markets) + 1 global
  (+1 LunarCrush, +2 FRED si clés). À 120 s, ça reste très en dessous des limites.

## Sécurité (résumé)

- Aucune clé dans le navigateur, aucun appel tiers côté client, aucune fuite d'IP
  utilisateur vers les fournisseurs de données.
- CSP `default-src 'none'` ; `script-src 'self'` (app.js externe, pas d'inline) ;
  `connect-src 'self'`. Logos et données en same-origin.
- Builder non privilégié et fortement sandboxé (ProtectSystem=strict,
  MemoryDenyWriteExecute, SystemCallFilter, un seul chemin inscriptible), https-only,
  allowlist d'hôtes pour les logos, taille de réponse bornée, écritures atomiques.
- Clés FRED/LunarCrush/CoinGecko dans `/etc/orbit/orbit.env` (640), injectées par
  systemd, jamais sur disque accessible au front.
