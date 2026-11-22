# Montage et publication (lu au moment de monter et publier)

## 7. Montage (une commande)
1. Le clip est déjà dans `/tmp/clip.mp4` (fait par `python3 scripts/lobby.py take <id>`, qui affiche aussi ffprobe).
   **Source Twitch (depuis le 22 nov.)** : `take` cherche tout seul le même moment en clip Twitch (comparaison d'images, ~1 min) et, s'il le trouve, remplace `/tmp/clip.mp4` par la version d'origine en 1080p60 ou plus, coupée sur le même passage (l'original X reste dans `/tmp/clip_x.mp4`). La version verticale fournie par Twitch est mise dans `/tmp/clip_portrait.mp4` (pas encore utilisée : réservée au futur format TikTok). Lire le champ `twitch` de la sortie : si `found` est vrai, le **crédit devient `twitch.tv/<chaîne>`** (`--credit-label CLIP --credit "twitch.tv/<chaîne>"`) et la ligne de crédit de la description aussi ; sinon rien ne change (clip X, crédit X). `found: false` n'est jamais une erreur bloquante.
2. Numéro et nom du post : `python3 scripts/lobby.py reserve <id> reel Clips` (ou `carrousel <Catégorie>`) réserve le numéro dans le journal et affiche `NNNN-JJ_MM_AAAA-<Catégorie>`.
3. `python3 scripts/make_reel.py --video /tmp/clip.mp4 --post <nom> --title "Ligne 1|Ligne 2 *mot*" --credit-label CLIP --credit "x.com/<origine>" [--start S --end E]` (couper les temps morts, garder le meilleur moment, 15-60 s ; le script choisit la mise en page selon le format du clip).
4. **Relire visuellement** : `Read` sur `posts/<nom>/<nom>_cover.jpg` → titre entier visible, rien de coupé ni qui chevauche, surligneur sur un seul groupe, crédit lisible. Un problème → corriger le titre (plus court) et relancer, une fois. Vérifier la durée, la présence du son, la taille (< 100 Mo).

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
media_items: [{"type":"video","url":"<url raw du mp4>"}]
platforms: [
 {"platform":"instagram","accountId":"6afdabaa129402676fdefe98","platformSpecificData":{"contentType":"reels","instagramThumbnail":"<url raw de la cover>"}},
 {"platform":"tiktok","accountId":"6afdabc00ebbceefd4b2d727"}]
tiktok_settings: {"privacyLevel":"PUBLIC_TO_EVERYONE","allowComment":true,"allowDuet":true,"allowStitch":true,"commercialContentType":"none","contentPreviewConfirmed":true,"expressConsentGiven":true}
```
   **Carrousel** : `media_items` = la liste des JPG dans l'ordre (`{"type":"image","url":"<url raw>"}`), `platforms` = Instagram et TikTok sans `platformSpecificData`, `tiktok_settings` = `{"privacyLevel":"PUBLIC_TO_EVERYONE","allowComment":true,"commercialContentType":"none","contentPreviewConfirmed":true,"expressConsentGiven":true,"mediaType":"photo","photoCoverIndex":0,"autoAddMusic":true,"description":"<légende complète>"}`. Dans le journal, `type: "carrousel"`.
   **Carrousel sur TikTok (règle du 22 nov. 2026)** : Zernio prend `content` comme titre TikTok (90 caractères max) et en retire les hashtags. Donc `content` = le titre du carrousel en texte clair, sans hashtag ; la légende complète (1re phrase accrocheuse avec les mots-clés du sujet, puis 3 à 5 hashtags) va dans `tiktok_settings.description`. Ne jamais envoyer un carrousel TikTok dont le texte ne contient que des hashtags (c'était le cas de plusieurs carrousels déjà publiés : titre et description vides). `autoAddMusic: true` : TikTok choisit la musique.
   (Si `validate_post` refuse un champ, retirer ce champ et revalider ; ne jamais publier sans validation.)
4. Vérifier avec `posts_get` / la réponse (statut `published`, `platformPostUrl`). Une plateforme en échec : `posts_retry` une fois ; si ça échoue encore, noter `echec` pour cette plateforme (l'autre reste publiée).
5. **Journal** : `python3 scripts/lobby.py done <nom> --ig <url> --tiktok <url> --zernio <id> --judge 8/10 --slot 12h` (ou `--hot leak|embrouille|5_comptes`). Il passe le post et le sujet de la file à `publie`. Échec partout : `python3 scripts/lobby.py fail <nom> "<raison>"` (le sujet retourne en file s'il n'a pas expiré).
6. Sorties de commandes : toujours silencieuses (`-q`, `| tail -3`), ne jamais afficher un JSON entier.
