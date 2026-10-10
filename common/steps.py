"""Loops shared by steps that rewrite files one by one."""

from collections import Counter

from .ui import note, outcome, report, warn


def extension(text):
    """"MP3" / ".mp3" -> ".mp3"."""
    return "." + text.lower().lstrip(".")


def convert_extensions(args):
    """(from, to) extensions for `convert`, or None if they match."""
    from_ext, to_ext = extension(args.from_ext), extension(args.to_ext)
    if from_ext == to_ext:
        note("from and to formats are the same -- nothing to do.")
        return None
    return from_ext, to_ext


def process_each(paths, describe, perform, verb, noun, dry_run=False):
    """For each path, report `describe(path)` and, unless `dry_run`,
    `perform(path)`; then print a tally. `verb` is e.g. "convert"."""
    counts = Counter()
    for path in paths:
        detail = describe(path)
        if not dry_run:
            try:
                perform(path)
            except Exception as exc:
                warn(f"Failed to {verb} {path}: {exc}")
                counts["error"] += 1
                continue
        report(verb, detail, dry_run)
        counts["done"] += 1
    print(f"\n{counts['done']} {noun}(s) {outcome(verb, dry_run)}, "
          f"{counts['error']} error(s).")
    return counts
