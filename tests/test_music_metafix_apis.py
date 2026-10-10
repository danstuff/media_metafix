"""MusicBrainz, Cover Art Archive and AcoustID code, with every
network call faked out."""

import argparse
import io
from argparse import Namespace
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from conftest import make_audio, needs_ffmpeg, write_queue

RELEASE = {"release": {"medium-list": [{"track-list": [
    {"position": "1", "recording": {
        "title": "First Song",
        "artist-credit": [{"artist": {"name": "Artist A"}}],
    }},
    {"position": "2", "recording": {
        "title": "Second Song",
        "artist-credit": [
            {"artist": {"name": "Artist A"}}, " feat. ",
            {"artist": {"name": "Guest"}},
        ],
    }},
]}]}}


class FakeMusicBrainz:
    """Stands in for the musicbrainzngs module."""

    def __init__(self, releases=({"id": "mbid-1"},)):
        self.releases = list(releases)
        self.searches = []

    def set_useragent(self, *_args):
        pass

    def search_releases(self, artist, release, limit):
        self.searches.append((artist, release))
        return {"release-list": self.releases}

    def get_release_by_id(self, release_id, includes):
        assert release_id == "mbid-1"
        return RELEASE


class FakeAcoustid:
    """Stands in for the acoustid module."""

    class AcoustidError(Exception):
        pass

    class WebServiceError(AcoustidError):
        pass

    class NoBackendError(AcoustidError):
        pass

    def __init__(self, response):
        self.response = response

    def fingerprint_file(self, path):
        if isinstance(self.response, Exception):
            raise self.response
        return 180, "fp"

    def lookup(self, api_key, fp, duration, meta):
        assert (api_key, fp, duration) == ("key", "fp", 180)
        return self.response


@pytest.fixture
def fake_mb(mmf, monkeypatch):
    fake = FakeMusicBrainz()
    monkeypatch.setattr(mmf, "musicbrainzngs", fake)
    return fake


def acoustid_results(*scored_titles):
    return {"status": "ok", "results": [
        {"score": score, "recordings": [{"title": title}]}
        for score, title in scored_titles
    ]}


def jpeg_bytes():
    Image = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buffer, "JPEG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# MusicBrainz
# ---------------------------------------------------------------------------

def test_recognize_via_musicbrainz_text(mmf, fake_mb):
    assert mmf.recognize_via_musicbrainz_text("Artist A", "Album") == {
        1: {"title": "First Song", "artists": ["Artist A"]},
        2: {"title": "Second Song", "artists": ["Artist A", "Guest"]},
    }
    assert fake_mb.searches == [("Artist A", "Album")]


def test_recognize_no_release(mmf, fake_mb):
    fake_mb.releases = []
    assert mmf.recognize_via_musicbrainz_text("X", "Y") is None


@pytest.mark.parametrize("filename_track, filename_title, expected", [
    (2, "whatever", 2),       # a filename track number wins
    (None, "second song", 2),  # else fuzzy title matching
    (None, "nothing like it", None),
])
def test_locate_track(mmf, fake_mb, filename_track, filename_title,
                      expected):
    track_map = mmf.album_tracks(
        "Artist A", "Album", Namespace(no_musicbrainz=False), {},
    )
    assert mmf.locate_track(
        track_map, filename_track, filename_title) == expected


def test_album_tracks_cached_and_optional(mmf, fake_mb):
    cache = {}
    args = Namespace(no_musicbrainz=False)
    mmf.album_tracks("A", "B", args, cache)
    mmf.album_tracks("A", "B", args, cache)
    assert fake_mb.searches == [("A", "B")]
    assert mmf.album_tracks(
        "A", "B", Namespace(no_musicbrainz=True), {}) is None


def test_apply_track_match(mmf):
    updates = {}
    match = {"title": "Second Song", "artists": ["Artist A", "Guest"]}
    mmf.apply_track_match(
        updates, {"title": "second song", "tracknumber": "1"}, 2, match,
    )
    assert updates == {"title": "Second Song", "tracknumber": "2",
                       "artists": ["Artist A", "Guest"]}


