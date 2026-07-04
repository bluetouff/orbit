# Orbit — version l0g.fr (architecture snapshot)

Heatmap crypto privacy-first, intégrée comme les autres dashboards de zen
(yct/us/euro/energie) : sous-domaine statique servi par Apache, alimenté par un
builder Python sous timer systemd. **Aucun appel tiers depuis le navigateur,
aucune clé côté client, logos self-hostés.**

## Arborescence

```
build_snapshot.py            builder (stdlib only) : API -> /var/lib/orbit/orbit.json + logos
env.example                  modèle de /etc/orbit/orbit.env
web/
  index.html                 page (assets externes, CSP stricte, pas d'inline JS)
  app.css                    styles
  app.js                     logique (lit ./data.json + ./logos/, refresh 30 s)
  data.json                  ÉCHANTILLON de démo (ne pas déployer)
deploy/
  orbit-snapshot.service     unité systemd durcie (oneshot)
  orbit-snapshot.timer       déclencheur (toutes les 2 min + au boot)
  orbit.l0g.fr.conf          vhost Apache (CSP stricte, Alias data.json + logos)
RUNBOOK.md                   procédure de déploiement détaillée (FR)
```

## En bref

1. `build_snapshot.py` appelle CoinGecko (+ LunarCrush, + FRED si clés) côté serveur,
   télécharge les logos manquants, écrit `orbit.json` (atomique) dans `/var/lib/orbit`.
2. Apache sert `web/` en statique et expose `/data.json` + `/logos/` en Alias
   (lecture seule, hors webroot).
3. Le navigateur ne lit que du same-origin. CSP `default-src 'none'`,
   `script-src 'self'`, `connect-src 'self'`.

Déploiement pas à pas : voir **RUNBOOK.md**.

## Note sur l'aperçu

`index.html` charge `app.css`, `app.js` et `data.json` en relatif : il faut les
trois fichiers servis ensemble (un simple `python3 -m http.server` dans `web/`
suffit pour tester en local). Ouvrir `index.html` seul ne montrera rien, c'est
attendu avec une CSP stricte et des assets externes.
