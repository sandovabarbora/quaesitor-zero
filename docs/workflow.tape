# The whole loop, end to end, against the public TPC-DS warehouse: the schema
# going in, the questions it produces, the replies coming back, the scorecard.
#
# One of the four steps is not a command. You ask your assistant and paste the
# replies into the CSV. That step is named on screen and done off camera,
# because watching a spreadsheet being filled in teaches nobody anything.
#
# Every command is real and the replies are real. `generate` against the
# example's warehouse reproduces the recorded question set exactly, so the
# answers in examples/tpcds/answers.csv are answers to these questions.
#
# Regenerate with:
#   python examples/tpcds/build.py          # once, makes the warehouse
#   ./docs/workflow-setup.sh /tmp/wf
#   DEMO_DIR=/tmp/wf vhs docs/workflow.tape

Output docs/workflow.gif

Set Shell zsh
Set FontSize 16
Set Width 1100
Set Height 560
Set Padding 28
Set BorderRadius 8
Set TypingSpeed 22ms
Set Theme { "background": "#1C1A17", "foreground": "#EFEBDF", "cursor": "#4657D9", "black": "#1C1A17", "red": "#9A3324", "green": "#2E6B4F", "yellow": "#D9A441", "blue": "#4657D9", "magenta": "#4657D9", "cyan": "#33424A", "white": "#EFEBDF", "brightBlack": "#6B655C", "brightRed": "#9A3324", "brightGreen": "#2E6B4F", "brightYellow": "#D9A441", "brightBlue": "#4657D9", "brightMagenta": "#4657D9", "brightCyan": "#DAD6CC", "brightWhite": "#F6F4EE" }

Hide
Type "cd $DEMO_DIR && setopt interactivecomments && clear" Enter
Show

Sleep 400ms
Type "# what goes in: your schema."
Enter
Sleep 500ms
Type "head -6 schema.sql"
Sleep 200ms
Enter
Sleep 2200ms

Type "clear"
Enter
Sleep 300ms
Type "quaesitor-zero generate --warehouse tpcds.duckdb --include-ambiguous"
Sleep 200ms
Enter
Sleep 3000ms

Type "# two of the twenty it wrote:"
Enter
Sleep 500ms
Type "head -3 questions.csv | cut -d, -f1,2"
Sleep 200ms
Enter
Sleep 2400ms

Type "# now ask your assistant those, and paste each reply into the response column."
Enter
Sleep 2000ms

Hide
Type "cp .replies.csv questions.csv && clear" Enter
Show

Sleep 400ms
Type "quaesitor-zero score --answers questions.csv --out scorecard.html --review review.csv"
Sleep 200ms
Enter
Sleep 2800ms

Type "open scorecard.html"
Sleep 300ms
Enter
Sleep 1100ms
