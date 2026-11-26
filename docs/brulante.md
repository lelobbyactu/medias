# Drama brûlant (lu seulement par la tâche « Publication immédiate »)

## 2ter. Drama Just Chatting envoyé en urgence (décisions d'Alix des 24 et 25 nov. 2026)
Tout le reste passe par la validation d'Alix. Un drama urgent part **20 minutes après son envoi sur Telegram, sauf s'il clique « Annuler »** (Instagram et TikTok ne permettent pas de supprimer un post par l'API). La veille ne marque `hot_reason: "drama"` que si **tout** est réuni :
- **clip vidéo** d'un drama, d'une embrouille ou d'une annonce en Just Chatting (ou en live) ;
- le créateur concerné est sur **la liste blanche** (doc projet `claude/liste-blanche-streamers.md`) ;
- **buzz prouvé** : repris par au moins 2 comptes FR indépendants de la veille (champ `mentions`) ;
- **moins de 12 h** depuis le moment ;
- aucune exclusion de `docs/clips.md` §4 ; accusation grave : seulement si vérifiée (`docs/clips.md` §4), et jamais si elle touche des mineurs, des violences sexuelles ou une procédure judiciaire en cours.

**Règles de publication**
- Tout de suite, à toute heure : montage puis `lobby.py proposer <nom> <fiche> --urgent`. Limites : **plafond de 7 posts/jour** et **2 clips urgents par nuit** (0 h-8 h à Taipei, soit 17 h-1 h à Paris ; compter les posts `urgent` du journal sur cette plage, hors `refuse`). Vérifier qu'aucun post en cours ne traite le même sujet.
- Juge rapide (2 combos), **seuil 8/10**. Titre factuel qui raconte sans prendre parti (« selon X », « X répond à Y »), jamais réécrit après le choix du juge.
- On raconte uniquement ce que les personnes concernées ont dit ou montré publiquement.
- Montage et envoi : `docs/montage.md` (9:16 ou 16:9). Claude ne publie pas.
- En cas de doute : ne rien envoyer en urgence ; le sujet reste dans la file pour la prochaine session de production.
