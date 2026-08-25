"""Render the scorecard: one self-contained HTML file.

Self-contained means what it says: no stylesheet, no script, no image, and no
font fetched from anywhere. The reading face is a system serif stack and the
mono is embedded as base64, so the page makes no request to any host, including
the one that served it. It can be opened from a laptop with no network and
attached to an email without leaking that it was opened.

The look is the one used on quaesitor.eu: a printed report, not an interface.
One warm-paper substrate, the finding set in a reading serif, every figure the
machine produced set in mono, and red reserved for the one thing it means here,
a silent failure.

Every question, its response and its classification are printed. The totals are
the argument, and an argument whose evidence is not shown is a claim.

References:
    - html.escape: https://docs.python.org/3/library/html.html
"""

import html
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from quaesitor_zero import __version__
from quaesitor_zero._fonts import (
    JBM_400_B64, JBM_700_B64,
    SG_400_LATIN_B64, SG_400_LATIN_RANGE,
    SG_400_LATIN_EXT_B64, SG_400_LATIN_EXT_RANGE,
    SG_700_LATIN_B64, SG_700_LATIN_RANGE,
    SG_700_LATIN_EXT_B64, SG_700_LATIN_EXT_RANGE,
)
from quaesitor_zero.score import Scores, reading

logger = logging.getLogger(__name__)

BOUNDARY = (
    "This measures whether the system declines what it cannot answer. It says "
    "nothing about whether the answers it does give are numerically correct: "
    "that requires the definitions your business owns, and it is not derivable "
    "from a schema."
)

VERDICT_CLASS = {
    "silent overreach": "bad",
    "correct refusal": "good",
    "asked which was meant": "good",
    "correct answer": "good",
    "over-refusal": "flag",
    "not measured": "muted",
}

def _face(family: str, weight: str, b64: str, unicode_range: str = "") -> str:
    """One @font-face rule, embedded rather than linked.

    The scorecard's promise is that opening it fetches nothing from any host,
    so both faces travel in the file. That is also what the brand asks for in
    production, and it is what the site does with the same two typefaces.
    """
    rule = (f'@font-face{{font-family:"{family}";font-weight:{weight};'
            f'font-style:normal;font-display:swap;'
            f'src:url(data:font/woff2;base64,{b64}) format("woff2");')
    if unicode_range:
        rule += f'unicode-range:{unicode_range};'
    return rule + "}"


# JetBrains Mono for anything a machine produced, Space Grotesk for prose:
# the pairing the brand specifies, and the same one the site uses.
_FONT_FACE = (
    _face("JBM", "400", JBM_400_B64)
    + _face("JBM", "700", JBM_700_B64)
    + _face("Space Grotesk", "400", SG_400_LATIN_B64, SG_400_LATIN_RANGE)
    + _face("Space Grotesk", "400", SG_400_LATIN_EXT_B64, SG_400_LATIN_EXT_RANGE)
    + _face("Space Grotesk", "700", SG_700_LATIN_B64, SG_700_LATIN_RANGE)
    + _face("Space Grotesk", "700", SG_700_LATIN_EXT_B64, SG_700_LATIN_EXT_RANGE)
)

