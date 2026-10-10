import shutil
import socket
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

needs_ffmpeg = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not installed",
)


def load_script(name):
    """Import an extensionless script from the repo root."""
    loader = SourceFileLoader(name, str(REPO / name))
    module = module_from_spec(spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to reach a real API."""
    def refuse(*_args, **_kwargs):
        raise RuntimeError("tests must not use the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(scope="session")
def tmf():
    return load_script("tv_metafix")


@pytest.fixture(scope="session")
def mmf():
    pytest.importorskip("mutagen")
    return load_script("music_metafix")


@pytest.fixture
def answer(monkeypatch):
    """answer("2") makes every check prompt pick option 2."""
    def set_answer(choice):
        monkeypatch.setattr("builtins.input", lambda _prompt: choice)
    return set_answer


def make_video(path, *metadata):
    """A short test video at `path`, with optional -metadata args."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=duration=1:size=64x48:rate=5",
            "-c:v", "mpeg4", *metadata, str(path),
        ],
        check=True,
    )
    return path


def make_audio(path, *metadata):
    """A short sine-wave audio file at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", "sine=duration=0.2", *metadata, str(path),
        ],
        check=True,
    )
    return path


def write_queue(path, text):
    path.write_text(f"# root: /nowhere\n{text}", encoding="utf-8")
    return path
