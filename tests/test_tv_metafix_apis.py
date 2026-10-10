"""TVmaze, TMDB and OpenSubtitles code, with HTTP faked out."""

from argparse import Namespace
from urllib.error import HTTPError

import pytest

from conftest import make_video, needs_ffmpeg, write_queue

SRT = b"1\n00:00:00,000 --> 00:00:00,500\nHello\n"
EPISODES = {
    "name": "The Office",
    "_embedded": {"episodes": [
        {"season": 1, "number": 1, "name": "Pilot"},
        {"season": 1, "number": 2, "name": "Diversity Day"},
        {"season": 0, "number": None, "name": "Unnumbered special"},
    ]},
}


class FakeApi:
    """Stands in for fetch_json/fetch, answering by URL suffix and
    recording every call as (url, params, headers, body)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def fetch_json(self, url, params=None, headers=None, body=None):
        self.calls.append((url, params or {}, headers or {}, body))
        for suffix, respond in self.routes.items():
            if url.endswith(suffix):
                return respond(params or {}, body)
        raise AssertionError(f"unexpected request to {url}")

    def fetch(self, url, params=None, headers=None, body=None):
        self.calls.append((url, params or {}, headers or {}, body))
        return SRT

    def requests_to(self, suffix):
        return [c for c in self.calls if c[0].endswith(suffix)]


@pytest.fixture
def fake_api(tmf, monkeypatch):
    def install(**routes):
        api = FakeApi({
            "/" + name.replace("_", "/"): respond
            for name, respond in routes.items()
        })
        monkeypatch.setattr(tmf, "fetch_json", api.fetch_json)
        monkeypatch.setattr(tmf, "fetch", api.fetch)
        return api
    return install


def not_found(*_args):
    raise HTTPError("url", 404, "Not Found", {}, None)


def subtitle(file_id, hash_match=False, downloads=1, **feature):
    return {"attributes": {
        "moviehash_match": hash_match, "download_count": downloads,
        "files": [{"file_id": file_id}], "feature_details": feature,
    }}


# ---------------------------------------------------------------------------
# Metadata lookups
# ---------------------------------------------------------------------------

def test_tvmaze_episodes(tmf, fake_api):
    api = fake_api(shows=lambda params, body: EPISODES)
    name, titles = tmf.tvmaze_episodes("the office")
    assert name == "The Office"
    assert titles == {(1, 1): "Pilot", (1, 2): "Diversity Day"}
    _url, params, headers, _body = api.calls[0]
    assert params == {"q": "the office", "embed": "episodes"}
    assert headers["User-Agent"] == tmf.USER_AGENT


def test_tvmaze_unknown_show(tmf, fake_api):
    fake_api(shows=not_found)
    assert tmf.tvmaze_episodes("nope") is None


def test_show_episodes_warns_on_other_show(tmf, fake_api, capsys):
    api = fake_api(shows=lambda params, body: EPISODES)
    args = Namespace(no_tvmaze=False)
    cache = {}
    assert tmf.show_episodes("Office", args, cache)[(1, 1)] == "Pilot"
    assert "TVmaze matched 'The Office' for folder 'Office'" in \
        capsys.readouterr().err
    assert tmf.show_episodes("Office", args, cache)
    assert len(api.calls) == 1  # cached


def test_lookup_failure_is_cached_as_none(tmf, fake_api, capsys):
    def server_error(*_args):
        raise HTTPError("url", 500, "Oops", {}, None)
    api = fake_api(shows=server_error)
    args, cache = Namespace(no_tvmaze=False), {}
    assert tmf.show_episodes("X", args, cache) is None
    assert tmf.show_episodes("X", args, cache) is None
    assert len(api.calls) == 1
    assert "TVmaze lookup for 'X' failed" in capsys.readouterr().err


def test_tmdb_movie(tmf, fake_api):
    api = fake_api(movie=lambda params, body: {"results": [
        {"title": "Heat", "release_date": "1995-12-15"},
        {"title": "Heat 2", "release_date": ""},
    ]})
    assert tmf.tmdb_movie("heat", 1995, "key") == {
        "title": "Heat", "year": 1995,
    }
    assert api.calls[0][1] == {"query": "heat", "api_key": "key",
                               "year": 1995}


def test_tmdb_no_results(tmf, fake_api):
    api = fake_api(movie=lambda params, body: {"results": []})
    assert tmf.tmdb_movie("zzz", None, "key") is None
    assert "year" not in api.calls[0][1]


@needs_ffmpeg
def test_scan_uses_tmdb(tmf, fake_api, tmp_path):
    fake_api(movie=lambda params, body: {"results": [{
        "title": "Harry Potter and the Philosopher's Stone",
        "release_date": "2001-11-16",
    }]})
    root = tmp_path / "root"
    make_video(root / "Harry Potter" / "Sorcerers Stone (2001).mkv")
    queue = tmp_path / "q.yml"
    tmf.run_scan(Namespace(
        root=str(root), queue=str(queue), tmdb_api_key="key",
        no_tvmaze=True, no_subs=True,
    ))
    assert tmf.load_queue(queue) == {
        "Harry Potter/Sorcerers Stone (2001).mkv": {
            "series": "Harry Potter",
            "title": "Harry Potter and the Philosopher's Stone",
            "year": 2001,
        },
    }


# ---------------------------------------------------------------------------
# OpenSubtitles client
# ---------------------------------------------------------------------------

def test_opensubtitles_login_search_download(tmf, fake_api):
    api = fake_api(
        login=lambda params, body: {"token": "tok"},
        subtitles=lambda params, body: {"data": [subtitle(7)]},
        download=lambda params, body: {"link": "https://dl.example/7"},
    )
    client = tmf.OpenSubtitles("key")
    client.login("user", "pass")
    results = client.search(languages="en", year=None, query="Heat")
    assert client.download(7) == SRT

    login, search, download, link = api.calls
    assert login[3] == {"username": "user", "password": "pass"}
    assert login[2]["Api-Key"] == "key"
    assert "Authorization" not in login[2]
    assert search[1] == {"languages": "en", "query": "Heat"}
    assert search[2]["Authorization"] == "Bearer tok"
    assert results[0]["attributes"]["files"] == [{"file_id": 7}]
    assert download[3] == {"file_id": 7}
    assert link[0] == "https://dl.example/7"


def test_opensubtitles_client_needs_key(tmf, capsys):
    assert tmf.opensubtitles_client(
        Namespace(opensubtitles_api_key=None)) is None
    assert "no OpenSubtitles API key" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

def big_file(path, seed=0):
    """Large enough to hash (two 64 KiB chunks); `seed` varies it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes([seed]) + bytes(range(256)) * 1024)
    return path


