# The whole loop, end to end, against the public TPC-DS warehouse.
#
# Three steps and one of them is not a command: you ask your assistant and paste
# the replies back. That step is named on screen and done off camera, because
# watching a spreadsheet being filled in teaches nobody anything. The replies
# are real, from the run recorded in examples/tpcds/.
#
# Regenerate with:
#   ./docs/workflow-setup.sh /tmp/wf [path/to/tpcds.duckdb]
#   DEMO_DIR=/tmp/wf vhs docs/workflow.tape

Output docs/workflow.gif

Set Shell zsh
Set FontSize 16
Set Width 1100
Set Height 620
Set Padding 28
Set BorderRadius 8
Set TypingSpeed 35ms
Set Theme { "background": "#1C1A17", "foreground": "#EFEBDF", "cursor": "#4657D9", "black": "#1C1A17", "red": "#9A3324", "green": "#2E6B4F", "yellow": "#D9A441", "blue": "#4657D9", "magenta": "#4657D9", "cyan": "#33424A", "white": "#EFEBDF", "brightBlack": "#6B655C", "brightRed": "#9A3324", "brightGreen": "#2E6B4F", "brightYellow": "#D9A441", "brightBlue": "#4657D9", "brightMagenta": "#4657D9", "brightCyan": "#DAD6CC", "brightWhite": "#F6F4EE" }

Hide
Type "cd $DEMO_DIR && setopt interactivecomments && clear" Enter
Show

Sleep 600ms
Type "quaesitor-zero generate --warehouse tpcds.duckdb --include-ambiguous"
Sleep 200ms
Enter
Sleep 3800ms

Type "# two of the questions it wrote:"
Enter
Sleep 700ms
Type `python3 -c "import csv;[print(' ',r['id'],r['question']) for r in list(csv.DictReader(open('questions.csv')))[:2]]"`
Sleep 200ms
Enter
Sleep 3200ms

Type "# now ask your assistant those, and paste each reply into the response column."
Enter
Sleep 2400ms

Hide
Type "cp .replies.csv questions.csv && clear" Enter
Show

Sleep 400ms
Type "quaesitor-zero score --answers questions.csv --out scorecard.html --review review.csv"
Sleep 200ms
Enter
Sleep 3800ms
