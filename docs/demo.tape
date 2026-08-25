# Terminal recording for the README, in the brand palette.
#
# Regenerate with:  vhs docs/demo.tape
#
# It runs the real command against the real package, so the figures in the
# recording are the figures the tool prints. Nothing here is typed for effect.

Output docs/demo.gif

Set Shell zsh
Set FontSize 18
Set Width 1100
Set Height 400
Set Padding 32
Set BorderRadius 8
Set TypingSpeed 55ms
Set Theme { "background": "#1C1A17", "foreground": "#EFEBDF", "cursor": "#4657D9", "black": "#1C1A17", "red": "#9A3324", "green": "#2E6B4F", "yellow": "#D9A441", "blue": "#4657D9", "magenta": "#4657D9", "cyan": "#33424A", "white": "#EFEBDF", "brightBlack": "#6B655C", "brightRed": "#9A3324", "brightGreen": "#2E6B4F", "brightYellow": "#D9A441", "brightBlue": "#4657D9", "brightMagenta": "#4657D9", "brightCyan": "#DAD6CC", "brightWhite": "#F6F4EE" }

Hide
Type "cd $DEMO_DIR && clear" Enter
Show

Sleep 800ms
Type "quaesitor-zero demo"
Sleep 400ms
Enter
Sleep 4s

Type "open scorecard.html"
Sleep 400ms
Enter
Sleep 1600ms