def test_fingerprint(tmf, fake_api, tmp_path, capsys):
    root = tmp_path / "root"
    known = {
        "Show/S1/a.mkv": [subtitle(1, hash_match=True, title="Pilot",
                                   season_number=1, episode_number=1)],
        "Show/S1/b.mkv": [subtitle(2, hash_match=True, title="Pilot",
                                   season_number=1, episode_number=1)],
        "Show/S1/c.mkv": [subtitle(3, title="Pilot")],  # no hash match
    }
    hashes = {}
    for seed, file in enumerate(known):
        hashes[tmf.oshash(big_file(root / file, seed))] = known[file]
    hashes[tmf.oshash(big_file(root / "Heat" / "Heat.mkv", 9))] = [
        subtitle(4, hash_match=True, title="Heat", year=1995)]
    api = fake_api(subtitles=lambda params, body: {
        "data": hashes[params["moviehash"]],
    })
    queue = write_queue(tmp_path / "q.yml", (
        "Show/S1/a.mkv: {season: 1, episode: 1, title: Pilot}\n"
        "Show/S1/b.mkv: {season: 1, episode: 2, title: Two}\n"
        "Show/S1/c.mkv: {season: 1, episode: 3, title: Three}\n"
        "Heat/Heat.mkv: {title: Heat, year: 1995}\n"
        "Gone/Gone.mkv: {title: Gone}\n"
    ))
    tmf.run_fingerprint(Namespace(
        root=str(root), queue=str(queue), opensubtitles_api_key="key",
    ))
    out, err = capsys.readouterr()
    assert "Show/S1/b.mkv: queued entry doesn't match" in err
    assert "S1E1 'Pilot'" in err
    assert "Show/S1/a.mkv" not in err
    assert "File not found" in err
    assert ("3 file(s) identified, 1 mismatch(es), 1 unknown, "
            "1 skipped.") in out
    assert len(api.requests_to("/subtitles")) == 4


