from argparse import Namespace

import pytest

from common import check as chk
from common.files import is_ignored, load_mmfignore
from common.queue import (
    build_queue_fields, load_queue, read_root_header, verify_queue_root,
    write_queue_entry,
)
from common.text import (
    best_fuzzy_match, leading_int, render_filename, should_replace,
    titles_match,
)
from conftest import write_queue


def test_leading_int():
    assert leading_int("3/12") == 3
    assert leading_int(" 07") == 7
    assert leading_int("x") is None
    assert leading_int(None) is None


@pytest.mark.parametrize("filename, title", [
    ("diversity day", "Diversity Day!"),
    ("Up", "Up!"),
    ("M.A.S.H", "MASH"),
    ("Whats Up Doc", "What's Up, Doc?"),
    ("!!!", "!!!"),
])
def test_titles_match_ignores_punctuation(filename, title):
    assert titles_match(filename, title)


@pytest.mark.parametrize("filename, title", [
    ("Heat", "Heap"), ("Up", "Us"), ("Pilot", "The Alliance"),
    ("!!!", "???"),
])
def test_titles_match_rejects_real_differences(filename, title):
    assert not titles_match(filename, title)


@pytest.mark.parametrize("new, current", [
    ("What's Up, Doc?", "Whats Up Doc"),   # punctuation
    ("Second Song", "second song"),        # case
    ("The Lord of the Rings: The Fellowship of the Ring",
     "The Lord of the Rings: The Fellowship Of the Ring"),  # 1 letter
    ("Pilot", None),
])
def test_should_replace(new, current):
    assert should_replace(new, current)


@pytest.mark.parametrize("new, current", [
    ("Pilot", "Pilot"), ("Pilot", "  Pilot "),
])
def test_should_not_replace_same_title(new, current):
    assert not should_replace(new, current)


def test_best_fuzzy_match():
    candidates = {1: "Pilot", 2: "Diversity Day"}
    assert best_fuzzy_match(candidates, "diversity") == 2
    assert best_fuzzy_match(candidates, "zzzz") is None


def test_render_filename(tmp_path):
    path = tmp_path / "old.mkv"
    values = {"%title": "A/B: C", "%num": "01"}
    assert render_filename("%num - %title", path, values) == "01 - AB C.mkv"
    assert render_filename("%title.%ext", path, values) == "AB C.mkv"


def test_mmfignore_rules(tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "skip").mkdir()
    (tmp_path / "keep" / "a.mkv").touch()
    (tmp_path / "keep" / "b.tmp").touch()
    (tmp_path / "skip" / "c.mkv").touch()
    (tmp_path / ".mmfignore").write_text("skip/\n*.tmp\n")
    spec = load_mmfignore(tmp_path)
    kept = {
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")
        if not is_ignored(spec, tmp_path, p)
    }
    assert kept == {".mmfignore", "keep", "keep/a.mkv"}


def test_build_queue_fields_keeps_zero():
    current = {"season": 0, "title": "", "show": "S"}
    fields, previous = build_queue_fields(
        current, {"show": "T"}, ("show", "season", "title"),
    )
    assert fields == {"show": "T", "season": 0, "title": None}
    assert previous == {"show": "S"}


def test_queue_round_trip(tmp_path):
    queue = tmp_path / "q.yml"
    with open(queue, "w", encoding="utf-8") as f:
        f.write(f"# root: {tmp_path}\n")
        write_queue_entry(f, "a: b/c.mkv", {"title": "X", "n": 2},
                          {"title": "Old"})
    assert "# was: Old" in queue.read_text()
    assert load_queue(queue) == {"a: b/c.mkv": {"title": "X", "n": 2}}
    assert read_root_header(queue) == str(tmp_path)
    verify_queue_root(queue, tmp_path)
    with pytest.raises(SystemExit):
        verify_queue_root(queue, tmp_path / "other")


def test_queue_entry_printed_as_written(tmp_path, capsys):
    queue = tmp_path / "q.yml"
    with open(queue, "w", encoding="utf-8") as f:
        write_queue_entry(
            f, "A/b.mkv", {"title": "New", "year": 2001}, {"title": "Old"},
        )
    printed = capsys.readouterr().out
    assert printed == queue.read_text()
    assert "  title: New  # was: Old\n" in printed


def test_check_always_skip_marks_ok(tmp_path, answer):
    queue = write_queue(tmp_path / "q.yml", (
        "A/B/1.mkv:\n  n: 1\n"
        "A/B/2.mkv:\n  n: 1\n"
    ))

    def check_group(lines, stats, group_dir, group):
        chk.check_duplicates(
            lines, stats, group_dir, group, "n", "number", leading_int,
        )

    def check_entry(*_args):
        pass

    answer("3")
    stats = chk.run_check(queue, check_group, check_entry)
    assert (stats.warnings, stats.resolved) == (1, 1)
    assert queue.read_text().count("# OK") == 2
    # Marked warnings are reported without prompting.
    answer("bad")
    stats = chk.run_check(queue, check_group, check_entry)
    assert (stats.warnings, stats.resolved) == (1, 0)


def test_restart_check_opens_editor(tmp_path, answer, monkeypatch):
    queue = write_queue(tmp_path / "q.yml", "A/B/1.mkv:\n  n: null\n")
    calls = []

    def fake_editor(path, line):
        calls.append(line)
        queue.write_text("A/B/1.mkv:\n  n: 1\n")

    monkeypatch.setattr(chk, "open_editor", fake_editor)
    answer("1")
    stats = chk.run_check(
        queue,
        lambda *a: None,
        lambda lines, stats, file, fields, group:
            chk.check_null_and_blank_fields(lines, stats, file, fields),
    )
    assert calls == [2]
    assert stats.warnings == 0


def test_cli_parser_requires_step():
    from common.cli import build_parser

    def add_demo(subparsers):
        subparsers.add_parser("demo")

    parser = build_parser("x", "doc", [add_demo])
    assert parser.parse_args(["demo"]) == Namespace(step="demo")
    with pytest.raises(SystemExit):
        parser.parse_args([])
