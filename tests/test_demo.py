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

    readme = README.read_text(encoding="utf-8")
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
