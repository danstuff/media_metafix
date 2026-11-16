from argparse import Namespace

import pytest

from conftest import write_queue


def test_track_parsing(mmf):
    assert mmf.track_number_from_filename("03 - Song") == 3
    assert mmf.track_number_from_filename("Track 7") == 7
    assert mmf.track_number_from_filename("1999") is None
    assert mmf.strip_filename_track_prefix("03 - Song") == "Song"


def test_render_filename(mmf, tmp_path):
    song = tmp_path / "Earth, Wind & Fire" / "Album" / "x.mp3"
    tags = {"tracknumber": "3/12", "title": "Song",
            "artist": "Earth, Wind & Fire, B, C"}
    name = mmf.render_filename(
        "%num - %artist - %title (feat. %features)", song, tags,
    )
    assert name == "03 - Earth, Wind & Fire - Song (feat. B, C).mp3"
    tags["title"] = "Mr. Jones feat. St. Vincent..."
    assert mmf.render_filename("%title", song, tags) == \
        "Mr Jones feat St Vincent.mp3"


@pytest.mark.parametrize("artist, expected", [
    ("Earth, Wind & Fire", ("Earth, Wind & Fire", "")),
    ("Earth, Wind & Fire, B, C", ("Earth, Wind & Fire", "B, C")),
    ("Other, B, C", ("Other", "B, C")),  # tag doesn't match the folder
    ("Other", ("Other", "")),
    (None, ("", "")),
])
def test_split_artist(mmf, artist, expected):
    assert mmf.split_artist(artist, "Earth, Wind & Fire") == expected


def test_full_artist(mmf):
    assert mmf.full_artist("A", ["A"]) == "A"
    assert mmf.full_artist("A", ["A", "B", "C"]) == "A, B, C"
    # The folder name wins over MusicBrainz's spelling of the main
    # artist, and isn't repeated if credited again.
    assert mmf.full_artist("Beyonce", ["Beyoncé", "B", "beyonce"]) == \
        "Beyonce, B"


def test_strip_title_variations(mmf):
    assert mmf.strip_title_variations(
        "Song (feat. X) - Remastered 2011") == "Song"


def test_check_track_warnings(mmf, tmp_path, answer, capsys):
    queue = write_queue(tmp_path / "q.yml", (
        "A/B/01 - One.mp3:\n  album: B\n  artist: A, Guest\n"
        "  title: One\n  tracknumber: 1\n"
        "A/B/03 - Three.mp3:\n  album: C\n  artist: Z, A\n"
        "  title: One\n  tracknumber: 3\n"
    ))
    answer("2")
    mmf.run_check_step(Namespace(queue=queue))
    out = capsys.readouterr().out
    assert "track number(s) 2 missing" in out
    assert "same title 'One'" in out
    assert "disagree on album" in out
    assert "doesn't start with the artist folder's name 'A'" in out
    assert "disagree on artist" not in out


@pytest.mark.parametrize("step", [
    "scan", "check", "fingerprint", "apply", "normalize", "convert",
    "rename",
])
def test_cli_help(mmf, step, capsys):
    with pytest.raises(SystemExit) as exit_info:
        mmf.build_arg_parser().parse_args([step, "-h"])
    assert exit_info.value.code == 0
    assert step in capsys.readouterr().out


def test_cli_dispatch(mmf, monkeypatch):
    calls = []
    monkeypatch.setitem(mmf.STEP_HANDLERS, "rename", calls.append)
    monkeypatch.setattr("sys.argv", [
        "music_metafix", "rename", "/music", "%num", "--dry-run",
    ])
    mmf.main()
    assert calls[0].root == "/music"
    assert calls[0].template == "%num"
    assert calls[0].dry_run