@needs_ffmpeg
def test_scan_queues_musicbrainz_changes_and_art(mmf, fake_mb, monkeypatch,
                                                 tmp_path):
    monkeypatch.setattr(mmf, "fetch_cover_art", lambda _id: jpeg_bytes())
    root = tmp_path / "root"
    make_audio(root / "Artist A" / "Album" / "02 - second.mp3",
               "-metadata", "title=old")
    queue = tmp_path / "q.yml"
    art_dir = tmp_path / "art"
    mmf.run_scan(Namespace(
        root=str(root), queue=str(queue), no_art=False,
        art_dir=str(art_dir), art_fn="art.jpg",
        musicbrainz_contact="me@example.com", no_musicbrainz=False,
    ))
    assert mmf.load_queue(queue) == {"Artist A/Album/02 - second.mp3": {
        "album": "Album", "artist": "Artist A",
        "artists": ["Artist A", "Guest"], "title": "Second Song",
        "tracknumber": 2,
    }}
    assert (art_dir / "Artist A" / "Album" / "art.jpg").exists()


# ---------------------------------------------------------------------------
# Cover Art Archive
# ---------------------------------------------------------------------------

def test_fetch_cover_art_url(mmf, monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return io.BytesIO(b"img")

    monkeypatch.setattr(mmf, "urlopen", fake_urlopen)
    assert mmf.fetch_cover_art("mbid-1") == b"img"
    assert requests[0].full_url == \
        "https://coverartarchive.org/release/mbid-1/front"


def test_download_album_art_resizes(mmf, fake_mb, monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(mmf, "fetch_cover_art", lambda _id: jpeg_bytes())
    mmf.download_album_art("A", "B", tmp_path, "art.jpg")
    with Image.open(tmp_path / "art.jpg") as image:
        assert image.size == mmf.ALBUM_ART_SIZE


def test_download_album_art_missing(mmf, fake_mb, monkeypatch, tmp_path,
                                    capsys):
    def not_found(_id):
        raise HTTPError("url", 404, "Not Found", {}, None)
    monkeypatch.setattr(mmf, "fetch_cover_art", not_found)
    mmf.download_album_art("A", "B", tmp_path, "art.jpg")
    assert "No cover art available for A/B" in capsys.readouterr().err
    assert not (tmp_path / "art.jpg").exists()


# ---------------------------------------------------------------------------
# AcoustID
# ---------------------------------------------------------------------------

def test_acoustid_titles_filter_low_scores(mmf, monkeypatch):
    monkeypatch.setattr(mmf, "acoustid", FakeAcoustid(acoustid_results(
        (0.9, "Reckoner (Live)"), (0.2, "Unlikely"),
    )))
    assert mmf.acoustid_recording_titles("x.mp3", "key") == [
        "Reckoner (Live)"]
    assert mmf.check_fingerprint_title("x.mp3", "key", "Reckoner")[0]


def test_acoustid_error_status(mmf, monkeypatch):
    fake = FakeAcoustid({"status": "error", "error": {"message": "bad"}})
    monkeypatch.setattr(mmf, "acoustid", fake)
    with pytest.raises(fake.WebServiceError, match="bad"):
        mmf.acoustid_recording_titles("x.mp3", "key")


def fingerprint(mmf, tmp_path, queue_text):
    root = tmp_path / "root"
    for name in ("a.mp3", "b.mp3"):
        (root / "A" / "B").mkdir(parents=True, exist_ok=True)
        (root / "A" / "B" / name).touch()
    queue = write_queue(tmp_path / "q.yml", queue_text)
    mmf.run_fingerprint(Namespace(
        root=str(root), queue=str(queue), acoustid_api_key="key",
    ))


def test_run_fingerprint_reports_mismatch(mmf, monkeypatch, tmp_path,
                                          capsys):
    monkeypatch.setattr(mmf, "acoustid", FakeAcoustid(acoustid_results(
        (0.9, "Pilot"),
    )))
    fingerprint(mmf, tmp_path, (
        "A/B/a.mp3: {title: Pilot}\n"
        "A/B/b.mp3: {title: Something Else}\n"
    ))
    out, err = capsys.readouterr()
    assert "A/B/b.mp3: queued title 'Something Else' doesn't match" in err
    assert "A/B/a.mp3" not in err
    assert "2 track(s) fingerprinted, 1 mismatch(es)" in out


def test_run_fingerprint_aborts_without_fpcalc(mmf, monkeypatch, tmp_path,
                                               capsys):
    fake = FakeAcoustid(None)
    fake.response = fake.NoBackendError()
    monkeypatch.setattr(mmf, "acoustid", fake)
    fingerprint(mmf, tmp_path, "A/B/a.mp3: {title: Pilot}\n")
    assert "fpcalc/chromaprint not found" in capsys.readouterr().err


def test_run_fingerprint_needs_key(mmf, monkeypatch, capsys):
    monkeypatch.setattr(mmf, "acoustid", SimpleNamespace())
    mmf.run_fingerprint(Namespace(acoustid_api_key=None))
    assert "no AcoustID API key" in capsys.readouterr().err


def test_queue_album_art_skips_albums_with_art(mmf, fake_mb, monkeypatch,
                                               tmp_path):
    monkeypatch.setattr(mmf, "fetch_cover_art", lambda _id: jpeg_bytes())
    root = tmp_path / "root"
    (root / "A" / "Has Art").mkdir(parents=True)
    (root / "A" / "Has Art" / "art.jpg").write_bytes(b"mine")
    (root / "A" / "No Art").mkdir(parents=True)
    art_dir = tmp_path / "art"
    mmf.queue_album_art(root, art_dir, "art.jpg", "me@example.com")
    assert fake_mb.searches == [("A", "No Art")]
    assert (art_dir / "A" / "No Art" / "art.jpg").exists()
    assert not (art_dir / "A" / "Has Art").exists()


def test_apply_album_art_keeps_existing(mmf, tmp_path, capsys):
    root = tmp_path / "root"
    for album in ("Has Art", "No Art"):
        (root / "A" / album).mkdir(parents=True)
        queued = tmp_path / "art" / "A" / album / "art.jpg"
        queued.parent.mkdir(parents=True)
        queued.write_bytes(b"new")
    (root / "A" / "Has Art" / "art.jpg").write_bytes(b"mine")
    assert mmf.apply_album_art(root, tmp_path / "art") == 1
    assert (root / "A" / "Has Art" / "art.jpg").read_bytes() == b"mine"
    assert (root / "A" / "No Art" / "art.jpg").read_bytes() == b"new"
    assert "Keeping existing album art" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["art.jpg", "cover.PNG", "folder.webp"])
def test_art_filename_accepts(mmf, name):
    assert mmf.art_filename(name) == name


@pytest.mark.parametrize("name, error", [
    ("dir/art.jpg", "plain filename"), ("", "plain filename"),
    ("cover", "no image extension"), ("cover.xyz", "can't save '.xyz'"),
])
def test_art_filename_rejects(mmf, name, error):
    with pytest.raises(argparse.ArgumentTypeError, match=error):
        mmf.art_filename(name)


@pytest.mark.parametrize("name, fmt", [
    ("art.jpg", "JPEG"), ("cover.png", "PNG"), ("folder.webp", "WEBP"),
])
def test_album_art_format_follows_extension(mmf, fake_mb, monkeypatch,
                                            tmp_path, name, fmt):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(mmf, "fetch_cover_art", lambda _id: jpeg_bytes())
    mmf.download_album_art("A", "B", tmp_path, name)
    with Image.open(tmp_path / name) as image:
        assert image.format == fmt


@needs_ffmpeg
def test_scan_with_custom_art_filename(mmf, fake_mb, monkeypatch,
                                       tmp_path):
    monkeypatch.setattr(mmf, "fetch_cover_art", lambda _id: jpeg_bytes())
    root = tmp_path / "root"
    make_audio(root / "A" / "Has Cover" / "01 - x.mp3")
    make_audio(root / "A" / "No Cover" / "01 - y.mp3")
    (root / "A" / "Has Cover" / "cover.png").write_bytes(b"mine")
    art_dir = tmp_path / "art"
    mmf.run_scan(Namespace(
        root=str(root), queue=str(tmp_path / "q.yml"), no_art=False,
        art_dir=str(art_dir), art_fn="cover.png",
        musicbrainz_contact="me@example.com", no_musicbrainz=True,
    ))
    assert sorted(p.relative_to(art_dir).as_posix()
                  for p in art_dir.rglob("*.*")) == ["A/No Cover/cover.png"]
