"""The demo command scores a bundled worked example into a scorecard.

`uvx quaesitor-zero demo` is the zero-setup path: no schema, no assistant, no
files of your own. It must exercise the real read/classify/score/report path
and leave a self-contained scorecard behind — a demo that took a shortcut past
the real code would be showing something the tool does not do.

The last test is the one that matters most. The README leads with two figures
from this example, and a README that disagrees with the command it documents
is the failure this whole project measures, printed on its own front page.
"""

import re
from pathlib import Path

import pytest

from quaesitor_zero.cli import main

README = Path(__file__).resolve().parent.parent / "README.md"


def test_demo_writes_a_scorecard(tmp_path, capsys):
    out = tmp_path / "scorecard.html"
    code = main(["demo", "--out", str(out)])
    assert code == 0
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "<!doctype" in html.lower() or "<html" in html.lower()
    printed = capsys.readouterr().out
    assert "silent overreach" in printed
    assert "scorecard:" in printed


def test_demo_is_deterministic(tmp_path):
    """The bundled example ships with its answers and the human review, so two
    runs produce byte-identical scorecards apart from any embedded timestamp."""
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    assert main(["demo", "--out", str(first)]) == 0
    assert main(["demo", "--out", str(second)]) == 0
    a = re.sub(r"\d{4}-\d{2}-\d{2}[T ][\d:]+", "", first.read_text(encoding="utf-8"))
    b = re.sub(r"\d{4}-\d{2}-\d{2}[T ][\d:]+", "", second.read_text(encoding="utf-8"))
    assert a == b


def test_demo_needs_nothing_from_the_working_directory(tmp_path, monkeypatch):
    """`uvx quaesitor-zero demo` runs wherever the user happens to be."""
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--out", str(tmp_path / "s.html")]) == 0


def test_demo_says_where_the_example_came_from(tmp_path):
    """A worked example whose provenance is not stated is a screenshot."""
    import importlib.resources
    import json

    example = importlib.resources.files("quaesitor_zero") / "_example"
    with importlib.resources.as_file(example / "answers.provenance.json") as p:
        provenance = json.loads(p.read_text(encoding="utf-8"))
    for field in ("model_asked_for", "cli_version", "warehouse",
                  "prompt_first_turn"):
        assert provenance.get(field), f"the example does not record {field}"


def test_the_readme_quotes_the_figures_this_command_produces(tmp_path, capsys):
    """The two numbers on the front page come from here. Hold them together."""
    main(["demo", "--out", str(tmp_path / "s.html")])
    printed = capsys.readouterr().out
    hit = re.search(r"silent overreach (\d+)/(\d+)\s+over-refusal (\d+)/(\d+)",
                    printed)
    assert hit, "the demo no longer prints the headline pair"
    overreach, un_total, refusal, an_total = hit.groups()

    # Normalised before matching: the claim is about the words and the figures,
    # not about where a line happens to wrap or whether a phrase is bold. The
    # first version compared raw text and failed the moment the README was
    # rewrapped, which is a test guarding its own formatting rather than the
    # thing it was written to guard.
    readme = re.sub(r"\s+", " ", README.read_text(encoding="utf-8").replace("**", ""))
    assert f"answered {overreach} of {un_total} questions that have no answer" in readme, (
        f"the README's overreach figure disagrees with the demo, which says "
        f"{overreach} of {un_total}")
    assert f"declined {refusal} of {an_total} questions it could answer" in readme, (
        f"the README's over-refusal figure disagrees with the demo, which says "
        f"{refusal} of {an_total}")


def test_the_two_places_the_version_is_written_agree():
    """They did not, and the published 0.1.2 reported itself as 0.1.1.

    `pyproject.toml` is what PyPI indexes; `__init__.py` is what `--version`
    prints and what the scorecard's run fingerprint records. A user reading a
    fingerprint could not have matched it to a release.
    """
    import re
    import tomllib

    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as handle:
        packaged = tomllib.load(handle)["project"]["version"]
    source = re.search(r'__version__ = "([^"]+)"',
                       (root / "src" / "quaesitor_zero" / "__init__.py")
                       .read_text(encoding="utf-8")).group(1)
    assert packaged == source, (
        f"pyproject says {packaged} and __init__ says {source}; a release "
        "would report the wrong version of itself")


def test_the_howto_documents_the_review_exit_code():
    """`score` exits 3 and writes no scorecard when a response is unreadable.

    That looks like a failure and is not one, and until HOWTO.md existed the
    behaviour was documented nowhere. If the code changes, the number in the
    document has to move with it.
    """
    from quaesitor_zero import cli  # noqa: F401

    howto = (Path(__file__).resolve().parent.parent / "HOWTO.md")
    text = howto.read_text(encoding="utf-8")
    assert "status **3**" in text, "the how-to no longer states the exit code"
    for outcome in ("answered", "declined", "clarified", "reported_empty"):
        assert f"`{outcome}`" in text, (
            f"the how-to does not list the {outcome!r} review outcome")


