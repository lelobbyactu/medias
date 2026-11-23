# Album d'inspiration (lu par la tâche « Inspirations », 1×/jour)

Alix enregistre des posts d'autres comptes (Instagram, TikTok, X, YouTube…) qui l'inspirent, sur le fond ou la forme, via le raccourci iPhone « Lobby inspi » : chaque lien devient une issue GitHub `inspi` de ce dépôt (la note éventuelle d'Alix est dans `note_alix` : elle dit souvent ce qui lui plaît, en tenir compte en priorité). Le but : **garder les meilleurs selon les critères du juge et en reprendre la recette dans notre DA**, jamais le contenu.

## Déroulé
1. `python3 scripts/inspi.py list` → liens à traiter (10 max par exécution, les plus anciens d'abord). Rien → « RAS inspirations » et fin.
2. Pour chaque lien : `python3 scripts/inspi.py fetch <n>` → une planche (6 images) + légende + stats.
   - `need_media` sur **Instagram** : Apify `apify/instagram-scraper` (call-actor, input `{"directUrls":["<url>"],"resultsType":"posts","resultsLimit":1}`, waitSecs 45), puis lis `videoUrl,displayUrl,images,caption,likesCount,commentsCount,videoViewCount,ownerUsername,timestamp,type` et relance `fetch <n> --media <videoUrl, sinon images ou displayUrl> --caption "<caption>" --stats '{"likes":…,"comments":…,"views":…,"auteur":"…"}'`.
   - **X** : Apify `xquik/x-tweet-scraper` (`searchTerms: ["conversation_id:<id du tweet>"]`, maxItems 1), puis `--media` avec la variante vidéo ou l'image.
   - Toujours rien : verdict `ecarte`, format `illisible`, et le signaler dans le rapport.
3. Lis UNE planche par lien (Read) + la légende. Pas de transcription, pas d'analyse plan par plan.
4. **Juge** : un seul sous-agent au contexte vierge (outil Agent, general-purpose) pour tout le lot, avec les planches (chemins), légendes, stats, notes d'Alix et cette grille. Pour chaque post il rend : score /10, verdict `garde` (≥ 7) ou `ecarte`, format, et une **recette** de 2 à 3 lignes.
   - Grille /10 : sujet + accroche (titre, 1re slide, 1re seconde) 0-4 · nom connu / sujet hype pour notre public (créateurs FR, Twitch, JV mainstream) 0-3 · clarté en 2 s 0-1 · format reproductible dans notre DA 0-1 · originalité de l'idée par rapport à ce qu'on fait déjà 0-1.
   - Critères d'Alix : aller à l'essentiel (pourquoi ça marche, pas la description de tous les plans) ; le combo sujet + titre prime sur la qualité du montage ; une stat ou actu chiffrée se fait en image ; pas d'image IA, pas de voix IA, rien hors DA.
   - Format = `reel-clip` · `reel-info` · `carrousel-actu` · `carrousel-classement` · `image-unique` · `autre : <nom>`.
   - Recette = ce qu'on reprend : le type d'accroche (avec un exemple de titre à la manière du Lobby, en français), la structure (ordre des slides ou des moments), et quand l'utiliser.
5. Pour chaque post **gardé** :
   - **Sujet encore frais** (actu < 6 h, clip < 24 h depuis la source d'origine) et dans notre ligne : l'ajouter à la file comme un sujet de la veille (`/tmp/add.json` puis `python3 scripts/lobby.py add /tmp/add.json`, `found_by: "inspi"`, `score` = note du juge, `angle` = la recette en 1 phrase, `source_url` = la source d'origine (créateur, éditeur), **jamais le post inspirant**). Le créneau le refera avec nos sources, nos visuels, notre DA.
   - **Idée intemporelle** (classement, comparaison, « ce qu'il faut savoir sur… ») notée ≥ 8 : l'ajouter à la file en `actu` avec `source_time_utc` = maintenant, `found_by: "inspi"` et dans `note` « refaire entièrement avec nos sources (recoupement docs/actus.md) ». Au plus une par exécution.
   - Sinon : la fiche suffit (exemple « Top » pour le juge).
6. `python3 scripts/inspi.py done <n> --url <url> --verdict garde|ecarte --score S --format F --recette "…" [--queue <id de la file>]` pour CHAQUE lien (même écarté), sinon il revient le lendemain. Les fiches gardées vont dans `juge/inspirations.md`, que le juge des créneaux lit comme exemples « Top ».
7. **Jamais** : republier le post d'un autre, reprendre son texte mot pour mot, ses images, sa musique ou son montage ; utiliser une photo de personne qui n'est pas dans `assets/photos/`. Un nouveau gabarit (format absent de notre DA) n'est **pas** créé tout seul : le proposer à Alix dans le rapport (« Gabarit à valider : … »).

## Rapport (court, en français)
« Inspirations : N analysées, G gardées, F en file » ; pour chaque gardée : note, format, recette en 1 ligne, lien ; « Gabarit à valider » s'il y a lieu ; liens illisibles.