def test_fingerprint_lookup_error_skips(tmf, fake_api, tmp_path, capsys):
    def server_error(*_args):
        raise HTTPError("url", 503, "Down", {}, None)
    fake_api(subtitles=server_error)
    root = tmp_path / "root"
    big_file(root / "Heat" / "Heat.mkv")
    queue = write_queue(tmp_path / "q.yml", "Heat/Heat.mkv: {title: H}\n")
    tmf.run_fingerprint(Namespace(
        root=str(root), queue=str(queue), opensubtitles_api_key="key",
    ))
    assert "Hash lookup failed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# subtitles
# ---------------------------------------------------------------------------

def test_find_subtitle_prefers_hash_match(tmf, fake_api, monkeypatch):
    monkeypatch.setattr(tmf, "oshash", lambda path: "abc")
    api = fake_api(subtitles=lambda params, body: {"data": [
        subtitle(1, downloads=99), subtitle(2, hash_match=True),
    ]})
    assert tmf.find_subtitle(tmf.OpenSubtitles("k"), None, None, "en") == 2
    # A hash match means no fallback text search.
    assert len(api.calls) == 1
    assert api.calls[0][1] == {"languages": "en", "moviehash": "abc"}


def scan_args(root, tmp_path, lang="en"):
    return Namespace(
        root=str(root), queue=str(tmp_path / "q.yml"), tmdb_api_key=None,
        no_tvmaze=True, no_subs=False, sub_lang=lang,
        subs_dir=str(tmp_path / "subtitles"),
        opensubtitles_api_key="key", opensubtitles_username=None,
    )


def apply_args(root, tmp_path, dry_run=False):
    return Namespace(
        root=str(root), queue=str(tmp_path / "q.yml"), dry_run=dry_run,
        subs_dir=str(tmp_path / "subtitles"),
    )


LANGUAGES = {"data": [
    {"language_code": code, "language_name": code}
    for code in ("en", "fr", "pt-BR", "pt-PT", "zh-CN")
]}


def languages(_params, _body):
    return LANGUAGES


def subtitle_api(fake_api):
    return fake_api(
        infos_languages=languages,
        subtitles=lambda params, body: {
            "data": [] if "moviehash" in params else [subtitle(9)],
        },
        download=lambda params, body: {"link": "https://dl.example/9"},
    )


@needs_ffmpeg
def test_scan_downloads_subtitles(tmf, fake_api, tmp_path, capsys):
    root = tmp_path / "root"
    episode = make_video(root / "Show" / "Season 2" / "S02E05 - X.mkv")
    make_video(root / "Heat" / "Heat (1995).avi")
    api = subtitle_api(fake_api)
    tmf.run_scan(scan_args(root, tmp_path))
    subtitles = tmp_path / "subtitles"
    assert (subtitles / "Show" / "Season 2" / "S02E05 - X.en.srt"
            ).read_bytes() == SRT
    assert (subtitles / "Heat" / "Heat (1995).en.srt").read_bytes() == SRT
    assert "2 subtitle file(s) downloaded" in capsys.readouterr().out
    assert not tmf.has_subtitles(episode, "en")  # scan changes nothing

    searches = [c[1] for c in api.requests_to("/subtitles")
                if "query" in c[1]]
    assert {"languages": "en", "query": "Heat", "year": 1995,
            "type": "movie"} in searches
    assert {"languages": "en", "query": "Show", "season_number": 2,
            "episode_number": 5, "type": "episode"} in searches

    api.calls.clear()
    tmf.run_scan(scan_args(root, tmp_path))
    assert "2 already present" in capsys.readouterr().out
    assert api.requests_to("/download") == []


