"""Render the scorecard: one self-contained HTML file.

Self-contained means what it says — no stylesheet, no font, no script, no image
fetched from anywhere. The page makes no request to any host, including the one
that served it, so it can be opened from a laptop with no network and attached
to an email without leaking that it was opened.

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
from quaesitor_zero.score import Scores, reading

logger = logging.getLogger(__name__)

BOUNDARY = (
    "This measures whether the system declines what it cannot answer. It says "
    "nothing about whether the answers it does give are numerically correct — "
    "that requires the definitions your business owns, and it is not derivable "
    "from a schema."
)

VERDICT_CLASS = {
    "silent overreach": "bad",
    "correct refusal": "good",
    "asked which was meant": "good",
    "correct answer": "good",
    "over-refusal": "warn",
    "not measured": "muted",
}

CSS = """
:root {
  --bg: #fbfaf8; --fg: #1a1a1a; --muted: #6b6b6b; --rule: #e2ded8;
  --card: #ffffff; --bad: #a11f2b; --bad-bg: #fbeced;
  --good: #1c6b46; --good-bg: #eaf4ee; --warn: #8a5a00; --warn-bg: #fbf2e0;
  --accent: #1a1a1a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16161a; --fg: #eceae6; --muted: #9a978f; --rule: #2e2e34;
    --card: #1d1d22; --bad: #f0808d; --bad-bg: #2c1a1d; --good: #6fce9d;
    --good-bg: #16271e; --warn: #e0b055; --warn-bg: #2a2216; --accent: #eceae6;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 3rem 1.25rem 6rem; background: var(--bg); color: var(--fg);
  font: 16px/1.6 ui-serif, Georgia, "Iowan Old Style", "Times New Roman", serif;
}
main { max-width: 52rem; margin: 0 auto; }
h1 { font-size: 1.9rem; line-height: 1.2; margin: 0 0 .3rem; letter-spacing: -.01em; }
h2 { font-size: 1.15rem; margin: 3rem 0 .75rem; letter-spacing: .02em;
     text-transform: uppercase; font-family: ui-sans-serif, system-ui, sans-serif; }
h3 { font-size: 1rem; margin: 2rem 0 .5rem; }
.sub { color: var(--muted); margin: 0 0 2.5rem; }
.lede { font-size: 1.15rem; border-left: 3px solid var(--accent); padding-left: 1.1rem;
        margin: 2rem 0; }
table { border-collapse: collapse; width: 100%; font-size: .9rem;
        font-family: ui-sans-serif, system-ui, sans-serif; }
