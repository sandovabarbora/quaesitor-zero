#!/bin/sh
# Build docs/hero.gif: the whole loop, then the scorecard it produced.
#
#   python examples/tpcds/build.py     # once, makes the warehouse
#   ./docs/build-demo.sh
#
# Three stages, because vhs records a terminal and the payoff is a document.
#
#   1. vhs runs the four steps and ends on `open scorecard.html`
#   2. headless Chrome captures that scorecard full height, in one image
#   3. ffmpeg holds six windows of it, then joins the two halves
#
# The scroll is stepped rather than smooth, for two reasons. A smooth pan makes
# every frame different and took the same GIF from 292 kB to 3.9 MB. And nobody
# can read a document sliding past at sixteen frames a second, whereas a window
# held for a beat can be read. The stops are chosen against the document's own
# sections rather than by dividing its height, so no table is cut in half.
#
# Needs: vhs, ffmpeg, Google Chrome, python3, and quaesitor-zero on PATH.
set -eu
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"; kill %1 2>/dev/null || true' EXIT

CHROME=${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}
command -v vhs >/dev/null || { echo "vhs not on PATH: brew install vhs" >&2; exit 1; }
command -v quaesitor-zero >/dev/null || { echo "quaesitor-zero not on PATH" >&2; exit 1; }
[ -x "$CHROME" ] || { echo "Chrome not at $CHROME; set CHROME=" >&2; exit 1; }

echo "1/3 recording the terminal"
./docs/workflow-setup.sh "$work/run"
DEMO_DIR="$work/run" vhs docs/workflow.tape

echo "2/3 capturing the scorecard full height"
quaesitor-zero demo --out "$work/run/scorecard.html" >/dev/null
(cd "$work/run" && python3 -m http.server 8779 >/dev/null 2>&1) &
sleep 1
"$CHROME" --headless --disable-gpu --hide-scrollbars \
  --screenshot="docs/scorecard-full.png" --window-size=1100,2600 \
  http://127.0.0.1:8779/scorecard.html 2>/dev/null

echo "3/3 assembling"
ffmpeg -v error -i docs/workflow.gif \
  -vf "fps=16,scale=1100:560,setsar=1,format=yuv420p" -y "$work/term.mp4"
python3 - "$work" <<'PY'
import pathlib, subprocess, sys
work = sys.argv[1]
# Each window is [y, y+560]: header and headline numbers; the 2x2 and the two
# rates; the assumptions and the per-family table; the families that found
# nothing and the start of the per-question evidence.
STOPS = [0, 620, 1150, 1600, 2040]
lines = []
for i, y in enumerate(STOPS):
    out = f"{work}/{i:02d}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-i", "docs/scorecard-full.png",
                    "-vf", f"crop=1100:560:0:{y}", "-frames:v", "1",
                    "-update", "1", "-y", out], check=True)
    lines += [f"file '{out}'", "duration 1.3"]
lines.append(f"file '{work}/{len(STOPS) - 1:02d}.png'")
pathlib.Path(f"{work}/stops.txt").write_text("\n".join(lines) + "\n")
PY
ffmpeg -v error -f concat -safe 0 -i "$work/stops.txt" \
  -vf "fps=16,setsar=1,format=yuv420p" -y "$work/steps.mp4"
printf "file '%s/term.mp4'\nfile '%s/steps.mp4'\n" "$work" "$work" > "$work/join.txt"
ffmpeg -v error -f concat -safe 0 -i "$work/join.txt" -c copy -y "$work/joined.mp4"
ffmpeg -v error -i "$work/joined.mp4" \
  -vf "fps=14,scale=900:-1:flags=lanczos,palettegen=max_colors=64:stats_mode=diff" \
  -y "$work/palette.png"
ffmpeg -v error -i "$work/joined.mp4" -i "$work/palette.png" \
  -lavfi "fps=14,scale=900:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle" \
  -y docs/hero.gif

ls -lh docs/hero.gif