CSS = _FONT_FACE + """
:root{
  /* brand/BRAND.md, the 2026-08 identity. The scorecard was still on the
     previous one: a warmer green-grey and a Palatino-ish serif, which was
     nobody's decision by the end, just the version it was written against. */
  --paper:#EFEBDF; --paper-raised:#F6F4EE;
  --ink:#1C1A17; --ink-2:#6B655C; --ink-3:#6B655C;
  --rule:#DAD6CC; --hazard:#9A3324; --blue:#4657D9;
  /* The brand has no green. This is the one the site already uses for a
     correct outcome in its own result grid, so the two agree. */
  --verified:#2E6B4F;
  --mono:"JBM", ui-monospace, SFMono-Regular, Menlo, "DejaVu Sans Mono", monospace;
  --prose:"Space Grotesk", ui-sans-serif, system-ui, -apple-system,
          "Helvetica Neue", Arial, sans-serif;
}
*{box-sizing:border-box;}
html{-webkit-text-size-adjust:100%;}
body{
  margin:0; padding:clamp(2rem,6vw,4.5rem) 1.25rem 6rem;
  background:var(--paper); color:var(--ink);
  font:1rem/1.62 var(--prose);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
main{max-width:54rem; margin:0 auto;}
.mast{
  font-family:var(--mono); font-size:0.72rem; font-weight:700;
  letter-spacing:0.22em; text-transform:uppercase; color:var(--ink-3);
  margin:0 0 1.5rem;
}
h1{
  font-family:var(--prose); font-weight:700;
  font-size:clamp(2rem,4.6vw,2.6rem); line-height:1.08; letter-spacing:-0.01em;
  margin:0 0 0.5rem; color:var(--ink);
}
.sub{ color:var(--ink-2); margin:0 0 2rem; font-size:1.1rem; max-width:48ch; }
h2{
  font-family:var(--mono); font-size:0.72rem; font-weight:700;
  letter-spacing:0.2em; text-transform:uppercase; color:var(--ink-3);
  margin:3rem 0 1rem; padding-top:1rem; border-top:1px solid var(--rule);
}
h3{ font-family:var(--prose); font-weight:700; font-size:1.05rem; margin:2rem 0 .5rem; }
.figs{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));
  gap:1.5rem 2rem; margin:1.5rem 0; border-top:1px solid var(--rule);
  padding-top:1.5rem;
}
.fig .k{
  font-family:var(--mono); font-size:0.72rem; font-weight:700; letter-spacing:0.1em;
  text-transform:uppercase; color:var(--ink-3); margin:0 0 .4rem;
}
.fig .v{
  font-family:var(--mono); font-size:2.05rem; font-weight:700; line-height:1;
  font-variant-numeric:tabular-nums; color:var(--ink); margin:0;
}
.fig .v.hazard{ color:var(--hazard); }
.fig .n{
  font-family:var(--mono); font-size:0.72rem; letter-spacing:0.02em;
  color:var(--ink-3); margin:.5rem 0 0;
}
.lede{
  font-size:1.15rem; line-height:1.5; border-left:3px solid var(--ink);
  padding-left:1.1rem; margin:2rem 0; max-width:56ch; color:var(--ink);
}
.scroll{ overflow-x:auto; }
.matrix{ width:100%; border-collapse:collapse; margin:1rem 0; }
.matrix th{
  font-family:var(--mono); font-size:0.68rem; font-weight:700; letter-spacing:0.1em;
  text-transform:uppercase; color:var(--ink-3); text-align:center;
  padding:0 .8rem .6rem; border-bottom:1px solid var(--rule); vertical-align:bottom;
}
.matrix th.rowhead, .matrix td.rowhead{ text-align:left; }
.matrix td{
  text-align:center; padding:1.1rem .8rem; border-bottom:1px solid var(--rule);
  vertical-align:top;
}
.matrix td.rowhead strong{
  font-family:var(--prose); font-weight:700; font-size:1.02rem; display:block;
}
.matrix td.rowhead .rownote{
  font-family:var(--mono); font-size:0.66rem; letter-spacing:0.04em;
  text-transform:uppercase; color:var(--ink-3); margin-top:.35rem; display:block;
}
.qty{
  font-family:var(--mono); font-size:1.9rem; font-weight:700; line-height:1;
  font-variant-numeric:tabular-nums; display:block; color:var(--ink);
}
.qty.hazard{ color:var(--hazard); }
.qty.verified{ color:var(--verified); }
.qty.neutral{ color:var(--ink-2); }
.cellnote{
  font-family:var(--mono); font-size:0.66rem; letter-spacing:0.02em;
  color:var(--ink-3); margin-top:.45rem; display:block;
}
td.hazard-cell{ background:rgba(157,59,44,0.07); }
table.grid{ width:100%; border-collapse:collapse; font-family:var(--mono); font-size:0.8rem; }
table.grid th{
  text-align:left; font-size:0.68rem; font-weight:700; letter-spacing:0.08em;
  text-transform:uppercase; color:var(--ink-3); padding:.5rem .7rem;
  border-bottom:1px solid var(--rule);
}
table.grid td{ padding:.5rem .7rem; border-bottom:1px solid var(--rule); vertical-align:top; }
table.grid td.num, table.grid th.num{ text-align:right; font-variant-numeric:tabular-nums; }
.bad{ color:var(--hazard); }
.good{ color:var(--verified); }
.flag{ color:var(--ink-2); }
.muted{ color:var(--ink-3); }
.q{ border-top:1px solid var(--rule); padding:1.1rem 0; }
.q .meta{
  font-family:var(--mono); font-size:0.66rem; letter-spacing:0.06em;
  text-transform:uppercase; color:var(--ink-3); display:flex; gap:1rem;
  flex-wrap:wrap; margin:0;
}
.q .text{ font-family:var(--prose); font-size:1.08rem; margin:.55rem 0; color:var(--ink); }
.q .why{ font-size:0.9rem; color:var(--ink-2); margin:.3rem 0; }
.q .why strong{ color:var(--ink); }
.q .resp{
  white-space:pre-wrap; font-family:var(--mono); font-size:0.8rem; line-height:1.5;
  background:var(--paper-raised); border-left:2px solid var(--rule);
  padding:.7rem .9rem; margin:.6rem 0; color:var(--ink); overflow-x:auto;
}
.note{
  background:var(--paper-raised); border-left:3px solid var(--ink);
  padding:1rem 1.15rem; margin:1.5rem 0; font-size:0.95rem;
}
.note strong{ color:var(--ink); }
.note ul{ margin:.5rem 0 0; padding-left:1.1rem; }
p.muted{ font-size:0.92rem; max-width:62ch; }
footer{
  margin-top:4rem; padding-top:1.5rem; border-top:1px solid var(--rule);
  font-family:var(--mono); font-size:0.72rem; line-height:1.7; color:var(--ink-3);
}
footer strong{ color:var(--ink-2); }
code{ font-family:var(--mono); font-size:0.85em; }
"""


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _ci(bounds) -> str:
    lo, hi = bounds
    return f"95% CI {lo:.0%}–{hi:.0%}"


