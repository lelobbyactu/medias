# Montage et publication (lu au moment de monter et publier)

## 7. Montage d'un clip (format 9:16 unique pour Instagram et TikTok, décision d'Alix du 22 nov. 2026)
Une seule vidéo par clip, publiée telle quelle sur les deux réseaux : bande titre DA, webcam du streamer, bande noire (future place des sous-titres), gameplay recadré en 4:3. L'ancien format (`make_reel.py`, clip 16:9 au milieu) n'est plus qu'un **secours**, pour les exceptions.
1. Le clip est déjà dans `/tmp/clip.mp4` (fait par `python3 scripts/lobby.py take <id>`). `take` cherche tout seul le même moment en clip Twitch et, s'il le trouve, remplace `/tmp/clip.mp4` par la version d'origine 1080p60 ou plus (original X dans `/tmp/clip_x.mp4`). Lire le champ `twitch` : si `found`, le crédit est `twitch.tv/<chaîne>` et `twitch.channel` sert au montage ; sinon crédit X. `found: false` n'est jamais bloquant.
2. Numéro et nom du post : `python3 scripts/lobby.py reserve <id> reel Clips` → `NNNN-JJ_MM_AAAA-Clips`.
3. **Montage** : `python3 scripts/make_reel_916.py --video /tmp/clip.mp4 --post <nom> --title "Ligne 1|Ligne 2 *mot*" [--start S --end E] [--channel <twitch.channel>] 2>&1 | grep -v WARN` (~1 min ; couper les temps morts, 15-60 s). Il trouve seul la webcam (pleine largeur, ou plus petite et centrée si elle est petite ; mise en page sans webcam s'il n'y en a pas) et place le cadre du jeu à côté. Pas de crédit à l'écran : il est dans la légende.
4. **Garde-fou** (`docs/juge.md` §6bis) sur `posts/<nom>/<nom>_planche.jpg` (une seule image) :
   - **OK** → publier sur Instagram et TikTok (même vidéo, §8).
   - **SPONSOR** (logo de marque d'un overlay ou QR visible ; aussi si le script a renvoyé `"qr": true`) → même vidéo, **Instagram seul**.
   - **NON** → une seule correction si le défaut est le cadrage (`--cam x,y,w,h` ou `--no-cam` ou `--game-x X`, espace 1920x1080) puis nouveau garde-fou ; sinon **secours**.
5. **Secours** (exception : `"ok": false` du script, cinématique, action coupée, NON après correction) : `python3 scripts/make_reel.py --video /tmp/clip.mp4 --post <nom> --title "<même titre>" --credit-label CLIP --credit "<crédit>" [--start S --end E]` (il remplace `<nom>.mp4` et `<nom>_cover.jpg`), relire `<nom>_cover.jpg`, puis **Instagram seul**. Rapport : « secours : <raison> ».
6. Après un OK ou un SPONSOR, si la chaîne n'est pas encore dans `config.json` → `tiktok_layouts` : `python3 scripts/make_reel_916.py --video /tmp/clip.mp4 --post <nom> --channel <chaîne> --check-only --save-layout --out-dir /tmp/chk 2>&1 | grep -v WARN` (mémorise la webcam ; `config.json` part avec le push du post).
7. Vérifier la durée, la présence du son (`has_audio`), la taille (< 100 Mo). `_planche.jpg` et `_fond.png` restent dans le dossier du post (archive), jamais publiés.

## 7bis. Montage d'un carrousel (une commande)
1. Écrire la spec JSON (modèle complet : `scripts/exemple_carousel.json` = post 0008) dans `/tmp/spec.json` : `post` (`NNNN-JJ_MM_AAAA-<Catégorie>` : Chiffres, Actu, Streamers, Esport, Leak…), `rubrique`, `image`, `image_credit`, `slides` (types cover, split, bars, versus, cards, text ; doc en tête du script).
2. `python3 scripts/make_carousel.py --spec /tmp/spec.json` → `posts/<nom>/<nom>_01.jpg`… + une planche de contrôle.
3. **Relire visuellement la seule planche de contrôle** (un seul `Read`, pas les JPG un par un) : rien de coupé, rien qui chevauche le pied de page, un seul surligneur par titre, chiffres justes. Un message « ATTENTION … déborde » = raccourcir le texte et relancer (une fois).

## 8. Publication
1. **Réserver** : déjà fait par `lobby.py reserve` (étape montage). Si le script signale un autre post `en_cours` sur le même sujet, abandonner.
2. Pousser : `python3 scripts/lobby.py push "post <nom>" posts/<nom>` (réessaie seul en cas de conflit). Attendre que `https://raw.githubusercontent.com/lelobbyactu/medias/main/posts/<nom>/<nom>.mp4` (ou le 1er JPG) réponde 200 (`curl -sI`).
3. Zernio : `validate_post`, puis `call_tool` → `posts_create_post` avec :
```
publish_now: true
content: <description>
media_items: [{"type":"video","url":"<url raw de <nom>.mp4>"}]
platforms: [
 {"platform":"instagram","accountId":"6afdabaa129402676fdefe98","platformSpecificData":{"contentType":"reels","instagramThumbnail":"<url raw de la cover>"}},
 {"platform":"tiktok","accountId":"6afdabc00ebbceefd4b2d727"}]
tiktok_settings: {"privacyLevel":"PUBLIC_TO_EVERYONE","allowComment":true,"allowDuet":true,"allowStitch":true,"commercialContentType":"none","contentPreviewConfirmed":true,"expressConsentGiven":true}
```
   **Reel** : un seul post pour les deux réseaux avec `<nom>.mp4` (format 9:16) ; `content` = la description, qui contient toujours la ligne de crédit (`Clip : twitch.tv/<chaîne>` ou `x.com/<compte>`), car le crédit n'est plus à l'écran. Retirer la plateforme `tiktok` (Instagram seul) si : verdict SPONSOR, secours (§7.5), ou pause TikTok.
   **Carrousel** : `media_items` = la liste des JPG dans l'ordre (`{"type":"image","url":"<url raw>"}`), `platforms` = Instagram et TikTok sans `platformSpecificData`, `tiktok_settings` = `{"privacyLevel":"PUBLIC_TO_EVERYONE","allowComment":true,"commercialContentType":"none","contentPreviewConfirmed":true,"expressConsentGiven":true,"mediaType":"photo","photoCoverIndex":0,"autoAddMusic":true,"description":"<légende complète>"}`. Dans le journal, `type: "carrousel"`.
   **Carrousel sur TikTok (règle du 22 nov. 2026)** : Zernio prend `content` comme titre TikTok (90 caractères max) et en retire les hashtags. Donc `content` = le titre du carrousel en texte clair, sans hashtag ; la légende complète (1re phrase accrocheuse avec les mots-clés du sujet, puis 3 à 5 hashtags) va dans `tiktok_settings.description`. Ne jamais envoyer un carrousel TikTok dont le texte ne contient que des hashtags (c'était le cas de plusieurs carrousels déjà publiés : titre et description vides). `autoAddMusic: true` : TikTok choisit la musique.
   (Si `validate_post` refuse un champ, retirer ce champ et revalider ; ne jamais publier sans validation.)
4. Vérifier avec `posts_get` / la réponse (statut `published`, `platformPostUrl`). Une plateforme en échec : `posts_retry` une fois ; si ça échoue encore, noter `echec` pour cette plateforme (l'autre reste publiée).
5. **Journal** : `python3 scripts/lobby.py done <nom> --ig <url> --tiktok <url> --zernio <id> --judge 8/10 --slot 12h` (ou `--hot leak|embrouille|5_comptes`). Il passe le post et le sujet de la file à `publie`. Échec partout : `python3 scripts/lobby.py fail <nom> "<raison>"` (le sujet retourne en file s'il n'a pas expiré).
6. Sorties de commandes : toujours silencieuses (`-q`, `| tail -3`), ne jamais afficher un JSON entier.
