"""Dry runs, apply's safety checks, scan errors and ffmpeg failures."""

import pytest

from common.ffmpeg import run_ffmpeg
from common.files import move
from common.queue import apply_queue, scan_one_file
from common.steps import process_each
from common.ui import past_tense
from conftest import needs_ffmpeg, write_queue


def make_library(root):
    for rel in ("A/B/1.mkv", "A/B/2.mkv", "Skip/x.mkv", "A/B/junk.tmp"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(rel)
    (root / ".mmfignore").write_text("Skip/\n*.tmp\n")
    return root


def test_past_tense():
    assert [past_tense(v) for v in ("convert", "normalize", "apply")] == \
        ["converted", "normalized", "applied"]


def test_process_each(tmp_path, capsys):
    paths = [tmp_path / "a", tmp_path / "b"]
    done = []

    def perform(path):
        if path.name == "b":
            raise RuntimeError("boom")
        done.append(path.name)

    counts = process_each(paths, lambda p: p.name, perform, "convert",
                          "file")
    assert done == ["a"]
    assert (counts["done"], counts["error"]) == (1, 1)
    out, err = capsys.readouterr()
    assert "Converted: a" in out
    assert "1 file(s) converted, 1 error(s)." in out
    assert "Failed to convert" in err


def test_process_each_dry_run(tmp_path, capsys):
    def perform(_path):
        raise AssertionError("dry run performed work")

    process_each([tmp_path / "a"], lambda p: p.name, perform, "convert",
                 "file", dry_run=True)
    out = capsys.readouterr().out
    assert "Would convert: a" in out
    assert "1 file(s) would be converted, 0 error(s)." in out


def test_move_dry_run(tmp_path, capsys):
    path = tmp_path / "old.mkv"
    path.touch()
    move(path, tmp_path / "new.mkv", dry_run=True)
    assert path.exists()
    assert "Would rename: old.mkv -> new.mkv" in capsys.readouterr().out
    move(path, tmp_path / "new.mkv")
    assert (tmp_path / "new.mkv").exists() and not path.exists()


def test_apply_queue_skips_ignored_missing_and_failures(tmp_path, capsys):
    root = make_library(tmp_path / "lib")
    queue = write_queue(tmp_path / "q.yml", (
        "A/B/1.mkv: {title: One}\n"
        "A/B/2.mkv: {title: Boom}\n"
        "Skip/x.mkv: {title: X}\n"
        "A/B/gone.mkv: {title: Gone}\n"
    ))
    written = []

    def write_fields(path, fields):
        if fields["title"] == "Boom":
            raise RuntimeError("disk on fire")
        written.append((path.relative_to(root).as_posix(), fields))

    counts = apply_queue(root, queue, write_fields)
    assert written == [("A/B/1.mkv", {"title": "One"})]
    assert (counts["applied"], counts["ignored"], counts["error"]) == \
        (1, 1, 2)
    err = capsys.readouterr().err
    assert "Ignored by .mmfignore, skipping" in err
    assert "File not found" in err
    assert "disk on fire" in err


def test_apply_queue_dry_run(tmp_path, capsys):
    root = make_library(tmp_path / "lib")
    queue = write_queue(tmp_path / "q.yml",
                        "A/B/1.mkv: {title: One, year: null}\n")

    def write_fields(_path, _fields):
        raise AssertionError("dry run wrote")

    counts = apply_queue(root, queue, write_fields, dry_run=True)
    assert counts["applied"] == 1
    out = capsys.readouterr().out
    assert f"Would apply: {root / 'A/B/1.mkv'}\n  title: One\n" in out
    assert "year" not in out
    assert "1 would be applied" in out


def test_scan_one_file_outcomes(tmp_path, capsys):
    def crash(_path):
        raise ValueError("bad tags")

    with open(tmp_path / "q.yml", "w", encoding="utf-8") as queue_f:
        assert scan_one_file(queue_f, crash, "x.mkv") == "error"
        assert scan_one_file(queue_f, lambda _p: None, "y.mkv") == "ok"
        assert scan_one_file(
            queue_f, lambda _p: ("z.mkv", {"title": "Z"}, {}), "z.mkv",
        ) == "queued"
    assert "Unexpected error on x.mkv: bad tags" in capsys.readouterr().err
    assert (tmp_path / "q.yml").read_text() == "z.mkv:\n  title: Z\n"


@needs_ffmpeg
def test_run_ffmpeg_failure_removes_partial_output(tmp_path):
    tmp_out = tmp_path / ".partial.mkv"
    tmp_out.write_text("half-written")
    cmd = ["ffmpeg", "-loglevel", "error", "-i",
           str(tmp_path / "missing.mkv"), str(tmp_out)]
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        run_ffmpeg(cmd, tmp_out)
    assert not tmp_out.exists()