def _fig(key: str, value: str, note: str = "", tone: str = "") -> str:
    v_class = "v hazard" if tone == "hazard" else "v"
    return (f'<div class="fig"><p class="k">{_e(key)}</p>'
            f'<p class="{v_class}">{_e(value)}</p>'
            f'<p class="n">{_e(note)}</p></div>')


def _matrix(scores: Scores) -> str:
    """The 2x2 itself, which is the point of the page.

    Red marks the one cell that means a silent failure. The correct actions are
    verified green; over-refusal is friction, so it is ink, not an alarm colour.
    """
    held_shown = scores.correct_refusal + scores.clarified_unanswerable
    return f"""
<div class="scroll"><table class="matrix">
<thead><tr>
  <th class="rowhead"></th>
  <th>Assistant answered</th>
  <th>Assistant declined or asked</th>
  <th>Not measured</th>
</tr></thead>
<tbody>
<tr>
  <td class="rowhead"><strong>Unanswerable</strong>
      <span class="rownote">correct action: decline</span></td>
  <td class="hazard-cell"><span class="qty hazard">{scores.overreach}</span>
      <span class="cellnote">silent overreach</span></td>
  <td><span class="qty verified">{held_shown}</span>
      <span class="cellnote">{scores.correct_refusal} refused,
      {scores.clarified_unanswerable} asked which was meant</span></td>
  <td><span class="qty neutral">{_unmeasured(scores, "unanswerable")}</span>
      <span class="cellnote">excluded</span></td>
</tr>
<tr>
  <td class="rowhead"><strong>Answerable</strong>
      <span class="rownote">correct action: answer</span></td>
  <td><span class="qty verified">{scores.correct_answer}</span>
      <span class="cellnote">correct answer</span></td>
  <td><span class="qty neutral">{scores.over_refusal}</span>
      <span class="cellnote">over-refusal</span></td>
  <td><span class="qty neutral">{_unmeasured(scores, "answerable")}</span>
      <span class="cellnote">excluded</span></td>
</tr>
</tbody></table></div>
"""


