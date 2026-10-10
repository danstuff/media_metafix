"""MMF steps that modify files: apply, rename, convert, normalize."""

from argparse import Namespace

import pytest

from conftest import make_audio, needs_ffmpeg, write_queue

pytestmark = needs_ffmpeg

TAGS = {
    "album": "Album", "artist": "Artist A",
    "artists": ["Artist A", "Guest"], "title": "Song",
    "tracknumber": "3",
}


def read_tags(mmf, path):
    return mmf.get_tags(mmf.load_track(path))


@pytest.mark.parametrize("ext", [".mp3", ".flac", ".wav"])
def test_tag_round_trip(mmf, tmp_path, ext):
    path = make_audio(tmp_path / f"song{ext}")
    mmf.set_tags(mmf.load_track(path), TAGS)
    assert read_tags(mmf, path) == TAGS


def test_untagged_wav_reads_empty(mmf, tmp_path):
    path = make_audio(tmp_path / "song.wav")
    assert read_tags(mmf, path) == {
        "album": None, "artist": None, "artists": [], "title": None,
        "tracknumber": None,
    }


def library(tmp_path):
    root = tmp_path / "root"
    make_audio(root / "Artist A" / "Album" / "01 - one.mp3")
    make_audio(root / "Skip" / "Album" / "01 - x.mp3")
    (root / ".mmfignore").write_text("Skip/\n")
    return root


def test_apply_writes_tags_and_art(mmf, tmp_path):
    root = library(tmp_path)
    queue = tmp_path / "q.yml"
    queue.write_text(
        f"# root: {root.resolve()}\n"
        "Artist A/Album/01 - one.mp3:\n"
        "  album: Album\n  artist: Artist A\n"
        "  artists: [Artist A, Guest]\n  title: '  One  '\n"
        "  tracknumber: 1\n",
        encoding="utf-8",
    )
    art_dir = tmp_path / "art"
    for album in ("Artist A/Album", "Skip/Album", "Nobody/Album"):
        (art_dir / album).mkdir(parents=True)
        (art_dir / album / "art.jpg").write_bytes(b"jpeg")
    mmf.run_apply(Namespace(
        root=str(root), queue=str(queue), art_dir=str(art_dir),
        dry_run=False,
    ))
    tags = read_tags(mmf, root / "Artist A" / "Album" / "01 - one.mp3")
    assert tags == {
        "album": "Album", "artist": "Artist A",
        "artists": ["Artist A", "Guest"], "title": "One",
        "tracknumber": "1",
    }
    assert (root / "Artist A" / "Album" / "art.jpg").read_bytes() == \
        b"jpeg"
    assert not (root / "Skip" / "Album" / "art.jpg").exists()


def test_queue_fields_to_tag_updates_skips_nulls(mmf):
    assert mmf.queue_fields_to_tag_updates({
        "album": None, "artists": ["A", 2], "title": " T ",
        "tracknumber": 4,
    }) == {"artists": ["A", "2"], "title": "T", "tracknumber": "4"}


def test_rename(mmf, tmp_path, capsys):
    root = library(tmp_path)
    song = root / "Artist A" / "Album" / "01 - one.mp3"
    mmf.set_tags(mmf.load_track(song), TAGS)
    make_audio(root / "Artist A" / "Album" / "03 - Song.mp3")
    mmf.run_rename(root, "%num - %title")
    assert "Rename target already exists" in capsys.readouterr().err
    assert song.exists()
    mmf.run_rename(root, "%title (feat. %features)")
    assert (root / "Artist A" / "Album" / "Song (feat. Guest).mp3").exists()
    assert (root / "Skip" / "Album" / "01 - x.mp3").exists()


def test_convert_keeps_tags(mmf, tmp_path, capsys):
    root = tmp_path / "root"
    flac = make_audio(root / "Artist A" / "Album" / "song.flac")
    mmf.set_tags(mmf.load_track(flac), TAGS)
    mmf.run_convert(Namespace(
        root=str(root), from_ext="FLAC", to_ext="mp3", dry_run=False,
    ))
    assert "1 track(s) converted, 0 error(s)" in capsys.readouterr().out
    assert not flac.exists()
    assert read_tags(mmf, flac.with_suffix(".mp3")) == TAGS


def test_convert_same_format_is_noop(mmf, tmp_path, capsys):
    mmf.run_convert(Namespace(
        root=str(tmp_path), from_ext="mp3", to_ext=".MP3", dry_run=False,
    ))
    assert "nothing to do" in capsys.readouterr().err


def test_normalize_keeps_tags(mmf, tmp_path, capsys):
    root = tmp_path / "root"
    song = make_audio(root / "Artist A" / "Album" / "song.mp3")
    mmf.set_tags(mmf.load_track(song), TAGS)
    mmf.run_normalize(Namespace(root=str(root), lufs=-16.0, dry_run=False))
    assert "1 track(s) normalized, 0 error(s)" in capsys.readouterr().out
    assert read_tags(mmf, song) == TAGS


def test_check_track_totals(mmf, tmp_path, answer, capsys):
    queue = write_queue(tmp_path / "q.yml", (
        "A/B/1.mp3: {title: One, tracknumber: 1/10}\n"
        "A/B/2.mp3: {title: Two, tracknumber: 2/12}\n"
    ))
    answer("2")
    mmf.run_check_step(Namespace(queue=queue))
    assert "disagree on the total track count" in capsys.readouterr().out


def test_dry_runs_change_nothing(mmf, tmp_path, capsys):
    root = library(tmp_path)
    song = root / "Artist A" / "Album" / "01 - one.mp3"
    mmf.set_tags(mmf.load_track(song), TAGS)
    before = song.read_bytes()
    queue = tmp_path / "q.yml"
    queue.write_text(f"# root: {root.resolve()}\n"
                     "Artist A/Album/01 - one.mp3: {title: New}\n")
    art_dir = tmp_path / "art" / "Artist A" / "Album"
    art_dir.mkdir(parents=True)
    (art_dir / "art.jpg").write_bytes(b"jpeg")

    mmf.run_apply(Namespace(root=str(root), queue=str(queue),
                            art_dir=str(tmp_path / "art"), dry_run=True))
    mmf.run_normalize(Namespace(root=str(root), lufs=-16.0, dry_run=True))
    mmf.run_convert(Namespace(root=str(root), from_ext="mp3",
                              to_ext="flac", dry_run=True))
    mmf.run_rename(root, "%title", dry_run=True)

    out = capsys.readouterr().out
    assert f"Would apply: {song}\n  title: New\n" in out
    assert "Would copy:" in out
    assert "1 album art file(s) would be copied." in out
    assert f"Would normalize: {song}" in out
    assert "Would convert: 01 - one.mp3 -> 01 - one.flac" in out
    assert "Would rename: 01 - one.mp3 -> Song.mp3" in out
    assert song.read_bytes() == before
    assert not (root / "Artist A" / "Album" / "art.jpg").exists()
    assert sorted(p.name for p in song.parent.iterdir()) == [song.name]
