import argparse
from argparse import Namespace
from pathlib import Path

import pytest

from conftest import make_video, needs_ffmpeg, write_queue


@pytest.mark.parametrize("name, season", [
    ("Season 2", 2), ("S03", 3), ("season_04", 4), ("7", 7),
    ("Specials", 0), ("Extras", None),
])
def test_season_from_dir(tmf, name, season):
    assert tmf.season_from_dir(name) == season


@pytest.mark.parametrize("stem, episode, title", [
    ("The Office - S01E03 - Health Care", 3, "Health Care"),
    ("show.1x12.Title", 12, "Title"),
    ("04 - The Alliance", 4, "The Alliance"),
    ("Episode 5", 5, ""),
    ("Pilot", None, "Pilot"),
])
def test_episode_parsing(tmf, stem, episode, title):
    assert tmf.episode_from_name(stem) == episode
    assert tmf.strip_episode_number(stem) == title


def test_movie_parsing(tmf):
    assert tmf.year_from_name("Heat (1995)") == 1995
    assert tmf.strip_year("Heat (1995)") == "Heat"
    assert tmf.year_from_name("Blade Runner 2049") is None


def test_guess_fields(tmf):
    assert tmf.guess_fields("Show/Season 1/S01E02 - Two.mkv") == {
        "show": "Show", "season": 1, "episode": 2, "title": "Two",
    }
    assert tmf.guess_fields("Harry Potter/Goblet (2005).mp4") == {
        "series": "Harry Potter", "title": "Goblet", "year": 2005,
    }


def test_iter_videos_mixed_root(tmf, tmp_path):
    for rel in ("Show/Season 1/e1.mkv", "Show/Season 1/notes.txt",
                "Movies/Heat (1995).mp4", "Skip/Season 1/e1.mkv",
                "Show/Season 1/deep/too-deep.mkv", "loose.mkv"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).touch()
    (tmp_path / ".mmfignore").write_text("Skip/\n")
    found = [
        p.relative_to(tmp_path).as_posix() for p in tmf.iter_videos(tmp_path)
    ]
    assert found == ["Movies/Heat (1995).mp4", "Show/Season 1/e1.mkv"]
    assert [tmf.kind_of(f) for f in found] == ["movie", "episode"]


def test_match_episode(tmf):
    titles = {(1, 1): "Pilot", (1, 2): "Diversity Day", (2, 1): "Pilot"}
    by_number = {"season": 1, "episode": 2, "title": "x"}
    by_title = {"season": 2, "episode": None, "title": "pilot"}
    assert tmf.match_episode(by_number, titles) == (1, 2, "Diversity Day")
    assert tmf.match_episode(by_title, titles) == (2, 1, "Pilot")


def test_oshash(tmf, tmp_path):
    path = tmp_path / "zeros.bin"
    path.write_bytes(bytes(131072))
    assert tmf.oshash(path) == "0000000000020000"
    path.write_bytes(b"\x01" + bytes(131071))
    assert tmf.oshash(path) == "0000000000020001"


def test_pick_subtitle_prefers_hash_match(tmf):
    def result(file_id, downloads, match=False):
        attributes = {
            "download_count": downloads, "moviehash_match": match,
            "files": [{"file_id": file_id}],
        }
        return {"attributes": attributes}
    results = [result(1, 900), result(2, 5, match=True), result(3, 50)]
    assert tmf.pick_subtitle(results) == 2
    assert tmf.pick_subtitle(results[::2]) == 1
    assert tmf.pick_subtitle([]) is None


def test_feature_agrees(tmf):
    feature = {"title": "Pilot", "season_number": 1, "episode_number": 1}
    episode = {"season": 1, "episode": 1, "title": "Pilot"}
    assert tmf.feature_agrees(feature, episode)
    assert not tmf.feature_agrees(feature, dict(episode, episode=2))
    assert tmf.feature_agrees({"title": "Heat"}, {"title": "Heat"})
    assert not tmf.feature_agrees({"title": "Heat"}, {"title": "Alien"})


def run_check(tmf, queue):
    return tmf.run_check(Namespace(queue=queue))


