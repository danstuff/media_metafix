"""The YAML changes queue: scan writes it, check edits it, apply
reads it."""

import os
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

from .files import is_ignored, load_mmfignore
from .ui import outcome, report, warn, warn_missing_file

ROOT_HEADER_RE = re.compile(r"^#\s*root:\s*(.+?)\s*$")

QUEUE_HEADER = """\
# {kind} metadata changes queue.
#
# Review and edit the fields below as needed, then apply with:
#   {script} apply {root} {queue}
#
# Delete a field to skip just that change, or remove a whole file's entry
# to skip that file entirely. File paths (relative to root) are the keys.
# A "# was: ..." comment shows the field's previous value, where it had one.

"""


def render_yaml_scalar(value):
    """`value` as a single-line flow-style YAML scalar."""
    dumped = yaml.safe_dump(
        value, default_flow_style=True, allow_unicode=True,
        width=float("inf"),
    )
    return dumped.split("\n", 1)[0]


def load_queue(queue_file):
    with open(queue_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def blank_to_none(value):
    """None for "" or [] (but not 0)."""
    return None if value in ("", []) else value


def build_queue_fields(current, updates, keys, coerce=None):
    """(fields, previous): `fields` has every key in `keys`, from
    `updates` else `current`; `previous` has old values of updated
    keys. `coerce(key, value)` may convert non-None values."""
    fields, previous = {}, {}
    for key in keys:
        if key in updates:
            value = updates[key]
            previous[key] = current.get(key)
        else:
            value = blank_to_none(current.get(key))
        if coerce and value is not None:
            value = coerce(key, value)
        fields[key] = value
    return fields, previous


def write_queue_header(queue_f, args, kind):
    queue_f.write(f"# root: {Path(args.root).resolve()}\n")
    queue_f.write(QUEUE_HEADER.format(
        kind=kind, script=sys.argv[0], root=args.root, queue=args.queue,
    ))
    queue_f.flush()


def field_lines(fields, previous=None):
    """Queue lines for `fields`, with "# was:" comments from
    `previous`."""
    lines = []
    for key, value in fields.items():
        line = f"  {key}: {render_yaml_scalar(value)}"
        if previous and previous.get(key):
            line += f"  # was: {render_yaml_scalar(previous[key])}"
        lines.append(line)
    return lines


def write_queue_entry(queue_f, file, fields, previous):
    """Print one entry and append it to the queue, fsynced so a crash
    keeps prior results."""
    lines = [f"{render_yaml_scalar(file)}:", *field_lines(fields, previous)]
    entry = "\n".join(lines) + "\n"
    print(entry, end="")
    queue_f.write(entry)
    queue_f.flush()
    os.fsync(queue_f.fileno())


def scan_one_file(queue_f, compute, path):
    """Queue `path`'s change, if any. Returns "queued", "ok" or
    "error"."""
    try:
        entry = compute(path)
    except Exception as exc:
        warn(f"Unexpected error on {path}: {exc}")
        return "error"
    if entry is None:
        print(f"{path}: OK")
        return "ok"
    file, fields, previous = entry
    write_queue_entry(queue_f, file, fields, previous)
    return "queued"


def print_scan_summary(counts, args):
    if counts["queued"]:
        script = sys.argv[0]
        print(f"\n{counts['queued']} pending change(s) written to "
              f"{args.queue}")
        print(
            "Review it, then optionally:\n"
            f"  {script} check {args.queue}\n"
            f"  {script} fingerprint {args.root} {args.queue}\n"
            "then apply with:\n"
            f"  {script} apply {args.root} {args.queue}"
        )
    else:
        print("\nNo changes needed.")
    print(f"({counts['ok']} already correct, {counts['error']} errors)")


def scan_to_queue(args, paths, compute, kind):
    """Write `compute(path)` for each of `paths` to args.queue.
    `compute` returns None or (file, fields, previous)."""
    counts = Counter()
    queue_path = Path(args.queue)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_path, "w", encoding="utf-8") as queue_f:
        write_queue_header(queue_f, args, kind)
        for path in paths:
            counts[scan_one_file(queue_f, compute, path)] += 1
    return counts


def read_root_header(queue_file):
    """The root `scan` stamped on `queue_file`, or None."""
    with open(queue_file, encoding="utf-8") as f:
        match = ROOT_HEADER_RE.match(f.readline())
    return match.group(1) if match else None


def verify_queue_root(queue_file, root):
    """Exit if `queue_file` was scanned from a different root."""
    stored_root = read_root_header(queue_file)
    if stored_root is None:
        warn(f"{queue_file} has no recorded root -- skipping root check.")
        return
    resolved_root = str(Path(root).resolve())
    if stored_root != resolved_root:
        print(
            f"Error: {queue_file} was scanned for root {stored_root!r}, "
            f"but apply was given root {resolved_root!r}.",
            file=sys.stderr,
        )
        sys.exit(1)


def preview_fields(path, fields):
    """Print the non-null `fields` a dry-run apply would write."""
    report("apply", path, dry_run=True)
    set_fields = {k: v for k, v in fields.items() if v is not None}
    print("\n".join(field_lines(set_fields)))


def apply_one_file(root, spec, file, fields, write_fields, dry_run):
    """`write_fields(path, fields)` for one entry, unless `dry_run`.
    Returns "applied", "ignored" or "error"."""
    path = root / file
    if is_ignored(spec, root, path):
        warn(f"Ignored by .mmfignore, skipping: {path}")
        return "ignored"
    if not path.exists():
        warn_missing_file(path)
        return "error"
    if dry_run:
        preview_fields(path, fields)
        return "applied"
    try:
        write_fields(path, fields)
    except Exception as exc:
        warn(f"Failed to apply changes to {path}: {exc}")
        return "error"
    report("apply", path, dry_run)
    return "applied"


def apply_queue(root, queue_file, write_fields, dry_run=False):
    """Apply every entry of `queue_file` via `write_fields`."""
    root = Path(root)
    spec = load_mmfignore(root)
    counts = Counter()
    for file, fields in load_queue(queue_file).items():
        counts[apply_one_file(
            root, spec, file, fields, write_fields, dry_run,
        )] += 1
    print(
        f"\n{counts['applied']} {outcome('apply', dry_run)}, "
        f"{counts['error']} errors, {counts['ignored']} ignored."
    )
    return counts
