#!/bin/sh
# Encode the rendered frames + soundtrack of the stylised version
set -e
cd "$(dirname "$0")"
python3 audio/make_audio.py audio/soundtrack.wav
ffmpeg -y -framerate 24 -i frames/%05d.jpg -i audio/soundtrack.wav -c:v libx264 -preset slow -crf 21 \
  -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 224k -shortest proyecto_lazaro.mp4
