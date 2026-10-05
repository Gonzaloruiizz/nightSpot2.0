#!/bin/sh
# Render every photoreal shot at 12 fps (every other frame of the 24 fps animation)
B=${BPY_PYTHON:-python3}
cd "$(dirname "$0")"
for shot in frozen mutation needle establish dna blood; do
  case $shot in establish) n=108;; frozen) n=96;; needle) n=84;; blood) n=108;; dna) n=108;; mutation) n=144;; esac
  done_n=$(ls frames/$shot 2>/dev/null | wc -l)
  [ "$done_n" -ge $(( (n + 1) / 2 )) ] && continue
  $B scene.py $shot 1 $n 2 2>&1 | grep --line-buffered "\] frame\|rror"
done
echo "ALL DONE"
