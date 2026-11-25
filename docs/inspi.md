# Album d'inspiration « Lobby inspi » (tâche « Inspirations », 1×/jour)

Alix enregistre des reels/posts d'autres comptes (Instagram, TikTok, X, YouTube…) via le raccourci iPhone « Lobby inspi » : chaque lien devient une issue GitHub `inspi` de ce dépôt. Corps de l'issue : `NOTE: <ce qui lui plaît ou non, avec une note /10 si possible : « 8/10 – le titre fait cliquer »> <lien>`.

Deux buts (décision d'Alix du 25 nov. 2026) :
1. **Calibrer le juge** : exemples « Top » et recette dans `juge/inspirations.md`, et comparaison de la note du juge avec celle d'Alix (`inspi.py calib`).
2. **Alimenter la file** : pour les 2 meilleurs reels du jour, retrouver le **clip Twitch brut** et le mettre en file, avec la note du juge. Il est refait dans notre DA (titre, sous-titres, description) ; il n'est publié que si un créneau n'a rien de mieux.

Jamais : republier le reel d'un autre, reprendre son montage, son titre ou son texte mot pour mot.

## Déroulé
1. `python3 scripts/inspi.py list` → liens à traiter (10 max, les plus anciens d'abord ; `note_alix` et `note_alix_sur_10`). Rien → « RAS inspirations » et fin.
2. Pour chaque lien : `python3 scripts/inspi.py fetch <n>` → planche (6 images), légende, stats, chemin `video`.
   - `need_media` sur **Instagram** : Apify `apify/instagram-scraper` (call-actor, input `{"directUrls":["<url>"],"resultsType":"posts","resultsLimit":1}`, waitSecs 45), puis relancer `fetch <n> --media <videoUrl, sinon images ou displayUrl> --caption "<caption>" --stats '{"likes":…,"comments":…,"views":…,"auteur":"…"}'`.
   - **X** : Apify `xquik/x-tweet-scraper` (`searchTerms: ["conversation_id:<id>"]`, maxItems 1), puis `--media`.
   - Toujours rien : verdict `ecarte`, format `illisible`, à signaler.
3. Lire UNE planche par lien (Read) + la légende. Pas de transcription.
4. **Juge** : un seul sous-agent au contexte vierge (Agent, general-purpose) pour tout le lot : planches, légendes, stats, notes d'Alix, cette grille. Pour chaque post : score /10, verdict `garde` (≥ 7) ou `ecarte`, format, **pourquoi** (1-2 lignes : ce qui marche ou non), **recette** (2-3 lignes), et pour un clip vidéo : `streamer` (login Twitch, d'après légende, pseudo à l'écran ou visage), `zone` du jeu ou de la webcam dans le reel (fractions `x,y,w,h` de l'image ; défaut moitié basse `0,0.5,1,0.5`).
   - Grille /10 : sujet + accroche 0-4 · nom connu / sujet hype pour notre public (créateurs FR, Twitch, JV mainstream) 0-3 · clarté en 2 s 0-1 · format reproductible dans notre DA 0-1 · originalité 0-1.
   - **La note d'Alix passe avant tout** : si `note_alix_sur_10` existe, le juge note d'abord à l'aveugle, puis voit l'écart (utile pour `calib`), et le verdict final suit Alix.
   - Format = `clip-jv` · `clip-just-chatting` · `clip-evenement` · `hors-ligne` (tout le reste : écarté).
5. Seuls les **clips vidéo** (jeu en stream, Just Chatting, événement) comptent : carrousel, image ou reel d'actu = `ecarte`.
6. **Retrouver le clip brut** pour les **2 meilleurs** `garde` seulement (les autres : `done` direct) :
   - `python3 scripts/inspi.py locate <n> --streamer <login> --time <publie_utc de fetch> --zone <x,y,w,h>` → `found`, `twitch_url`, `score`, `created_utc`, `title`, `views`. Le script compare la zone du reel aux clips Twitch du streamer créés dans les 72 h avant le post (seuil 0,85, au moins 80 % du passage retrouvé).
   - `found` faux (autre plateforme, moment jamais clippé, correspondance incertaine) : le reel reste une simple inspiration, rien en file. Ne jamais forcer une correspondance douteuse.
   - `found` vrai : **règles avant file** : fraîcheur selon la nature (12 h drama/événement, 48 h gameplay, comptées depuis la création du clip Twitch ; sinon rien en file) ; clip jamais déjà publié (la file le vérifie) ; Twitch uniquement.
   - `python3 scripts/inspi.py queue <n> --twitch-url <url> --streamer <login> --created <created_utc> --score <note du juge> --nature gameplay|drama|evenement --topic "<sujet en une phrase>" --angle "<recette>"`. Le clip entre dans la file comme n'importe quel candidat (champ `found_by: inspi`) : un créneau le prend seulement s'il est mieux classé que les clips venus de X, Twitch et Reddit, puis le juge des créneaux le note sur le vrai clip (seuil 7/10 ; validation d'Alix pour tout ce qui n'est pas un drama de la liste blanche).
   - Titre, sous-titres, description : refaits par notre montage (jamais ceux du reel) ; crédit au streamer.
7. `python3 scripts/inspi.py done <n> --url <url> --verdict garde|ecarte --score S --format F --recette "…" --pourquoi "…" [--note-alix N] [--brut <url twitch>] [--queue <id file>]` pour CHAQUE lien (même écarté), sinon il revient le lendemain.
8. `python3 scripts/inspi.py calib` une fois par semaine : écart moyen juge − Alix ; si ≥ 1 point ou plusieurs `trop_indulgent` / `trop_severe`, le dire à Alix et ajuster la grille.

## Rapport (court, en français)
« Inspirations : N analysées, G gardées » ; par gardée : note (et celle d'Alix), format, pourquoi, recette en 1 ligne, clip brut retrouvé ou non (mis en file ou non), lien ; liens illisibles ; écart de calibrage s'il y a de la matière.