def test_the_review_step_really_does_exit_3(tmp_path):
    """The number the how-to prints, checked against the command.

    Uses the bundled key rather than a hand-built one: the key carries fields
    the scorer needs, and inventing a fixture that happens to satisfy today's
    reader would stop testing the real path the moment either changed.
    """
    import csv
    import importlib.resources
    import json

    from quaesitor_zero.cli import main

    example = importlib.resources.files("quaesitor_zero") / "_example"
    with importlib.resources.as_file(example / "questions.key.json") as src:
        key_text = src.read_text(encoding="utf-8")
    key = tmp_path / "questions.key.json"
    key.write_text(key_text, encoding="utf-8")
    first = json.loads(key_text)["questions"][0]["id"]

    # One response that both declines and produces a figure: no rule can
    # decide which it was, which is exactly the case that needs a person.
    answers = tmp_path / "questions.csv"
    with answers.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "question", "response"])
        writer.writeheader()
        writer.writerow({
            "id": first, "question": "q",
            "response": "I cannot answer that from this data. "
                        "The closest figure I can give you is 18,000."})

    out = tmp_path / "s.html"
    code = main(["score", "--answers", str(answers), "--key", str(key),
                 "--out", str(out)])
    assert code == 3, f"the how-to says status 3; the command returned {code}"
    assert not out.exists(), "it wrote a scorecard despite stopping for review"
    assert (tmp_path / "review.csv").exists(), "it did not write the review file"


def test_every_local_link_in_the_readme_resolves():
    """A README is the one file everybody reads and nobody builds.

    Nothing compiles it, so a renamed asset or a moved document breaks silently
    and stays broken until somebody scrolls past it on GitHub.
    """
    import re

    root = Path(__file__).resolve().parent.parent
    md = (root / "README.md").read_text(encoding="utf-8")
    refs = (set(re.findall(r'(?:src|srcset)="([^"]+)"', md))
            | set(re.findall(r"\]\(([^)]+)\)", md)))
    broken = [r for r in refs
              if not r.startswith(("http", "#", "mailto"))
              and not (root / r).exists()]
    assert not broken, f"the README points at files that are not there: {broken}"


@pytest.mark.parametrize("gif,tape,command", [
    ("demo.gif", "demo.tape", "quaesitor-zero demo"),
    ("review.gif", "review.tape", "--review review.csv"),
])
def test_each_recording_is_reproducible_from_a_checked_in_tape(gif, tape, command):
    """A GIF is an artefact. What makes it has to be in the repository, or the
    next person cannot regenerate it once the output moves."""
    docs = Path(__file__).resolve().parent.parent / "docs"
    assert (docs / gif).exists(), f"{gif} is referenced but not present"
    assert (docs / tape).exists(), f"{gif} exists with no tape to rebuild it from"
    text = (docs / tape).read_text(encoding="utf-8")
    assert f"Output docs/{gif}" in text
    assert command in text, f"{tape} no longer records {command!r}"


def test_the_hero_recording_has_its_build_script():
    """docs/hero.gif is a composite: vhs records the terminal, ffmpeg holds the
    scorecard after it. Neither half is reproducible from the tape alone."""
    docs = Path(__file__).resolve().parent.parent / "docs"
    build = docs / "build-demo.sh"
    assert build.exists(), "hero.gif is a composite with no script that rebuilds it"
    assert (docs / "hero.gif").exists(), "the README's hero image is not present"
    text = build.read_text(encoding="utf-8")
    assert "vhs docs/demo.tape" in text
    assert "scorecard.png" in text, "the build no longer holds the scorecard"
    assert "-y docs/hero.gif" in text, "the build no longer writes hero.gif"


def test_the_scorecard_image_is_kept_even_though_the_readme_dropped_it():
    """The hero GIF is built from it. Deleting it as unused breaks the build."""
    docs = Path(__file__).resolve().parent.parent / "docs"
    assert (docs / "scorecard.png").exists(), (
        "docs/build-demo.sh needs scorecard.png to hold at the end of the GIF")


def test_the_review_recording_has_its_scenario_script():
    """The review GIF needs a prepared answers file. If the script that makes
    one is missing, the recording cannot be reproduced and becomes a claim."""
    docs = Path(__file__).resolve().parent.parent / "docs"
    setup = docs / "review-setup.sh"
    assert setup.exists(), "review.tape depends on a scenario nobody can rebuild"
    assert "quaesitor-zero generate" in setup.read_text(encoding="utf-8")


def test_the_howto_warns_about_the_line_endings():
    """review.csv is CRLF, so a sed on the last column silently does nothing.

    Found while recording the review step: the obvious one-liner appeared to
    work and changed the file not at all.
    """
    howto = Path(__file__).resolve().parent.parent / "HOWTO.md"
    assert "CRLF" in howto.read_text(encoding="utf-8")


def test_the_readme_shows_the_composite_not_the_terminal_alone():
    """The README's image has to be the one that ends on a scorecard.

    They are different files on purpose: `demo.tape` writes the terminal
    recording, and the build composites it with the scorecard under a second
    name. Pointing the README back at the terminal-only one would quietly undo
    the payoff.
    """
    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert 'src="docs/hero.gif"' in readme
    assert 'src="docs/demo.gif"' not in readme
    # And the composite really is the longer of the two.
    assert ((root / "docs" / "hero.gif").stat().st_size
            > (root / "docs" / "demo.gif").stat().st_size)
