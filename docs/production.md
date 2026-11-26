# Session de production (2 par jour : 11 h et 20 h, heure de Taipei)

But : monter **4 vidéos au maximum**, et seulement ce qui manque pour avoir **5 vidéos en stock** (à valider, validées ou en retouche ; `config.json` → `stock_cible`, décision d'Alix du 26 nov.) et les envoyer à Alix sur Telegram. **Claude ne publie rien** : après validation, GitHub Actions publie à chaque créneau (8 h, 12 h, 18 h, 21 h Paris) la vidéo validée la mieux notée encore fraîche.

0. **Retouches demandées par Alix** (clé `retouches` de `lot`) : à faire en premier. Reprendre la source (`clip.url`) avec `lobby.fetch_media`, remonter dans `posts/<nom>/` selon sa demande (texte d'Alix : une consigne de montage seulement), `push`, puis `python3 scripts/lobby.py renvoyer <nom>`. Demande impossible : le dire dans le rapport et `fail <nom> "<raison>"`.
1. `python3 scripts/lobby.py lot` : réseau, ménage, nombre à produire (`a_produire` = 5 − stock, 4 max ; 0 si le stock est plein), candidats encore frais au prochain créneau (2 de réserve). Clé `stop` ou aucun candidat → « RAS production : <raison> ».
2. Pour chaque candidat retenu, dans l'ordre : `python3 scripts/lobby.py take <id>` puis copier `/tmp/clip.mp4` vers `/tmp/lot/<id>.mp4`, noter `twitch.found` / `twitch.channel`, faire UNE planche de 6 images (`/tmp/lot/<id>.jpg`). Clip introuvable → `drop`, prendre la réserve.
3. Préparer **3 combos** titre / description par clip (`docs/clips.md` §5).
4. **Un seul juge pour tout le lot** (`docs/juge.md`) : il note chaque clip, retient un combo par clip (seuil 7/10) et dit lesquels des 2 autres titres restent acceptables. Clip refusé → `drop <id> "<raison>"`, prendre une réserve (une seule vague de remplacement).
5. Pour chaque clip retenu (meilleure note d'abord) : `reserve <id> reel Clips` → montage `docs/montage.md` §7 (`--video /tmp/lot/<id>.mp4`) → relecture des sous-titres.
6. **Garde-fou** (`docs/juge.md` §6bis) : un seul sous-agent relit toutes les planches 9:16 et répond une ligne par post.
7. Pour chaque post : `python3 scripts/lobby.py push "post <nom>" posts/<nom> config.json`, puis écrire `/tmp/lot/<nom>.json` :
   `{"titre": "<titre retenu, tel quel>", "titres_alt": ["<autre titre acceptable>", "<autre>"], "legende": "<description complète : texte + crédit + hashtags>", "judge": "8/10", "garde_fou": "OK|SPONSOR"}`
   (16:9 : pas de `garde_fou`) et lancer `python3 scripts/lobby.py proposer <nom> /tmp/lot/<nom>.json`. Le sujet sort de la file et la vidéo part sur Telegram.
   Montage impossible : `python3 scripts/lobby.py fail <nom> "<raison>"`.
8. Recherche de secours Apify (`docs/clips.md` §4) seulement si la file ne donne **aucun** candidat.