def test_check_episode_warnings(tmf, tmp_path, answer, capsys):
    queue = write_queue(tmp_path / "q.yml", (
        "Show/Season 1/S01E01 - Pilot.mkv:\n"
        "  show: Show\n  season: 1\n  episode: 1\n  title: Pilot\n"
        "Show/Season 1/S02E03 - Pilot.mkv:\n"
        "  show: Shoe\n  season: 1\n  episode: 1\n  title: Pilot\n"
    ))
    answer("2")
    run_check(tmf, queue)
    out = capsys.readouterr().out
    assert "same title 'Pilot'" in out
    assert "same episode number 1" in out
    assert "disagree on show" in out
    assert "filename says season 2, but season is 1" in out


def test_check_movie_warnings(tmf, tmp_path, answer, capsys):
    queue = write_queue(tmp_path / "q.yml", (
        "Heat/Heat (1995).mkv:\n  series: Heat\n  title: Heat\n"
        "  year: 1995\n"
        "Heat/Other.mkv:\n  series: Heat\n  title: ''\n  year: 3000\n"
    ))
    answer("2")
    run_check(tmf, queue)
    out = capsys.readouterr().out
    assert "Heat (1995)" not in out
    assert "title is blank" in out
    assert "year 3000 looks wrong" in out


@needs_ffmpeg
@pytest.mark.parametrize("ext", [".mkv", ".mp4", ".avi"])
def test_tag_round_trip(tmf, tmp_path, ext):
    path = make_video(tmp_path / f"v{ext}")
    fields = {"series": "Harry Potter", "title": "Goblet", "year": 2005}
    tmf.write_tags(path, fields)
    tags = tmf.read_tags(path)
    assert {k: tags[k] for k in fields} == fields


@needs_ffmpeg
def test_scan_and_apply(tmf, tmp_path, monkeypatch):
    root = tmp_path / "root"
    make_video(root / "Show" / "Season 1" / "02 - Wrong.mkv")
    make_video(root / "Heat" / "Heat (1995).mp4", "-metadata", "title=Heat")
    monkeypatch.setattr(tmf, "tvmaze_episodes", lambda show: (
        show, {(1, 2): "Diversity Day"},
    ))
    queue = tmp_path / "changes.yml"
    args = Namespace(
        root=str(root), queue=str(queue), tmdb_api_key=None,
        no_tvmaze=False, no_subs=True, dry_run=False,
        subs_dir=str(tmp_path / "subtitles"),
    )
    tmf.run_scan(args)
    entries = tmf.load_queue(queue)
    movie = {"series": "Heat", "title": "Heat", "year": 1995}
    episode_fields = {
        "show": "Show", "season": 1, "episode": 2, "title": "Diversity Day",
    }
    assert entries == {
        "Heat/Heat (1995).mp4": movie,
        "Show/Season 1/02 - Wrong.mkv": episode_fields,
    }
    tmf.run_apply(args)
    episode = root / "Show" / "Season 1" / "02 - Wrong.mkv"
    assert tmf.read_tags(episode)["title"] == "Diversity Day"
    tmf.run_scan(args)
    assert tmf.load_queue(queue) == {}


@needs_ffmpeg
def test_embed_subtitle_and_rename(tmf, tmp_path):
    path = make_video(tmp_path / "Show" / "Season 1" / "e.mkv",
                      "-metadata", "title=Pilot",
                      "-metadata", "episode_sort=1",
                      "-metadata", "season_number=1")
    srt = b"1\n00:00:00,000 --> 00:00:00,500\nHi\n"
    assert tmf.save_subtitle(path, srt, "en") == path
    assert tmf.has_subtitles(path, "en")
    assert not tmf.has_subtitles(path, "fr")
    avi = make_video(tmp_path / "Movie" / "m.avi", "-metadata", "title=M")
    assert tmf.save_subtitle(avi, srt, "en") == Path(
        tmp_path / "Movie" / "m.en.srt")
    tmf.rename_file(path, "S%seasonE%episode %title")
    tmf.rename_file(avi, "%title (x)")
    assert (tmp_path / "Show" / "Season 1" / "S01E01 Pilot.mkv").exists()
    assert (tmp_path / "Movie" / "M (x).en.srt").exists()


