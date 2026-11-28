# Album d'inspiration « Lobby inspi » (tâche « Inspirations », 1×/jour)

Alix enregistre des reels/posts d'autres comptes (Instagram, TikTok, X, YouTube…) via le raccourci iPhone « Lobby inspi » : chaque lien devient une issue GitHub `inspi` de ce dépôt. Corps de l'issue : `NOTE: <ce qui lui plaît ou non, avec une note /10 si possible : « 8/10 – le titre fait cliquer »> <lien>`.

## Règle « choix d'Alix » (28 nov. 2026) — prime sur tout le reste de ce doc et sur les autres docs
**La parole d'Alix passe au-dessus du juge.** Un clip vidéo qu'elle envoie, téléchargeable et d'assez bonne qualité (petit côté ≥ `config.json` → `alix_min_side_px`, 720 px), **passe toujours en production**, sur la **vraie vidéo**, quels que soient la note du juge, la présence d'un streamer, le jeu, la fraîcheur, le format ou les exclusions éditoriales. Pas de limite à 2 par jour. Elle choisit à la fin sur Telegram (« Poster » / « Non ») : jamais de publication sans son clic.
- Le juge note quand même chaque post (information et calibrage). Sa note ne bloque rien.
- Ordre : ses choix passent avant tous les autres, à la production comme aux créneaux ; entre eux, sa note /10 (sans note chiffrée = 10).
- Sa note écrite compte : si elle dit de ne pas le publier, ou qu'elle ne retient qu'un élément (« juste le titre », « pour l'idée »), appliquer ce qu'elle dit et ne rien mettre en file.
- Seuls blocages : vidéo introuvable ou qualité insuffisante (essayer Apify et la meilleure définition avant d'abandonner) ; contenu illégal ou interdit par les plateformes (mineurs sexualisés, nudité explicite, violence réelle ou gore). Toujours le lui dire.
- Point sensible (accusation, politique, drame, musique ou marque visible, qualité limite) : le clip part quand même, avec `--avertissement` (affiché sur Telegram).
- GTA VI : un clip drôle ou impressionnant **sans streamer** est accepté (sa décision) ; l'absence de nom connu n'écarte jamais un de ses envois.

Buts :
1. **Mettre ses choix en production** (ci-dessus).
2. **Calibrer le juge** : exemples « Top » et recette dans `juge/inspirations.md`, comparaison de la note du juge avec celle d'Alix (`inspi.py calib`).

Source à utiliser, dans l'ordre : le **clip Twitch brut** s'il est retrouvé avec certitude (meilleure qualité, montage complet dans notre DA) ; sinon **la vidéo du post** (« reprise ») : crédit au compte qui l'a publiée, **filigranes et signatures jamais rognés ni masqués**, notre titre (jamais le leur mot pour mot), `docs/montage.md` §7ter.

## Déroulé
1. `python3 scripts/inspi.py list` → liens à traiter (10 max, les plus anciens d'abord ; `note_alix` et `note_alix_sur_10`). Rien → « RAS inspirations » et fin.
2. Pour chaque lien : `python3 scripts/inspi.py fetch <n>` → planche (6 images), légende, stats, `compte`, chemin `video` (meilleure définition jusqu'à 1080p).
   - `need_media` sur **Instagram** : Apify `apify/instagram-scraper` (call-actor, input `{"directUrls":["<url>"],"resultsType":"posts","resultsLimit":1}`, waitSecs 45), puis relancer `fetch <n> --media <videoUrl, sinon images ou displayUrl> --caption "<caption>" --stats '{"likes":…,"comments":…,"views":…,"auteur":"…"}'`.
   - **X** : Apify `xquik/x-tweet-scraper` (`searchTerms: ["conversation_id:<id>"]`, maxItems 1), puis `--media`.
   - Toujours rien : verdict `ecarte`, format `illisible`, à signaler.
3. Lire UNE planche par lien (Read) + la légende. Pas de transcription.
4. **Juge** : un seul sous-agent au contexte vierge (Agent, general-purpose) pour tout le lot : planches, légendes, stats, notes d'Alix, cette grille et la règle « choix d'Alix ». Pour chaque post : score /10, **pourquoi** (1-2 lignes), **recette** (2-3 lignes), format, `streamer` (login Twitch ou « aucun », d'après légende, pseudo à l'écran ou visage), `zone` du jeu ou de la webcam dans le reel (fractions `x,y,w,h` ; défaut `0,0.5,1,0.5`), zone à garder pour une reprise (sans bandes noires ni texte de titre, filigranes conservés) et tout point sensible.
   - Grille /10 : sujet + accroche 0-4 · nom connu / sujet hype pour notre public (créateurs FR, Twitch, JV mainstream ; GTA VI compte même sans streamer) 0-3 · clarté en 2 s 0-1 · format reproductible dans notre DA 0-1 · originalité 0-1.
   - Si `note_alix_sur_10` existe : le juge note d'abord à l'aveugle, puis voit l'écart (utile pour `calib`).
   - Format = `clip-jv` (jeu vidéo, avec ou sans streamer) · `clip-just-chatting` · `clip-evenement` · `hors-ligne` (autre).
   - **Verdict = celui d'Alix** : tout clip vidéo qu'elle envoie = `garde` (sauf si sa note dit le contraire ou blocage ci-dessus). Image ou carrousel sans vidéo = `ecarte`, le lui dire.
5. Pour **chaque** clip `garde` avec un streamer identifié : `python3 scripts/inspi.py locate <n> --streamer <login> --time <publie_utc de fetch> --zone <x,y,w,h>` (compare la zone du reel aux clips Twitch du streamer créés dans les 72 h avant le post ; seuil 0,85, au moins 80 % du passage retrouvé). Ne jamais forcer une correspondance douteuse.
6. Mise en file (chaque clip `garde`) :
   - Clip brut trouvé : `python3 scripts/inspi.py alix <n> --twitch-url <url> --streamer <login> --created <created_utc> --score <note du juge> [--note-alix N] --topic "<sujet en une phrase>" --angle "<recette + ce qu'Alix a aimé>"`.
   - Sinon : `python3 scripts/inspi.py alix <n> --url <url du post> --auteur "<compte>" --credit "instagram.com/<compte>" [--crop x,y,w,h] --score <note du juge> [--note-alix N] --topic "…" --angle "…" [--avertissement "…"]` (`--credit` selon la plateforme : `tiktok.com/@…`, `x.com/…`).
   - `en_file: false` → lire `raison` ; qualité insuffisante ou vidéo absente : réessayer avec une meilleure source, sinon le signaler.
7. `python3 scripts/inspi.py done <n> --url <url> --verdict garde|ecarte --score S --format F --recette "…" --pourquoi "…" [--note-alix N] [--note "avis Alix : …"] [--brut <url twitch>] [--queue <id file>]` pour CHAQUE lien (même écarté), sinon il revient le lendemain.
8. `python3 scripts/inspi.py calib` le lundi : écart moyen juge − Alix ; si ≥ 1 point ou plusieurs `trop_indulgent` / `trop_severe`, le dire à Alix et ajuster la grille.

## Rapport (court, en français)
« Inspirations : N analysées, G mises en production » ; par post : note du juge (et celle d'Alix), format, source (clip brut ou reprise), avertissement, pourquoi, recette en 1 ligne, lien ; non mis en file et pourquoi ; liens illisibles ; calibrage le lundi.
