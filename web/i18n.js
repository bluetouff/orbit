'use strict';
(function(root){
  const fr={
    'Orbit2 - your crypto watchlist':'Orbit2 - votre sélection crypto',
    'Orbit2 - legal, privacy and GDPR':'Orbit2 - mentions légales, vie privée et RGPD',
    'Orbit2 home':'Accueil Orbit2','by l0g Lab':'par l0g Lab','Language':'Langue',
    'Support l0g':'Soutenir l0g','Discover l0g':'Découvrir l0g','Support independent work':'Soutenir un travail indépendant',
    'A l0g Lab project':'Un projet l0g Lab','Crypto performance. Market signals.':'Performances crypto. Signaux de marché.',
    'Your coins. The market around them. A clearer perspective on everyday price moves, unusual activity and the gaps between them.':'Vos cryptos. Le marché autour d’elles. Du recul sur les variations de prix, l’activité inhabituelle et les écarts entre les deux.',
    'Build my watchlist':'Choisir mes cryptos','Open my watchlist':'Ouvrir mes favoris','Explore market':'Explorer le marché',
    'No account. No trackers. Open source.':'Sans compte. Sans traceurs. Code ouvert.',
    'Frequently asked questions':'Questions fréquentes',
    'What is a divergence?':'Qu’est-ce qu’une divergence ?',
    "A gap between an asset's 24-hour price z-score and its trading-activity z-score. An absolute gap above 1.2 is highlighted. It describes a difference, not proof of buying pressure, selling pressure or a future move.":'Un écart entre le score z du prix sur 24 heures et celui de l’activité d’échange. Un écart absolu supérieur à 1,2 est signalé. Il décrit une différence, pas une preuve de pression acheteuse, vendeuse ou de mouvement à venir.',
    'What makes a move unusual?':'Qu’est-ce qu’un mouvement inhabituel ?',
    'A price return more than two standard deviations from the reference mean, or unusually high 24-hour volume relative to market cap. The reference includes all assets with usable data, not just your favorites.':'Une performance éloignée de plus de deux écarts-types de la moyenne de référence, ou un volume sur 24 heures inhabituellement élevé par rapport à la capitalisation. La référence inclut tous les actifs aux données exploitables, pas seulement vos favoris.',
    'How current are the data?':'Quelle est la fraîcheur des données ?',
    'The browser checks for a new server snapshot every 30 to 45 seconds while the page is visible. Provider observations can be older. Collection times are shown, and signals are paused when market data exceeds three minutes.':'Le navigateur recherche un nouvel instantané toutes les 30 à 45 secondes lorsque la page est visible. Les observations des fournisseurs peuvent être plus anciennes. Les heures de collecte sont affichées et les signaux sont suspendus au-delà de trois minutes.',
    'Where are my favorites stored?':'Où sont conservés mes favoris ?',
    'On this device, in your browser. Up to 50 coins, without an account. Your selection is not sent to the server. A local JSON export is available for backup or transfer.':'Sur cet appareil, dans votre navigateur. Jusqu’à 50 cryptos, sans compte. Votre sélection n’est pas envoyée au serveur. Un export JSON local permet de la sauvegarder ou de la transférer.',
    'Where do the data come from?':'D’où viennent les données ?',
    'CoinGecko supplies market data. LunarCrush provides separate social context when available; it does not determine the signals. FRED supplies macroeconomic context. Missing data stays unavailable.':'CoinGecko fournit les données de marché. LunarCrush apporte un contexte social distinct lorsqu’il est disponible, sans déterminer les signaux. FRED fournit le contexte macroéconomique. Une donnée manquante reste indisponible.',
    'Is this investment advice?':'Est-ce un conseil en investissement ?',
    'No. These are cross-asset statistical comparisons, not forecasts, trading instructions or risk guarantees. No detected signal does not mean an asset is safe.':'Non. Il s’agit de comparaisons statistiques entre actifs, pas de prévisions, de consignes de trading ou de garanties sur le risque. L’absence de signal ne signifie pas qu’un actif est sûr.',
    'Manage watchlist':'Gérer les favoris','Full screen':'Plein écran','Exit full screen':'Quitter le plein écran','Watchlist settings':'Réglages des favoris',
    'View':'Vue','Watchlist':'Favoris','Market':'Marché','Performance period':'Période de performance','Show':'Afficher','All coins':'Toutes les cryptos',
    'Divergences':'Divergences','Anomalies':'Anomalies','Gainers':'Hausses','Losers':'Baisses','Size':'Taille','Performance':'Performance','Market cap':'Capitalisation','Volume':'Volume',
    'Signals':'Signaux','Your market. Your selection.':'Votre marché. Votre sélection.','Your watchlist':'Vos favoris','Import watchlist':'Importer des favoris',
    'Find a coin':'Rechercher une crypto','Open watchlist':'Ouvrir les favoris','On this device only. No account.':'Sur cet appareil uniquement. Sans compte.',
    'Crypto performance heatmap':'Carte des performances crypto','Waiting for data':'En attente de données','Assets':'Actifs','Loading market data':'Chargement des données de marché',
    'Show all coins':'Afficher toutes les cryptos','24-hour performance':'Performance sur 24 heures','Down':'Baisse','Up':'Hausse','In your watchlist':'Dans vos favoris','In the top 100':'Dans le top 100',
    'Hide signals':'Masquer les signaux','Data sources':'Sources de données','How signals are calculated':'Méthode de calcul des signaux',
    'Private by design':'Vie privée préservée','Legal & privacy':'Mentions légales et vie privée','Source / MIT':'Code / MIT','Your coins':'Vos cryptos','Close':'Fermer',
    'Search coins':'Rechercher des cryptos','Selected only':'Sélection uniquement','More coins':'Plus de cryptos','Done':'Terminer','Export watchlist':'Exporter les favoris',
    'Coins and display preferences':'Cryptos et préférences d’affichage','From an Orbit2 JSON file':'Depuis un fichier JSON Orbit2',
    'Your file is read on this device and is never uploaded.':'Le fichier est lu sur cet appareil et n’est jamais envoyé au serveur.',
    'Selection':'Sélection','Merge with my coins':'Fusionner avec mes cryptos','Replace my selection':'Remplacer ma sélection','Import':'Importer',
    'Signal methodology':'Méthodologie des signaux','A common reference':'Une référence commune','Sources and limits':'Sources et limites',
    'All assets with a valid return in the current market snapshot form the reference, including stablecoins. Changing your watchlist or filtering the map does not change this reference. At least 20 valid observations are required.':'Tous les actifs ayant une performance valide dans l’instantané de marché forment la référence, stablecoins compris. Modifier vos favoris ou filtrer la carte ne change pas cette référence. Au moins 20 observations valides sont nécessaires.',
    'A return more than two population standard deviations above or below the reference mean is highlighted. A 24-hour volume-to-market-cap ratio is also highlighted above two standard deviations, after a log10(1 + 1000 × ratio) transformation.':'Une performance située à plus de deux écarts-types de population au-dessus ou au-dessous de la moyenne est signalée. Le ratio volume sur 24 heures / capitalisation est aussi signalé au-delà de deux écarts-types, après transformation log10(1 + 1000 × ratio).',
    'On the 24H view only, the price and activity z-scores are compared. An absolute difference above 1.2 is highlighted. Activity uses 24-hour volume; it is not compared with other return periods. These are heuristic thresholds, not probabilities or evidence of accumulation.':'En vue 24H uniquement, les scores z du prix et de l’activité sont comparés. Un écart absolu supérieur à 1,2 est signalé. L’activité utilise le volume sur 24 heures et n’est pas comparée aux autres périodes de performance. Ces seuils sont heuristiques : ni probabilités, ni preuves d’accumulation.',
    'Market observations come from CoinGecko. LunarCrush readings are separate context and do not determine these signals. FRED observations have their own publication dates. Extreme outliers and the composition of the reference can affect the result. This compares different assets at one moment, not an asset against its own history.':'Les observations de marché viennent de CoinGecko. LunarCrush constitue un contexte distinct, sans déterminer ces signaux. Les observations FRED ont leurs propres dates de publication. Les valeurs extrêmes et la composition de la référence peuvent influencer le résultat. La comparaison porte sur différents actifs au même instant, pas sur un actif face à son propre historique.',
    'Signals are suppressed when market data is older than three minutes or its age cannot be determined. Assets with a supplied price timestamp older than three minutes are also excluded. Legacy snapshots may only provide a collection time. A zero signal count does not guarantee low risk.':'Les signaux sont désactivés lorsque les données de marché ont plus de trois minutes ou que leur ancienneté est inconnue. Les actifs dont le prix est daté de plus de trois minutes sont également exclus. Les anciens instantanés peuvent ne fournir qu’une heure de collecte. Zéro signal ne garantit pas un risque faible.',
    'Unavailable':'Indisponible','Unknown':'Inconnue','Just now':'À l’instant','{n}m ago':'Il y a {n} min','{n}h ago':'Il y a {n} h','{n}d ago':'Il y a {n} j',
    '1-hour':'1 heure','24-hour':'24 heures','7-day':'7 jours','30-day':'30 jours',
    '7D':'7J','30D':'30J','{n} coin':'{n} crypto',
    'Your watchlist is limited to 50 coins.':'Les favoris sont limités à 50 cryptos.',
    'Browser storage is unavailable. Export your watchlist to keep it.':'Le stockage du navigateur est indisponible. Exportez vos favoris pour les conserver.',
    'Your selection':'Votre sélection','Market preview':'Aperçu du marché','{n} coins':'{n} cryptos',' · {n} unavailable':' · {n} indisponibles',' · mean {value}':' · moyenne {value}',
    '{period} performance · USD':'Performance sur {period} · USD','{n} of 50 selected':'{n} sur 50 sélectionnées','{n} / 50 selected':'{n} / 50 sélectionnées',
    'Received {age}':'Reçu {age}','Market data: {state} · {age}':'Marché : {state} · {age}','Snapshot collected {date}':'Instantané collecté le {date}',
    'Connection interrupted · retrying':'Connexion interrompue · nouvelle tentative','Connecting':'Connexion en cours','Same-origin data':'Données de même origine',
    'Market {value}':'Marché {value}','BTC dominance {value}%':'Dominance BTC {value} %','Current':'À jour','current':'à jour','stale':'anciennes','unavailable':'indisponibles','unknown':'inconnues','disabled':'désactivées',
    'Collected {age}':'Collecté {age}','Collected {date}':'Collecté le {date}','Collection time unavailable':'Heure de collecte indisponible','observed':'observé','Broad USD':'Dollar large',
    '{n} assets covered · context only':'{n} actifs couverts · contexte uniquement','{period} · {n} reference assets':'{period} · {n} actifs de référence',
    'No active signals':'Aucun signal actif','No thresholds crossed in this selection.':'Aucun seuil franchi dans cette sélection.','Waiting for market data':'En attente des données de marché',
    'Signals will appear after a valid snapshot arrives.':'Les signaux apparaîtront après réception d’un instantané valide.','Signals paused':'Signaux suspendus','Current market data is required.':'Des données de marché à jour sont nécessaires.',
    'Your signals start here':'Vos signaux commencent ici','Choose the coins you want to follow.':'Choisissez les cryptos à suivre.','Signals unavailable':'Signaux indisponibles',
    'The selected period needs valid returns and at least 20 reference assets.':'La période choisie nécessite des performances valides et au moins 20 actifs de référence.',
    'Some assets have insufficient or stale data.':'Les données de certains actifs sont insuffisantes ou anciennes.',
    'Price anomalies only. Activity comparisons are available in 24H.':'Anomalies de prix uniquement. Les comparaisons d’activité sont disponibles en 24H.',
    'Unusual rise':'Hausse inhabituelle','Unusual decline':'Baisse inhabituelle','Unusual turnover':'Activité inhabituelle','Price stronger than activity':'Prix plus fort que l’activité','Activity stronger than price':'Activité plus forte que le prix',
    '24H z-score gap · threshold > 1.2':'Écart de scores z 24H · seuil > 1,2','{period} z-score · threshold {threshold}':'Score z {period} · seuil {threshold}',
    'A little more focus.':'Un peu plus de recul.','Your chosen coins will appear here.':'Vos cryptos apparaîtront ici.','Market data unavailable':'Données de marché indisponibles',
    'We will retry automatically. Your watchlist is kept.':'Nouvelle tentative automatique. Vos favoris sont conservés.','No matching coins':'Aucune crypto correspondante',
    'Nothing in this selection matches the current filter.':'Aucun actif de cette sélection ne correspond au filtre.','Selected coins unavailable':'Cryptos sélectionnées indisponibles',
    'Your selection is kept until these assets return to the feed.':'Votre sélection est conservée jusqu’au retour de ces actifs dans les données.','DIVERGENCE':'DIVERGENCE','ANOMALY':'ANOMALIE',
    'Add {name}':'Ajouter {name}','Remove {name}':'Retirer {name}','Loading coins...':'Chargement des cryptos…','Market data is unavailable.':'Les données de marché sont indisponibles.',
    'No selected coins match.':'Aucun favori correspondant.','No matching coin in the current feed.':'Aucune crypto correspondante dans les données actuelles.',
    'Price anomaly':'Anomalie de prix','Turnover anomaly':'Anomalie d’activité','Price / activity gap':'Écart prix / activité','24H only':'24H uniquement','Insufficient activity data':'Données d’activité insuffisantes','Within threshold':'Seuil non franchi',
    'Market data is not current':'Les données de marché ne sont pas à jour','Asset price is stale':'Le prix de cet actif est trop ancien','Return unavailable for this period':'Performance indisponible sur cette période','Insufficient reference coverage':'Référence insuffisante',
    'No thresholds crossed':'Aucun seuil franchi','{n} signal detected':'{n} signal détecté','{n} signals detected':'{n} signaux détectés','z-score':'score z','z gap':'écart z',
    '{price} price / {activity} activity peers · CoinGecko':'{price} références prix / {activity} activité · CoinGecko',
    'Cross-asset comparison, not a buy or sell signal.':'Comparaison entre actifs, pas un signal d’achat ou de vente.','Methodology':'Méthodologie','Asset details':'Détails de l’actif','Market data':'Données de marché',
    'This asset is no longer in the current snapshot.':'Cet actif n’est plus présent dans l’instantané actuel.','Remove from watchlist':'Retirer des favoris','Add to watchlist':'Ajouter aux favoris',
    'Price observed {date}':'Prix observé le {date}','Price observation time unavailable':'Heure d’observation du prix indisponible',' · snapshot collected {date}':' · instantané collecté le {date}',
    '7-day price history':'Historique du prix sur 7 jours','7-day price history · CoinGecko':'Historique du prix sur 7 jours · CoinGecko','Social context':'Contexte social',
    'Galaxy Score {score}/100{sentiment} · LunarCrush, {date}. Symbol-based match; indicative only.':'Galaxy Score {score}/100{sentiment} · LunarCrush, {date}. Correspondance par symbole, indicative uniquement.',
    ' · sentiment {value}%':' · sentiment {value} %','LunarCrush data unavailable for this asset.':'Données LunarCrush indisponibles pour cet actif.',
    '24H volume':'Volume 24H','All-time high':'Plus haut historique','Circulating supply':'Quantité en circulation','View on CoinGecko':'Voir sur CoinGecko',
    'Watchlist files must be smaller than 16 KB.':'Le fichier de favoris doit peser moins de 16 Ko.','{n} coins in this file. Display preferences will also be restored.':'{n} cryptos dans ce fichier. Les préférences d’affichage seront aussi restaurées.',
    '{n} coins after import':'{n} cryptos après import',' · {n} currently unavailable; identifiers will be kept.':' · {n} actuellement indisponibles ; les identifiants seront conservés.',
    'Watchlist imported.':'Favoris importés.','Full screen is not supported by this browser.':'Le plein écran n’est pas pris en charge par ce navigateur.','Full screen could not be opened.':'Le plein écran n’a pas pu être ouvert.',
    'File exceeds 16 KB':'Le fichier dépasse 16 Ko','Invalid JSON file':'Fichier JSON invalide','Expected an Orbit2 watchlist with up to 50 coins':'Un fichier de favoris Orbit2 contenant au plus 50 cryptos est requis','Invalid coin identifier':'Identifiant de crypto invalide','This selection exceeds 50 coins':'Cette sélection dépasse 50 cryptos',
    '{label}: {value} {unit}. Threshold {rule} {threshold}':'{label} : {value} {unit}. Seuil {rule} {threshold}','z-score gap':'écart de scores z','above':'supérieur à','absolute value above':'en valeur absolue supérieur à',
    'Legal navigation':'Navigation des mentions légales','App':'Application','Legal, privacy and GDPR':'Mentions légales, vie privée et RGPD',
    'Clear terms for a l0g Lab crypto signal app.':'Un cadre clair pour une application crypto de l0g Lab.',
    'Orbit2 is a privacy-first crypto heatmap published as a l0g Lab experiment. The public app is static, same-origin and watchlist-first: no account, no advertising tracker, no browser call to CoinGecko, LunarCrush, FRED or any other data provider.':'Orbit2 est une carte de marché crypto respectueuse de la vie privée, publiée comme une expérimentation l0g Lab. L’application publique est statique, servie depuis la même origine et centrée sur vos favoris : sans compte, sans traceur publicitaire et sans appel du navigateur à CoinGecko, LunarCrush, FRED ou à un autre fournisseur de données.',
    'Short version':'En bref','No public account.':'Sans compte public.','Favorites are stored locally in your browser.':'Les favoris sont conservés localement dans votre navigateur.',
    'No ad tracking.':'Sans suivi publicitaire.','No analytics cookie, social pixel or remote font.':'Aucun cookie analytique, pixel social ou police distante.',
    'Static snapshot.':'Instantané statique.','Market data is fetched server-side and served from orbit.l0g.fr.':'Les données de marché sont collectées côté serveur et servies depuis orbit.l0g.fr.',
    'Key legal facts':'Informations légales essentielles','Publisher':'Éditeur','Updated':'Mis à jour','Publisher and hosting':'Éditeur et hébergement',
    'Orbit2 is operated and published by':'Orbit2 est exploité et publié par',
    ', an independent research and data project focused on macroeconomics, markets, public sources, systemic risk and machine-readable financial intelligence. The project is run by bluetouff.':', un projet indépendant de recherche et de données sur la macroéconomie, les marchés, les sources publiques, le risque systémique et l’information financière exploitable par les machines. Le projet est porté par bluetouff.',
    'Contact and rights requests:':'Contact et demandes relatives aux droits :','Hosting:':'Hébergement :','self-hosted by the publisher on infrastructure he administers.':'auto-hébergement par l’éditeur sur une infrastructure qu’il administre.',
    'Relationship to third parties:':'Liens avec les tiers :','Orbit2 is not affiliated with CoinGecko, CoinDesk, LunarCrush, FRED, the St. Louis Fed or the crypto assets shown in the interface.':'Orbit2 n’est affilié ni à CoinGecko, CoinDesk, LunarCrush, FRED, la Fed de Saint-Louis, ni aux actifs crypto présentés.',
    'Personal data and GDPR / RGPD':'Données personnelles et RGPD',
    'The public Orbit2 app is designed as a low-data, read-only surface. It does not require a public user account, does not ask visitors to create a profile, and does not set advertising or behavioral analytics cookies.':'L’application publique Orbit2 est conçue pour limiter les données traitées et fonctionne en lecture seule. Elle ne requiert pas de compte, ne demande pas de créer un profil et ne dépose pas de cookies publicitaires ou d’analyse comportementale.',
    'Data that may be processed':'Données susceptibles d’être traitées','Why it is processed':'Finalités du traitement',
    'Technical server logs: IP address, timestamp, requested URL, status code and user-agent.':'Journaux techniques du serveur : adresse IP, horodatage, URL demandée, code de réponse et agent utilisateur.',
    'Security and abuse signals needed to operate the service and investigate incidents.':'Signaux de sécurité et d’abus nécessaires au fonctionnement du service et à l’analyse des incidents.',
    'Messages you send voluntarily by email, including your email address and the content of the request.':'Messages envoyés volontairement par courriel, dont votre adresse et le contenu de la demande.',
    'Browser-local favorites stored through':'Favoris conservés dans le navigateur via','on your device only.':'sur votre appareil uniquement.',
    'Operate the public app and static snapshot endpoints.':'Faire fonctionner l’application publique et ses points d’accès aux instantanés statiques.',
    'Secure the service and prevent abuse.':'Sécuriser le service et prévenir les abus.','Respond to legal, privacy, support or research requests.':'Répondre aux demandes juridiques, de confidentialité, d’assistance ou de recherche.',
    'Monitor reliability without profiling individual visitors.':'Surveiller la fiabilité sans établir de profil individuel des visiteurs.',
    'Legal basis.':'Base légale.','Processing is based on legitimate interest for security and service operation, consent when you voluntarily contact the publisher, and legal obligation where applicable.':'Le traitement repose sur l’intérêt légitime pour la sécurité et le fonctionnement du service, le consentement lorsque vous contactez volontairement l’éditeur et l’obligation légale lorsque celle-ci s’applique.',
    'Cookies, local storage and third parties':'Cookies, stockage local et tiers','Cookies and trackers':'Cookies et traceurs','Local favorites':'Favoris locaux',
    'The public app does not use advertising cookies, social tracking pixels, third-party analytics tags or remote fonts. The Content Security Policy restricts scripts, styles and network requests to the same origin.':'L’application publique n’utilise ni cookies publicitaires, ni pixels de suivi social, ni balises d’analyse tierces, ni polices distantes. La politique de sécurité du contenu limite les scripts, styles et requêtes réseau à la même origine.',
    'Your watchlist is stored locally in your browser under':'Vos favoris sont conservés localement dans votre navigateur sous',', and display preferences under':', et les préférences d’affichage sous',
    '. They are not sent to the server, not attached to an account and can be cleared from your browser storage. Watchlist import reads your selected JSON file on this device; export downloads a local file. Neither operation uploads your selection.':'. Ils ne sont pas envoyés au serveur, ne sont associés à aucun compte et peuvent être supprimés du stockage du navigateur. L’import lit le fichier JSON choisi sur cet appareil ; l’export télécharge un fichier local. Aucune de ces opérations ne transmet votre sélection.',
    'Your language preference is stored locally under':'Votre préférence de langue est conservée localement sous','Server-side data providers':'Fournisseurs de données côté serveur',
    'CoinGecko, LunarCrush and FRED are contacted by the server-side builder only. Visitors receive a static same-origin snapshot and self-hosted logos; their browser does not contact those providers.':'Seul le collecteur côté serveur contacte CoinGecko, LunarCrush et FRED. Les visiteurs reçoivent un instantané statique de même origine et des logos auto-hébergés ; leur navigateur ne contacte pas ces fournisseurs.',
    'External links':'Liens externes','External sites, including l0g.fr, CoinGecko, CoinDesk, GitHub or CNIL, are contacted only when you choose to open a link.':'Les sites externes, notamment l0g.fr, CoinGecko, CoinDesk, GitHub ou la CNIL, ne sont contactés que lorsque vous choisissez d’ouvrir un lien.',
    'Your rights':'Vos droits','Under the GDPR / RGPD, you can request access, rectification, erasure, restriction, objection and portability where applicable. Send requests to':'En vertu du RGPD, vous pouvez demander l’accès, la rectification, l’effacement, la limitation, l’opposition et la portabilité lorsque ces droits s’appliquent. Adressez vos demandes à',
    '. A reasonable identity verification may be required before disclosure or deletion.':'. Une vérification raisonnable de votre identité peut être requise avant communication ou suppression.',
    'If you believe your request was not handled correctly, you can contact the French data protection authority:':'Si vous estimez que votre demande n’a pas été traitée correctement, vous pouvez contacter l’autorité française de protection des données :',
    'Data, sources and liability boundary':'Données, sources et limites de responsabilité',
    'Orbit2 displays crypto market data and derived cross-sectional signals for research and monitoring. Provider data may contain delays, corrections, symbol mismatches, missing logos or source inconsistencies. Signals, scores, divergences, anomalies and heatmap sizes are not personalized recommendations, investment advice, solicitation, execution guidance, probability estimates or performance promises.':'Orbit2 présente des données de marché crypto et des signaux transversaux dérivés à des fins de recherche et de suivi. Les données peuvent présenter des retards, corrections, ambiguïtés de symboles, logos manquants ou incohérences. Les signaux, scores, divergences, anomalies et tailles des tuiles ne constituent ni recommandations personnalisées, ni conseils d’investissement, ni sollicitations, ni consignes d’exécution, ni estimations de probabilité, ni promesses de performance.',
    'You remain responsible for your own diligence, risk controls and regulatory framework. Always verify material decisions against primary sources and provider documentation.':'Vous restez responsable de vos vérifications, de votre maîtrise des risques et du cadre réglementaire qui vous concerne. Confrontez toute décision importante aux sources primaires et à la documentation des fournisseurs.',
    'Intellectual property':'Propriété intellectuelle','The Orbit2 software and repository documentation are available under the':'Le logiciel Orbit2 et la documentation du dépôt sont disponibles sous la','MIT License':'licence MIT',
    ". Copyright and license notices must be preserved. Third-party market data, provider services and cryptocurrency logos remain governed by their owners' terms and are not relicensed under MIT.":'. Les mentions de droit d’auteur et de licence doivent être conservées. Les données de marché tierces, les services des fournisseurs et les logos crypto restent soumis aux conditions de leurs titulaires et ne sont pas placés sous licence MIT.',
    'Back to Orbit2':'Retour à Orbit2','l0g Lab · no trackers · same-origin data':'l0g Lab · sans traceurs · données de même origine'
  };
  function translate(key,language,values={}){
    const source=String(key),message=language==='fr'&&Object.hasOwn(fr,source)?fr[source]:source;
    return message.replace(/\{([a-zA-Z]+)\}/g,(match,name)=>Object.hasOwn(values,name)?String(values[name]):match);
  }
  let language='en';
  const api={t:(key,values)=>translate(key,language,values),translate,get language(){return language;}};
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.OrbitI18n=api;
  if(!root.document)return;
  const storageKey='orbit.locale.v1';
  try{const saved=localStorage.getItem(storageKey);language=['fr','en'].includes(saved)?saved:navigator.language.toLowerCase().startsWith('fr')?'fr':'en';}catch{language=navigator.language.toLowerCase().startsWith('fr')?'fr':'en';}
  // Keep the original static text nodes, including those beside links or code tags.
  // Dynamic app content is translated explicitly when rendered, never via HTML insertion.
  const nodes=[],attributes=[],walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){const node=walker.currentNode;if(node.textContent.trim()&&!['SCRIPT','STYLE'].includes(node.parentElement.tagName))nodes.push([node,node.textContent]);}
  for(const element of document.querySelectorAll('[title],[placeholder],[aria-label]'))for(const name of ['title','placeholder','aria-label'])if(element.hasAttribute(name))attributes.push([element,name,element.getAttribute(name)]);
  const title=document.title;
  function apply(){
    document.documentElement.lang=language;document.title=api.t(title);
    for(const [node,source]of nodes)if(node.isConnected)node.textContent=source.replace(source.trim(),api.t(source.trim()));
    for(const [element,name,source]of attributes)element.setAttribute(name,api.t(source));
    document.querySelectorAll('[data-lang]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.lang===language)));
    document.querySelectorAll('[data-support]').forEach(a=>a.href=language==='fr'?'https://l0g.fr/soutenir/':'https://l0g.fr/en/support/');
  }
  document.querySelectorAll('[data-lang]').forEach(b=>b.addEventListener('click',()=>{
    if(!['fr','en'].includes(b.dataset.lang))return;
    language=b.dataset.lang;try{localStorage.setItem(storageKey,language);}catch{}
    apply();document.dispatchEvent(new CustomEvent('orbit:language'));
  }));
  apply();
})(globalThis);