@needs_ffmpeg
def test_convert_keeps_streams_and_tags(tmf, tmp_path, capsys):
    root = tmp_path / "root"
    path = make_video(root / "Heat" / "Heat.mkv")
    tmf.write_tags(path, {"series": "Heat", "title": "Heat", "year": 1995})
    tmf.save_subtitle(path, b"1\n00:00:00,000 --> 00:00:00,500\nHi\n", "en")
    tmf.run_convert(Namespace(
        root=str(root), from_ext="mkv", to_ext="mp4", dry_run=False,
    ))
    assert "1 file(s) converted, 0 error(s)" in capsys.readouterr().out
    mp4 = path.with_suffix(".mp4")
    assert not path.exists()
    assert tmf.read_tags(mp4) == {
        "show": None, "season": None, "episode": None, "title": "Heat",
        "series": "Heat", "year": 1995,
    }
    assert tmf.has_subtitles(mp4, "en")


@needs_ffmpeg
def test_convert_failure_keeps_original(tmf, tmp_path, capsys):
    root = tmp_path / "root"
    path = make_video(root / "Heat" / "Heat.mkv")
    tmf.run_convert(Namespace(
        root=str(root), from_ext="mkv", to_ext="webm", dry_run=False,
    ))
    out, err = capsys.readouterr()
    assert "Failed to convert" in err
    assert "0 file(s) converted, 1 error(s)" in out
    assert path.exists()
    assert list(path.parent.iterdir()) == [path]


@needs_ffmpeg
def test_run_rename(tmf, tmp_path, capsys):
    root = tmp_path / "root"
    episode = make_video(root / "Show" / "Season 1" / "e.mkv")
    movie = make_video(root / "Heat" / "m.mkv")
    tmf.write_tags(episode, {"show": "Show", "season": 1, "episode": 2,
                             "title": "Two"})
    tmf.write_tags(movie, {"series": "Heat", "title": "Heat", "year": 1995})
    args = Namespace(root=str(root), episodes=None, movies=None,
                     dry_run=False)
    tmf.run_rename(args)
    assert "nothing to do" in capsys.readouterr().err
    args.episodes = "%show S%seasonE%episode %title"
    tmf.run_rename(args)
    assert (root / "Show" / "Season 1" / "Show S01E02 Two.mkv").exists()
    assert movie.exists()
    args.movies = "%title (%year)"
    tmf.run_rename(args)
    assert (root / "Heat" / "Heat (1995).mkv").exists()


@needs_ffmpeg
def test_write_tags_warns_about_unsupported_fields(tmf, tmp_path, capsys):
    path = make_video(tmp_path / "Show" / "Season 1" / "e.avi")
    tmf.write_tags(path, {"show": "Show", "season": 1, "episode": 2,
                          "title": "Two"})
    assert ".avi can't store show, season, episode" in \
        capsys.readouterr().err
    assert tmf.read_tags(path)["title"] == "Two"


@needs_ffmpeg
def test_scan_without_tvmaze_uses_filename(tmf, tmp_path, capsys):
    root = tmp_path / "root"
    make_video(root / "Show" / "Season 3" / "S03E07 - Seven.mkv")
    queue = tmp_path / "q.yml"
    tmf.run_scan(Namespace(root=str(root), queue=str(queue),
                           tmdb_api_key=None, no_tvmaze=True,
                           no_subs=True))
    assert "No TVmaze match found" in capsys.readouterr().err
    assert tmf.load_queue(queue) == {"Show/Season 3/S03E07 - Seven.mkv": {
        "show": "Show", "season": 3, "episode": 7, "title": None,
    }}


def test_videos_with_extension(tmf, tmp_path):
    for name in ("a.MKV", "b.mp4"):
        (tmp_path / "Heat").mkdir(exist_ok=True)
        (tmp_path / "Heat" / name).touch()
    videos = tmf.with_extension(tmf.iter_videos(tmp_path), ".mkv")
    assert [p.name for p in videos] == ["a.MKV"]


@pytest.mark.parametrize("step", [
    "scan", "check", "fingerprint", "apply", "convert", "rename",
])
def test_cli_help(tmf, step, capsys):
    with pytest.raises(SystemExit) as exit_info:
        tmf.build_arg_parser().parse_args([step, "-h"])
    assert exit_info.value.code == 0
    assert step in capsys.readouterr().out


