#!/bin/sh
# Build docs/hero.gif: the terminal recording, then the scorecard it produced.
#
# docs/demo.tape writes docs/demo.gif, the terminal on its own. This composites
# that with the scorecard and writes docs/hero.gif, which is what the README
# shows. Two names because they are two artefacts, and because renaming the one
# a README points at is the only reliable way to get GitHub to stop serving a
# cached copy of the previous version.
#
#   ./docs/build-demo.sh
#
# Two steps, because vhs records a terminal and the payoff is a document. The
# recording ends on a filename; holding the scorecard after it is what shows a
# reader what they actually get. The hold is static rather than a slow pan:
# panning makes every frame different and took the same GIF from 162 kB to
# 2.8 MB, which is not worth it for eighty-five pixels of movement.
#
# Needs: vhs, ffmpeg, and quaesitor-zero on PATH.
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

command -v vhs >/dev/null || { echo "vhs not on PATH: brew install vhs" >&2; exit 1; }
command -v quaesitor-zero >/dev/null || { echo "quaesitor-zero not on PATH" >&2; exit 1; }

echo "1/3 recording the terminal"
DEMO_DIR="$work" vhs docs/demo.tape

echo "2/3 holding the scorecard"
ffmpeg -v error -i docs/demo.gif \
  -vf "fps=20,scale=1100:400,setsar=1,format=yuv420p" -y "$work/term.mp4"
ffmpeg -v error -loop 1 -i docs/scorecard.png -t 2.6 -r 20 \
  -vf "scale=1100:-2,crop=1100:400:0:40,setsar=1,format=yuv420p" -y "$work/card.mp4"
printf "file '%s/term.mp4'\nfile '%s/card.mp4'\n" "$work" "$work" > "$work/list.txt"
ffmpeg -v error -f concat -safe 0 -i "$work/list.txt" -c copy -y "$work/joined.mp4"

echo "3/3 encoding the gif"
ffmpeg -v error -i "$work/joined.mp4" \
  -vf "fps=20,scale=1000:-1:flags=lanczos,palettegen=max_colors=96:stats_mode=diff" \
  -y "$work/palette.png"
ffmpeg -v error -i "$work/joined.mp4" -i "$work/palette.png" \
  -lavfi "fps=20,scale=1000:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=none" \
  -y docs/hero.gif

ls -lh docs/hero.gif
