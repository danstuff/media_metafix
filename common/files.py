"""Walking a library root, .mmfignore rules, and renaming."""

from pathlib import Path

from .ui import missing_package, report, warn

try:
    import pathspec
except ImportError:
    pathspec = None

MMFIGNORE_FILENAME = ".mmfignore"


def load_mmfignore(root):
    """`root`'s .mmfignore as a pathspec, or None."""
    ignore_path = Path(root) / MMFIGNORE_FILENAME
    if not ignore_path.exists():
        return None
    if pathspec is None:
        missing_package(
            "pathspec", "pathspec",
            f"{ignore_path} is present but its rules can't be applied.",
        )
        return None
    with open(ignore_path, encoding="utf-8") as f:
        return pathspec.PathSpec.from_lines("gitwildmatch", f)


def is_ignored(spec, root, path):
    """True if `path` under `root` matches `spec` (None matches
    nothing)."""
    if spec is None:
        return False
    rel = path.relative_to(root).as_posix()
    if path.is_dir():
        rel += "/"
    return spec.match_file(rel)


def iter_dirs(path):
    return sorted(p for p in path.iterdir() if p.is_dir())


def iter_files(path):
    return sorted(p for p in path.iterdir() if p.is_file())


def with_extension(paths, ext):
    return (p for p in paths if p.suffix.lower() == ext)


def iter_kept(spec, root, paths):
    """`paths` minus those `spec` ignores."""
    return (p for p in paths if not is_ignored(spec, root, p))


def iter_queued_files(queue_dir, root):
    """(file, dest_dir) for each file `scan` saved under `queue_dir`,
    where dest_dir is its mirror under root. Missing or ignored mirrors
    are skipped."""
    queue_dir, root = Path(queue_dir), Path(root)
    if not queue_dir.is_dir():
        return
    spec = load_mmfignore(root)
    for file in sorted(p for p in queue_dir.rglob("*") if p.is_file()):
        dest_dir = root / file.parent.relative_to(queue_dir)
        if not dest_dir.is_dir():
            warn(f"No matching folder under root for {file}")
        elif not is_ignored(spec, root, dest_dir):
            yield file, dest_dir


def rename_target(path, new_name):
    """`path` with `new_name`, or None (warned) if that's unchanged,
    taken or invalid."""
    if new_name == path.name:
        return None
    try:
        new_path = path.with_name(new_name)
    except ValueError as exc:
        warn(f"Invalid rename target, skipping: {path} -> {new_name!r} "
             f"({exc})")
        return None
    if new_path.exists():
        warn(f"Rename target already exists, skipping: {new_path}")
        return None
    return new_path


def move(path, new_path, dry_run=False):
    if not dry_run:
        path.rename(new_path)
    report("rename", f"{path.name} -> {new_path.name}", dry_run)