def test_cli_dispatch(tmf, monkeypatch):
    calls = []
    monkeypatch.setitem(tmf.STEP_HANDLERS, "scan", calls.append)
    monkeypatch.setenv("TMF_OPENSUBTITLES_API_KEY", "from-env")
    monkeypatch.setattr("sys.argv", [
        "tv_metafix", "scan", "/videos", "--sub-lang", "PT-br",
    ])
    tmf.main()
    assert (calls[0].root, calls[0].sub_lang) == ("/videos", "pt-BR")
    assert calls[0].opensubtitles_api_key == "from-env"
    assert not calls[0].no_subs
    assert calls[0].subs_dir == "tmp/subtitles"


@needs_ffmpeg
def test_dry_runs_change_nothing(tmf, tmp_path, capsys):
    root = tmp_path / "root"
    movie = make_video(root / "Heat" / "m.mkv", "-metadata", "title=Heat")
    sidecar = root / "Heat" / "m.en.srt"
    sidecar.write_text("subs")
    before = movie.read_bytes()
    queue = tmp_path / "q.yml"
    queue.write_text(f"# root: {root.resolve()}\n"
                     "Heat/m.mkv: {series: Heat, title: Heat, year: 1995}\n")

    tmf.run_apply(Namespace(root=str(root), queue=str(queue), dry_run=True,
                            subs_dir=str(tmp_path / "subtitles")))
    tmf.run_convert(Namespace(root=str(root), from_ext="mkv", to_ext="mp4",
                              dry_run=True))
    tmf.run_rename(Namespace(root=str(root), episodes=None,
                             movies="%title", dry_run=True))

    out = capsys.readouterr().out
    assert f"Would apply: {movie}\n  series: Heat\n" in out
    assert "Would convert: m.mkv -> m.mp4" in out
    assert "Would rename: m.en.srt -> Heat.en.srt" in out
    assert "Would rename: m.mkv -> Heat.mkv" in out
    assert movie.read_bytes() == before
    assert sorted(p.name for p in movie.parent.iterdir()) == \
        ["m.en.srt", "m.mkv"]


@needs_ffmpeg
@pytest.mark.parametrize("sidecar, found", [
    ("v.srt", True), ("v.en.srt", True), ("v.eng.srt", True),
    ("v.en.ass", True), ("v.vtt", True), ("v.fr.srt", False),
    ("other.en.srt", False),
])
def test_has_subtitles_sidecars(tmf, tmp_path, sidecar, found):
    video = make_video(tmp_path / "v.mkv")
    (tmp_path / sidecar).write_text("subs")
    assert tmf.has_subtitles(video, "en") == found


@needs_ffmpeg
@pytest.mark.parametrize("ext, language, found", [
    (".mkv", "eng", True), (".mkv", None, True), (".mp4", None, True),
    (".mkv", "fre", False),
])
def test_has_subtitles_embedded(tmf, tmp_path, ext, language, found):
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:00,500\nHi\n")
    video = tmp_path / f"v{ext}"
    codec = "srt" if ext == ".mkv" else "mov_text"
    tags = ["-metadata:s:s:0", f"language={language}"] if language else []
    make_video(video, "-i", str(srt), "-map", "0", "-map", "1",
               "-c:s", codec, *tags)
    assert tmf.has_subtitles(video, "en") == found


@needs_ffmpeg
def test_rename_moves_all_sidecars(tmf, tmp_path):
    video = make_video(tmp_path / "Heat" / "m.mkv", "-metadata", "title=Heat")
    for name in ("m.srt", "m.en.ass"):
        (video.parent / name).write_text("subs")
    tmf.rename_file(video, "%title")
    assert sorted(p.name for p in video.parent.iterdir()) == \
        ["Heat.en.ass", "Heat.mkv", "Heat.srt"]


@pytest.mark.parametrize("text, code", [
    ("en", "en"), ("FR", "fr"), ("pt-br", "pt-BR"), (" zh-CN ", "zh-CN"),
])
def test_subtitle_language(tmf, text, code):
    assert tmf.subtitle_language(text) == code


@pytest.mark.parametrize("text", ["english", "e", "en_US", "pt-BRA", ""])
def test_subtitle_language_rejects(tmf, text):
    with pytest.raises(argparse.ArgumentTypeError):
        tmf.subtitle_language(text)


def test_regional_language_codes(tmf):
    assert tmf.language_codes("pt-BR") == ("pt-BR", "pt", "por")
    assert tmf.iso639_2("pt-BR") == "por"
    assert tmf.iso639_2("de") == "ger"
    assert tmf.iso639_2("xx") == "xx"