def _unmeasured(scores: Scores, kind: str) -> int:
    return sum(1 for r in scores.rows
               if r.kind == kind and r.verdict == "not measured")


def _families(scores: Scores) -> str:
    rows = []
    for number in sorted(scores.per_family):
        stats = scores.per_family[number]
        name = scores.family_names.get(number, "")
        rows.append(
            f"<tr><td>{number} · {_e(name)}</td>"
            f"<td class='num'>{stats['unanswerable']}</td>"
            f"<td class='num {'bad' if stats['overreach'] else ''}'>"
            f"{stats['overreach']}</td>"
            f"<td class='num'>{stats['answerable']}</td>"
            f"<td class='num {'flag' if stats['over_refusal'] else ''}'>"
            f"{stats['over_refusal']}</td>"
            f"<td class='num muted'>{stats['unmeasured']}</td></tr>"
        )
    return (
        "<div class='scroll'><table class='grid'><thead><tr><th>Family</th>"
        "<th class='num'>Unanswerable</th><th class='num'>Overreach</th>"
        "<th class='num'>Controls</th><th class='num'>Over-refusal</th>"
        "<th class='num'>Not measured</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></div>"
    )


def _questions(scores: Scores) -> str:
    blocks = []
    for row in scores.rows:
        css = VERDICT_CLASS.get(row.verdict, "muted")
        blocks.append(f"""
<div class="q">
  <p class="meta">
    <span>{_e(row.question_id)}</span>
    <span>family {row.family} · {_e(row.family_name)}</span>
    <span>{_e(row.kind)}</span>
    <span class="{css}">{_e(row.verdict)}</span>
  </p>
  <p class="text">{_e(row.text)}</p>
  <p class="why"><strong>Why it is {_e(row.kind)}:</strong> {_e(row.warrant)}</p>
  <div class="resp">{_e(row.response) or '<em>no response</em>'}</div>
  <p class="why">Read as <strong>{_e(row.outcome)}</strong>: {_e(row.reason)}.
      Rules that fired: {_e(row.evidence)}.</p>
</div>""")
    return "".join(blocks)


def _fingerprint(fingerprint: Dict[str, str]) -> str:
    rows = "".join(
        f"<tr><td>{_e(k)}</td><td><code>{_e(v)}</code></td></tr>"
        for k, v in fingerprint.items()
    )
    return f"<div class='scroll'><table class='grid'><tbody>{rows}</tbody></table></div>"