@needs_ffmpeg
def test_apply_embeds_subtitles(tmf, fake_api, tmp_path, capsys):
    root = tmp_path / "root"
    episode = make_video(root / "Show" / "Season 2" / "S02E05 - X.mkv")
    movie = make_video(root / "Heat" / "Heat (1995).avi")
    subtitle_api(fake_api)
    tmf.run_scan(scan_args(root, tmp_path))
    before = episode.read_bytes()

    tmf.run_apply(apply_args(root, tmp_path, dry_run=True))
    assert f"Would subtitle: {episode}" in capsys.readouterr().out
    assert episode.read_bytes() == before

    tmf.run_apply(apply_args(root, tmp_path))
    assert "2 video(s) subtitled." in capsys.readouterr().out
    assert tmf.has_subtitles(episode, "en")
    assert (movie.parent / "Heat (1995).en.srt").read_bytes() == SRT

    tmf.run_apply(apply_args(root, tmp_path))
    assert "Keeping existing en subtitles" in capsys.readouterr().out
    assert len(tmf.subtitle_streams(episode)) == 1


@needs_ffmpeg
def test_scan_subtitles_not_found(tmf, fake_api, tmp_path, capsys):
    root = tmp_path / "root"
    make_video(root / "Heat" / "Heat.mkv")
    fake_api(infos_languages=languages,
             subtitles=lambda params, body: {"data": []})
    tmf.run_scan(scan_args(root, tmp_path, lang="fr"))
    out, err = capsys.readouterr()
    assert "No fr subtitles found" in err
    assert "1 not found" in out
    assert not (tmp_path / "subtitles").exists()


def test_orphan_subtitle_is_reported(tmf, tmp_path, capsys):
    root = tmp_path / "root"
    (root / "Heat").mkdir(parents=True)
    srt = tmp_path / "subtitles" / "Heat" / "Gone.en.srt"
    srt.parent.mkdir(parents=True)
    srt.write_bytes(SRT)
    assert tmf.apply_subtitles(root, tmp_path / "subtitles", False) == 0
    assert "No video for queued subtitles" in capsys.readouterr().err


def test_verified_language(tmf, fake_api, capsys):
    fake_api(infos_languages=languages)
    client = tmf.OpenSubtitles("k")
    assert tmf.verified_language(client, "PT-br") == "pt-BR"
    with pytest.raises(SystemExit, match="no 'de' subtitles.*pt-BR"):
        tmf.verified_language(client, "de")


def test_verified_language_unreachable(tmf, fake_api, capsys):
    def down(*_args):
        raise HTTPError("url", 503, "Down", {}, None)
    fake_api(infos_languages=down)
    assert tmf.verified_language(tmf.OpenSubtitles("k"), "de") == "de"
    assert "using 'de' unchecked" in capsys.readouterr().err


@needs_ffmpeg
def test_scan_rejects_language_before_scanning(tmf, fake_api, tmp_path):
    root = tmp_path / "root"
    (root / "Heat").mkdir(parents=True)
    (root / "Heat" / "Heat.mkv").touch()
    api = fake_api(infos_languages=languages)
    with pytest.raises(SystemExit):
        tmf.run_scan(scan_args(root, tmp_path, lang="de"))
    assert not (tmp_path / "q.yml").exists()
    assert api.requests_to("/subtitles") == []


@needs_ffmpeg
def test_regional_subtitles(tmf, fake_api, tmp_path, capsys):
    root = tmp_path / "root"
    movie = make_video(root / "Heat" / "Heat (1995).mkv")
    api = subtitle_api(fake_api)
    tmf.run_scan(scan_args(root, tmp_path, lang="pt-BR"))
    assert api.calls[0][0].endswith("/infos/languages")
    assert all(c[1]["languages"] == "pt-BR"
               for c in api.requests_to("/subtitles"))
    srt = tmp_path / "subtitles" / "Heat" / "Heat (1995).pt-BR.srt"
    assert srt.read_bytes() == SRT

    tmf.run_apply(apply_args(root, tmp_path))
    streams = tmf.subtitle_streams(movie)
    assert [s["tags"]["language"] for s in streams] == ["por"]
    assert tmf.has_subtitles(movie, "pt-BR")
    assert not tmf.has_subtitles(movie, "fr")
