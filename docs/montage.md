# Montage et envoi en validation

## 7. Montage d'un clip
Deux formats, choisis par la qualité de la source (ligne éditoriale d'Alix) :
- **9:16 (format principal)**, `make_reel_916.py`, même vidéo sur Instagram et TikTok : **titre en haut**, webcam du streamer, **sous-titres au milieu** (bande noire), **gameplay en bas** (recadré en 4:3). Seulement si la webcam ET le gameplay recadré sont de qualité acceptable.
- **16:9 (secours)**, `make_reel.py` : le clip tel qu'on le voit en live, **titre en haut**, **sous-titres en bas** (sous la vidéo). **Instagram seul.**
Dans les deux cas : pas de crédit ni de nombre de vues à l'écran (crédit dans la légende), sous-titres DA (Unbounded ExtraBold 58 px, capitales, blanc à contour noir, mot prononcé en jaune, une ligne sans mot coupé, gros mots masqués sauf la 1re lettre).

1. Le clip est dans `/tmp/clip.mp4` (fait par `python3 scripts/lobby.py take <id>`). `take` cherche le même moment en clip Twitch et, s'il le trouve, remplace `/tmp/clip.mp4` par la version d'origine 1080p60 ou plus (original X dans `/tmp/clip_x.mp4`). Champ `twitch` : si `found`, crédit `twitch.tv/<chaîne>` et `twitch.channel` sert au montage ; sinon crédit X. `found: false` n'est jamais bloquant.
2. Numéro et nom du post : `python3 scripts/lobby.py reserve <id> reel Clips` → `NNNN-JJ_MM_AAAA-Clips`.
3. **Montage 9:16** : `python3 scripts/make_reel_916.py --video /tmp/clip.mp4 --post <nom> --title "Ligne 1|Ligne 2 *mot*" [--start S --end E] [--channel <twitch.channel>] 2>&1 | grep -v WARN` (~1 min ; couper les temps morts). Il trouve seul la webcam (pleine largeur, ou plus petite et centrée ; mise en page sans webcam s'il n'y en a pas) et place le cadre du jeu à côté. Transcription ~10 s (+ installation de faster-whisper et ~1,6 Go de modèle au premier montage d'une exécution).
   **Relecture des sous-titres** (avant le garde-fou) : lire `sous_titres` et `mots_incertains`. Mot faux ou absurde → le retirer de `posts/<nom>/<nom>_soustitres.json` (ou corriger seulement le champ `mot` si le bon mot est certain ; retirer aussi les petits mots orphelins), puis relancer la même commande avec `--subs-json posts/<nom>/<nom>_soustitres.json`. Dans le doute, on retire. « A » → « À » quand c'est évident. Texte majoritairement faux ou personne ne parle (musique, jeu) → `--no-subs`.
4. **Garde-fou** (`docs/juge.md` §6bis) sur `posts/<nom>/<nom>_planche.jpg` (une seule image) :
   - **OK** → Instagram + TikTok (même vidéo).
   - **SPONSOR** (logo de marque d'overlay, QR ; aussi si le script renvoie `"qr": true`) → même vidéo, **Instagram seul**.
   - **NON** → une seule correction si le défaut est le cadrage (`--cam x,y,w,h`, `--no-cam` ou `--game-x X`, espace 1920x1080) puis nouveau garde-fou ; sinon **16:9** (étape 5).
5. **16:9** (si `make_reel_916.py` renvoie `"ok": false` — cinématique, zoom excessif, pas de place pour le 4:3 — ou garde-fou NON après correction) : `python3 scripts/make_reel.py --video /tmp/clip.mp4 --post <nom> --title "<même titre>" [--start S --end E]` (sous-titres automatiques en bas, même relecture qu'à l'étape 3 avec `--subs-json` ou `--no-subs`), relire `<nom>_cover.jpg`, puis **Instagram seul**. Rapport : « 16:9 : <raison> ».
6. Après un OK ou un SPONSOR, si la chaîne n'est pas encore dans `config.json` → `tiktok_layouts` : `python3 scripts/make_reel_916.py --video /tmp/clip.mp4 --post <nom> --channel <chaîne> --check-only --save-layout --out-dir /tmp/chk 2>&1 | grep -v WARN` (mémorise la webcam ; `config.json` part avec le push du post).
7. Vérifier la durée, le son (`has_audio`), la taille (< 100 Mo). `_planche.jpg` et `_fond.png` restent dans le dossier du post (archive), jamais publiés.

## 8. Envoi en validation (Claude ne publie jamais)
1. **Réserver** : fait par `lobby.py reserve`.
2. Pousser : `python3 scripts/lobby.py push "post <nom>" posts/<nom> config.json`.
3. `python3 scripts/lobby.py proposer <nom> <fiche.json>` (format de la fiche : `docs/production.md` §7 ; `--urgent` pour un drama brûlant). GitHub Actions envoie la vidéo sur Telegram et publie après validation.
4. Montage impossible : `python3 scripts/lobby.py fail <nom> "<raison>"`.
5. Sorties de commandes : toujours silencieuses (`-q`, `| tail -3`), ne jamais afficher un JSON entier.
