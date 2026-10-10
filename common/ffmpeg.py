"""Thin wrappers around the ffmpeg/ffprobe CLIs."""

import json
import shutil
import subprocess

from .ui import note


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def require_ffmpeg(action):
    """True if ffmpeg is installed; else note we can't `action`."""
    if ffmpeg_available():
        return True
    note(f"ffmpeg not found -- can't {action}.")
    return False


def run_ffmpeg(cmd, tmp_out):
    """Run `cmd`; on failure delete `tmp_out` and raise RuntimeError."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return
    tmp_out.unlink(missing_ok=True)
    lines = (result.stderr or "").strip().splitlines()
    raise RuntimeError(f"ffmpeg failed: {lines[-1] if lines else 'unknown'}")


def ffprobe_json(path):
    """ffprobe's format + stream info for `path`, as a dict."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-of", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}")
    return json.loads(result.stdout)


def temp_output_path(path, suffix=None):
    """Hidden sibling of `path` for ffmpeg to write to."""
    return path.with_name(f".{path.stem}.mmf-tmp{suffix or path.suffix}")


def replace_with(path, tmp_out, new_suffix=None):
    """Move `tmp_out` over `path` (or to `path` with `new_suffix`,
    deleting the original). Returns the final path."""
    final_path = path if new_suffix is None else path.with_suffix(new_suffix)
    if final_path != path:
        path.unlink()
    tmp_out.replace(final_path)
    return final_path