.scroll { overflow-x: auto; }
th, td { text-align: left; padding: .55rem .7rem; border-bottom: 1px solid var(--rule);
         vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: .78rem;
     text-transform: uppercase; letter-spacing: .05em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.matrix td, .matrix th { text-align: center; }
.matrix td.label, .matrix th.label { text-align: left; }
.cell { font-size: 1.5rem; font-weight: 600; display: block; }
.cell-note { font-size: .75rem; color: var(--muted); }
.bad { color: var(--bad); } .bad-cell { background: var(--bad-bg); }
.good { color: var(--good); } .good-cell { background: var(--good-bg); }
.warn { color: var(--warn); } .warn-cell { background: var(--warn-bg); }
.muted { color: var(--muted); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
         gap: 1rem; margin: 1.5rem 0; }
.stat { background: var(--card); border: 1px solid var(--rule); border-radius: 4px;
        padding: 1rem; }
.stat .v { font-size: 1.7rem; font-weight: 600; font-variant-numeric: tabular-nums;
           font-family: ui-sans-serif, system-ui, sans-serif; }
.stat .k { font-size: .74rem; text-transform: uppercase; letter-spacing: .06em;
           color: var(--muted); font-family: ui-sans-serif, system-ui, sans-serif; }
.stat .ci { font-size: .78rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.q { border: 1px solid var(--rule); border-radius: 4px; background: var(--card);
     padding: 1rem 1.15rem; margin: .75rem 0; }
.q .meta { font-size: .74rem; color: var(--muted); text-transform: uppercase;
           letter-spacing: .05em; font-family: ui-sans-serif, system-ui, sans-serif;
           display: flex; gap: .8rem; flex-wrap: wrap; }
.q .text { font-size: 1.05rem; margin: .5rem 0; }
.q .resp { white-space: pre-wrap; font-size: .85rem; background: var(--bg);
           border-left: 2px solid var(--rule); padding: .6rem .8rem; margin: .6rem 0;
           font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.q .why { font-size: .82rem; color: var(--muted); }
.note { background: var(--card); border: 1px solid var(--rule); border-left: 3px solid var(--accent);
        padding: 1rem 1.15rem; margin: 1.5rem 0; font-size: .95rem; }
footer { margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--rule);
         font-size: .82rem; color: var(--muted); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85em; }
"""


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.0%}"


def _ci(bounds) -> str:
    lo, hi = bounds
    return f"95% CI {lo:.0%}–{hi:.0%}"


def _stat(key: str, value: str, note: str = "") -> str:
    return (f'<div class="stat"><div class="k">{_e(key)}</div>'
            f'<div class="v">{_e(value)}</div>'
            f'<div class="ci">{_e(note)}</div></div>')


def _matrix(scores: Scores) -> str:
    """The 2x2 itself, which is the point of the page."""
    return f"""
<div class="scroll"><table class="matrix">
<thead><tr>
  <th class="label"></th>
  <th>Assistant answered</th>
  <th>Assistant declined or asked</th>
  <th class="num">Not measured</th>
</tr></thead>
<tbody>
<tr>
  <td class="label"><strong>Unanswerable</strong><br>
      <span class="cell-note">correct action: decline</span></td>
  <td class="bad-cell"><span class="cell bad">{scores.overreach}</span>
      <span class="cell-note">silent overreach</span></td>
  <td class="good-cell"><span class="cell good">{scores.correct_refusal + scores.clarified_unanswerable}</span>
      <span class="cell-note">{scores.correct_refusal} refused,
      {scores.clarified_unanswerable} asked which was meant</span></td>
  <td class="num muted">{_unmeasured(scores, "unanswerable")}</td>
</tr>
<tr>
  <td class="label"><strong>Answerable</strong><br>
      <span class="cell-note">correct action: answer</span></td>
  <td class="good-cell"><span class="cell good">{scores.correct_answer}</span>
      <span class="cell-note">correct answer</span></td>
  <td class="warn-cell"><span class="cell warn">{scores.over_refusal}</span>
      <span class="cell-note">over-refusal</span></td>
  <td class="num muted">{_unmeasured(scores, "answerable")}</td>
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
            f"<td class='num {'warn' if stats['over_refusal'] else ''}'>"
            f"{stats['over_refusal']}</td>"
            f"<td class='num muted'>{stats['unmeasured']}</td></tr>"
        )
    return (
        "<div class='scroll'><table><thead><tr><th>Family</th>"
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
  <div class="meta">
    <span>{_e(row.question_id)}</span>
    <span>family {row.family} · {_e(row.family_name)}</span>
    <span>{_e(row.kind)}</span>
    <span class="{css}">{_e(row.verdict)}</span>
  </div>
  <div class="text">{_e(row.text)}</div>
  <div class="why"><strong>Why it is {_e(row.kind)}:</strong> {_e(row.warrant)}</div>
  <div class="resp">{_e(row.response) or '<em>no response</em>'}</div>
  <div class="why">Read as <strong>{_e(row.outcome)}</strong> — {_e(row.reason)}.
      Rules that fired: {_e(row.evidence)}.</div>
</div>""")
    return "".join(blocks)


def _fingerprint(fingerprint: Dict[str, str]) -> str:
    rows = "".join(
        f"<tr><td>{_e(k)}</td><td><code>{_e(v)}</code></td></tr>"
        for k, v in fingerprint.items()
    )
    return f"<div class='scroll'><table><tbody>{rows}</tbody></table></div>"


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
            "thing.</p><div class='scroll'><table><tbody>"
            + "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>"
                      for k, v in silent.items())
            + "</tbody></table></div>"
        )

    review_html = ""
    if scores.unclear or scores.missing:
        review_html = (
            f"<div class='note'><strong>{scores.unclear + scores.missing} "
            f"responses were not measured</strong> — {scores.missing} empty, "
            f"{scores.unclear} carrying evidence of more than one thing. They "
            f"are excluded from every rate above, because a response that was "
            f"never read says nothing about the assistant, and counting it as "
            f"safe would make a broken export look like a careful system.</div>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>quaesitor-zero — {_e(assistant or 'scorecard')}</title>
<style>{CSS}</style>
</head>
<body><main>

<h1>Does it say “I don't know”?</h1>
<p class="sub">{_e(assistant or 'An assistant')}, measured against
{counts.get('unanswerable', 0)} questions its data cannot answer and
{counts.get('answerable', 0)} matched questions it can.</p>

<div class="stats">
  {_stat("Silent overreach", f"{scores.overreach}/{scores.measured_unanswerable}",
         _ci(scores.overreach_interval))}
  {_stat("Balanced accuracy", _pct(scores.balanced_accuracy),
         "restraint and usefulness, averaged")}
  {_stat("Coverage", _pct(scores.coverage),
         f"{scores.answered} of {scores.measured} answered")}
  {_stat("Risk at coverage", _pct(scores.risk_at_coverage),
         "lower bound; correctness not checked")}
</div>

<p class="lede">{_e(reading(scores))}</p>

<h2>The 2×2</h2>
{_matrix(scores)}

<div class="stats">
  {_stat("Restraint", _pct(scores.restraint), _ci(scores.restraint_interval))}
  {_stat("Usefulness", _pct(scores.usefulness), _ci(scores.usefulness_interval))}
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
