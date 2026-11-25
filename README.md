# medias
Visuels publiés par Le Lobby (@lelobbyactu) : uniquement des clips vidéo (jeu vidéo, Just Chatting, événements).

- `PIPELINE.md` : consignes des tâches automatiques (noyau) ; détails dans `docs/`
- `scripts/make_reel_916.py` : montage 9:16 (titre, webcam, sous-titres au milieu, gameplay), format principal
- `scripts/make_reel.py` : montage 16:9 de secours (clip tel qu'en live, titre en haut, sous-titres en bas)
- `scripts/subtitles.py` : sous-titres automatiques (DA)
- `scripts/lobby.py` : file d'attente, journal, ménage, git ; `scripts/sources.py` : collecte Twitch + Reddit
- `state/published.json` : journal des posts ; `state/queue.json` + `queue/` : file d'attente
