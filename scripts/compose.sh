#!/usr/bin/env bash
# Le Lobby — pose le clip 16:9 sur le fond du reel. Usage : compose.sh overlay.png clip.mp4 sortie.mp4 [VIDEO_Y]
set -euo pipefail
OV="$1"; IN="$2"; OUT="$3"; VY="${4:-730}"
ffmpeg -y -loglevel error -loop 1 -framerate 30 -i "$OV" -i "$IN" -filter_complex \
  "[1:v]scale=1080:608:force_original_aspect_ratio=decrease,pad=1080:608:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v];[0:v][v]overlay=0:${VY}:shortest=1,format=yuv420p[o]" \
  -map "[o]" -map 1:a? -c:v libx264 -preset veryfast -crf 20 -profile:v high -c:a aac -b:a 160k -ar 48000 -movflags +faststart -shortest "$OUT"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT"
