# The step people get stuck on, recorded.
#
# `score` refuses to guess at a response that carries evidence of two things.
# It writes review.csv, exits 3, and produces no scorecard. That looks like a
# failure and is the tool doing exactly what it was built to do, so it is worth
# showing rather than only describing in HOWTO.md.
#
# Regenerate with:
#   ./docs/review-setup.sh /tmp/revgif
#   DEMO_DIR=/tmp/revgif vhs docs/review.tape
#
# Every command in it is real. The outcome is written during the recording,
# because a person deciding is the thing being shown.

Output docs/review.gif

Set Shell zsh
Set FontSize 17
Set Width 1100
Set Height 700
Set Padding 30
Set BorderRadius 8
Set TypingSpeed 45ms
Set Theme { "background": "#1C1A17", "foreground": "#EFEBDF", "cursor": "#4657D9", "black": "#1C1A17", "red": "#9A3324", "green": "#2E6B4F", "yellow": "#D9A441", "blue": "#4657D9", "magenta": "#4657D9", "cyan": "#33424A", "white": "#EFEBDF", "brightBlack": "#6B655C", "brightRed": "#9A3324", "brightGreen": "#2E6B4F", "brightYellow": "#D9A441", "brightBlue": "#4657D9", "brightMagenta": "#4657D9", "brightCyan": "#DAD6CC", "brightWhite": "#F6F4EE" }

Hide
Type "cd $DEMO_DIR && setopt interactivecomments && clear" Enter
Show

Sleep 700ms
Type "quaesitor-zero score --answers questions.csv --out scorecard.html"
Sleep 300ms
Enter
Sleep 3500ms

Type "# the response no rule could read:"
Enter
Sleep 900ms
Type `python3 -c "import csv;print(list(csv.DictReader(open('review.csv')))[0]['response'])"`
Sleep 200ms
Enter
Sleep 3s

Type "# it declined AND gave a figure. only a person can call that one."
Enter
Sleep 1500ms
Type "# open review.csv, put reported_empty in the outcome column, save."
Enter
Sleep 2200ms

# Done off camera on purpose. What a person actually does here is open the file
# in a spreadsheet; watching one typed into an editor teaches nobody anything,
# and a CSV one-liner on screen teaches them less. The edit is exactly what the
# line above says, and it is in this file so anyone can check that.
Hide
Type `python3 -c "import csv;p='review.csv';r=list(csv.DictReader(open(p)));r[0]['outcome']='reported_empty';w=csv.DictWriter(open(p,'w',newline=''),fieldnames=list(r[0]));w.writeheader();w.writerows(r)"`
Enter
Type "clear"
Enter
Show

Sleep 500ms
Type "quaesitor-zero score --answers questions.csv --out scorecard.html --review review.csv"
Sleep 300ms
Enter
Sleep 3500ms