def render(scores: Scores, key: dict, assistant: str,
           lexicon_note: str = "built-in English rules") -> str:
    """Build the scorecard.

    Args:
        scores: The scored run.
        key: The key file the questions came from.
        assistant: What the operator called the system, free text.
        lexicon_note: Which classification rules were used.

    Returns:
        A complete HTML document.
    """
    counts = key.get("counts", {})
    fingerprint = {
        "Assistant (as named by the operator)": assistant or "not stated",
        "Schema source": key.get("schema_source", ""),
        "Schema (SHA-256)": key.get("schema_digest", ""),
        "Question set (SHA-256)": key.get("question_digest", ""),
        "Generator version": key.get("generator_version", __version__),
        "Questions generated (UTC)": key.get("generated_at", ""),
        "Scored (UTC)": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "Questions": f"{counts.get('unanswerable', 0)} unanswerable, "
                     f"{counts.get('answerable', 0)} matched controls",
        "Classification": lexicon_note,
    }

    assumptions = key.get("assumptions") or []
    silent = key.get("families_with_nothing_to_say") or {}

    assumption_html = ""
    if assumptions:
        assumption_html = (
            "<div class='note'><strong>What this run assumed.</strong><ul>"
            + "".join(f"<li>{_e(a)}</li>" for a in assumptions)
            + "</ul></div>"
        )

    silent_html = ""
    if silent:
        silent_html = (
            "<h2>Families with nothing to say</h2>"
            "<p class='muted'>A family that found nothing and a family that "
            "never ran look the same in a total. They are not the same "
            "thing.</p><div class='scroll'><table class='grid'><tbody>"
            + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>"
                      for k, v in silent.items())
            + "</tbody></table></div>"
        )

    review_html = ""
    if scores.unclear or scores.missing:
        review_html = (
            f"<div class='note'><strong>{scores.unclear + scores.missing} "
            f"responses were not measured:</strong> {scores.missing} empty, "
            f"{scores.unclear} carrying evidence of more than one thing. They "
            f"are excluded from every rate above, because a response that was "
            f"never read says nothing about the assistant, and counting it as "
            f"safe would make a broken export look like a careful system.</div>"
        )

    overreach_tone = "hazard" if scores.overreach else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>quaesitor-zero · {_e(assistant or 'scorecard')}</title>
<style>{CSS}</style>
</head>
<body><main>

<p class="mast">quaesitor-zero · abstention scorecard</p>
<h1>Does it say “I don’t know”?</h1>
<p class="sub">{_e(assistant or 'An assistant')}, measured against
{counts.get('unanswerable', 0)} questions its data cannot answer and
{counts.get('answerable', 0)} matched questions it can.</p>

<div class="figs">
  {_fig("Silent overreach", f"{scores.overreach}/{scores.measured_unanswerable}",
        _ci(scores.overreach_interval), overreach_tone)}
  {_fig("Balanced accuracy", _pct(scores.balanced_accuracy),
        "restraint and usefulness, averaged")}
  {_fig("Coverage", _pct(scores.coverage),
        f"{scores.answered} of {scores.measured} answered")}
  {_fig("Risk at coverage", _pct(scores.risk_at_coverage),
        "lower bound; correctness not checked")}
</div>

<p class="lede">{_e(reading(scores))}</p>

<h2>The 2×2</h2>
{_matrix(scores)}

<div class="figs">
  {_fig("Restraint", _pct(scores.restraint), _ci(scores.restraint_interval))}
  {_fig("Usefulness", _pct(scores.usefulness), _ci(scores.usefulness_interval))}
</div>
<p class="muted">Restraint is the share of unanswerable questions the assistant
did not answer; usefulness is the share of answerable ones it did. A system that
declines everything scores 100% on the first and 0% on the second, which is why
neither is reported alone.</p>

{review_html}
{assumption_html}

<h2>By family</h2>
{_families(scores)}

{silent_html}

<h2>Every question</h2>
<p class="muted">Printed so the reader can disagree. A total whose evidence is
not shown is a claim, not a measurement.</p>
{_questions(scores)}

<h2>Run fingerprint</h2>
{_fingerprint(fingerprint)}

<footer>
<p><strong>What this does not measure.</strong> {_e(BOUNDARY)}</p>
<p>Generated by quaesitor-zero {_e(__version__)}. The tool sent nothing
anywhere: it has no network code, no telemetry, and no model access. Every
figure on this page comes from the responses in the answers file, classified by
published rules that are printed beside each one.</p>
</footer>

</main></body>
</html>
"""


def write(scores: Scores, key: dict, path: Path, assistant: str,
          lexicon_note: str = "built-in English rules") -> Path:
    """Render and write the scorecard.

    Args:
        scores: The scored run.
        key: The key file.
        path: Where the HTML goes.
        assistant: Free-text name of the system measured.
        lexicon_note: Which rules classified the responses.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(scores, key, assistant, lexicon_note), encoding="utf-8")
    logger.info("Wrote %s", path)
    return path
