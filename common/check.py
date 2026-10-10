"""The `check` step: flag suspicious queue entries and ask how to
resolve each one."""

import os
import re
import subprocess
from pathlib import Path

import yaml

from .text import FUZZY_SAME_ENOUGH, fuzzy_ratio, leading_int, titles_match
from .ui import build_editor_command, prompt_action


class RestartCheck(Exception):
    """Open an editor on the queue at `line`, then re-run the check."""

    def __init__(self, line=None):
        super().__init__()
        self.line = line


class CheckStats:
    def __init__(self):
        self.warnings = 0
        self.resolved = 0
        self.changed = False


# ---------------------------------------------------------------------------
# Locating queue entries in the raw file
# ---------------------------------------------------------------------------

def find_entry_line(lines, file):
    """Index of `file`'s top-level key line, or None."""
    for i, line in enumerate(lines):
        if not line or line[0] in " #":
            continue
        try:
            parsed = yaml.safe_load(line)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and file in parsed:
            return i
    return None


def entry_line_range(lines, start):
    """Exclusive end index of the entry starting at `start`."""
    end = start + 1
    while end < len(lines) and lines[end].startswith("  "):
        end += 1
    return end


def find_field_line(lines, file, key):
    """Index of `key`'s line within `file`'s entry, or None."""
    start = find_entry_line(lines, file)
    if start is None:
        return None
    for i in range(start + 1, entry_line_range(lines, start)):
        if re.match(rf"^  {re.escape(key)}:", lines[i]):
            return i
    return None


def line_has_ok_comment(lines, index):
    if index is None or index >= len(lines):
        return False
    return bool(re.search(r"# OK\b", lines[index], re.IGNORECASE))


def add_ok_comment(lines, index):
    if not line_has_ok_comment(lines, index):
        lines[index] += "  # OK"


# ---------------------------------------------------------------------------
# Warning resolution
# ---------------------------------------------------------------------------

def resolve_warning(lines, stats, message, ok_lines, restart_line):
    """Report `message` unless an `ok_lines` line is marked "# OK";
    otherwise prompt. "manual" raises RestartCheck at
    `restart_line`; "always_skip" marks `ok_lines` "# OK"."""
    stats.warnings += 1
    if any(line_has_ok_comment(lines, i) for i in ok_lines):
        print(f"  ! {message}")
        return None
    action = prompt_action(message)
    if action == "manual":
        raise RestartCheck(restart_line)
    if action == "always_skip":
        for i in ok_lines:
            if i is not None:
                add_ok_comment(lines, i)
        stats.changed = True
        stats.resolved += 1
    return action


def warn_entry(lines, stats, message, file):
    """Warning anchored on `file`'s key line."""
    line = find_entry_line(lines, file)
    resolve_warning(lines, stats, message, [line], line)


def warn_field(lines, stats, message, file, key):
    """Warning anchored on `file`'s `key` line."""
    line = find_field_line(lines, file, key)
    resolve_warning(lines, stats, message, [line], line)


def warn_fields(lines, stats, message, file_keys):
    """Warning anchored on several (file, key) lines."""
    ok_lines = [find_field_line(lines, f, k) for f, k in file_keys]
    resolve_warning(lines, stats, message, ok_lines, ok_lines[0])


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------

def group_field_values(group, key, normalize):
    """{normalize(value): [(file, value), ...]} over `group`'s
    (file, fields) pairs, skipping values normalizing to None."""
    seen = {}
    for file, fields in group:
        value = fields.get(key)
        if value is None:
            continue
        norm = normalize(value)
        if norm is not None:
            seen.setdefault(norm, []).append((file, value))
    return seen


def casefold_str(value):
    return str(value).strip().casefold()


# ---------------------------------------------------------------------------
# Reusable checks. `group` is [(file, fields), ...] for one directory.
# ---------------------------------------------------------------------------

def check_partial_numbers(lines, stats, group_dir, group, key, label):
    """Warn if only some of a group got a new `key`."""
    has_update = [key in fields for _file, fields in group]
    if not any(has_update) or all(has_update):
        return
    message = (
        f"{group_dir}: only {sum(has_update)} of {len(group)} queued "
        f"entries were given a new {label}."
    )
    warn_entry(lines, stats, message, group[0][0])


def check_number_gaps(lines, stats, group_dir, group, key, label):
    """Warn if a group's queued `key` numbers skip any."""
    nums = sorted(
        {leading_int(fields.get(key)) for _file, fields in group} - {None}
    )
    if len(nums) < 2:
        return
    missing = sorted(set(range(nums[0], nums[-1] + 1)) - set(nums))
    if not missing:
        return
    message = (
        f"{group_dir}: {label}(s) {', '.join(map(str, missing))} "
        f"missing between {nums[0]} and {nums[-1]} in the queue."
    )
    warn_entry(lines, stats, message, group[0][0])


def check_duplicates(lines, stats, group_dir, group, key, label,
                     normalize):
    """Warn about entries in a group sharing a `key` value."""
    for dupes in group_field_values(group, key, normalize).values():
        if len(dupes) < 2:
            continue
        files = [file for file, _value in dupes]
        message = (
            f"{group_dir}: {len(dupes)} entries were given the same "
            f"{label} {dupes[0][1]!r}: {', '.join(files)}."
        )
        warn_fields(lines, stats, message, [(f, key) for f in files])


def check_duplicate_titles(lines, stats, group_dir, group):
    check_duplicates(
        lines, stats, group_dir, group, "title", "title", casefold_str,
    )


def check_inconsistent(lines, stats, group_dir, group, key,
                       normalize=lambda v: str(v).strip()):
    """Warn if a group disagrees on `key`."""
    variants = group_field_values(group, key, normalize)
    if len(variants) < 2:
        return
    parts = [
        f"{value!r} ({', '.join(f for f, _v in files)})"
        for value, files in variants.items()
    ]
    message = f"{group_dir}: entries disagree on {key}: {', '.join(parts)}."
    file_keys = [(f, key) for files in variants.values() for f, _v in files]
    warn_fields(lines, stats, message, file_keys)


def check_null_and_blank_fields(lines, stats, file, fields):
    """Warn about null or whitespace-only fields."""
    for key, value in list(fields.items()):
        if value is None:
            message = f"{file}: {key} couldn't be determined (null)."
        elif isinstance(value, str) and not value.strip():
            message = f"{file}: {key} is blank."
        else:
            continue
        warn_field(lines, stats, message, file, key)


def check_is_int(lines, stats, file, fields, key, label):
    value = fields.get(key)
    if value is None or isinstance(value, int):
        return
    message = f"{file}: {label} is not an integer: {value!r}."
    warn_field(lines, stats, message, file, key)


def check_nonzero(lines, stats, file, fields, key, label):
    if fields.get(key) != 0:
        return
    message = f"{file}: {label} is 0, which usually means it's unset."
    warn_field(lines, stats, message, file, key)


def check_in_range(lines, stats, file, fields, group, key, label):
    """Warn if `key` exceeds the number of queued entries in the
    group."""
    value = fields.get(key)
    if not isinstance(value, int) or value <= len(group):
        return
    message = (
        f"{file}: {label} {value} is greater than the {len(group)} "
        f"queued entries in its folder."
    )
    warn_field(lines, stats, message, file, key)


def filename_matches(stem, number, title, parse_number, strip_number):
    """True if `stem` carries `number` or roughly `title`.
    `parse_number`/`strip_number` read a number off a stem and drop
    it."""
    if number is not None and parse_number(stem) == number:
        return True
    return bool(title) and titles_match(strip_number(stem), str(title))


def check_filename_match(lines, stats, file, fields, number_key, label,
                         parse_number, strip_number):
    """Warn if the filename matches neither the queued title nor
    `number_key`."""
    title = fields.get("title")
    number = leading_int(fields.get(number_key))
    if number is None and title is None:
        return
    if filename_matches(Path(file).stem, number, title, parse_number,
                        strip_number):
        return
    # (key, description) of each queued value the filename lacks.
    missed = [
        (key, text) for key, value, text in (
            (number_key, number, f"{label} {number}"),
            ("title", title, f"title {title!r}"),
        ) if value is not None
    ]
    message = (
        f"{file}: filename doesn't match its new "
        f"{' or '.join(text for _key, text in missed)}."
    )
    ok_lines = [find_field_line(lines, file, key) for key, _text in missed]
    resolve_warning(
        lines, stats, message, ok_lines, find_entry_line(lines, file),
    )


def check_title_number_prefix(lines, stats, file, fields, number_key,
                              parse_number):
    """Warn if the title starts with its own number, e.g. "19-2000"
    at track 19."""
    title = fields.get("title")
    number = leading_int(fields.get(number_key))
    if not title or number is None or parse_number(str(title)) != number:
        return
    message = (
        f"{file}: title still starts with its own number: {title!r}."
    )
    warn_field(lines, stats, message, file, "title")


def check_title_matches_field(lines, stats, file, fields, other_key):
    """Warn if the title nearly equals `other_key` -- likely a wrong
    match."""
    title = fields.get("title")
    other = fields.get(other_key)
    if not title or not other:
        return
    if fuzzy_ratio(str(title), str(other)) < FUZZY_SAME_ENOUGH:
        return
    message = (
        f"{file}: new title matches the {other_key} ({other!r}) almost "
        f"exactly -- possible wrong match."
    )
    warn_field(lines, stats, message, file, "title")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def group_by_parent(entries):
    """{parent dir: [(file, fields), ...]} for a loaded queue."""
    groups = {}
    for file, fields in entries.items():
        groups.setdefault(Path(file).parent, []).append((file, fields))
    return groups


def write_queue_lines(queue_file, lines):
    with open(queue_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run_checks(lines, stats, entries, check_group, check_entry):
    """`check_group(lines, stats, dir, group)` per directory, then
    `check_entry(lines, stats, file, fields, group)` per entry."""
    for group_dir, group in group_by_parent(entries).items():
        check_group(lines, stats, group_dir, group)
        for file, fields in list(group):
            check_entry(lines, stats, file, fields, group)


def open_editor(queue_file, line):
    editor = os.environ.get("EDITOR", "vi")
    line = line + 1 if line is not None else None
    subprocess.call(build_editor_command(editor, queue_file, line))


def print_check_summary(queue_file, stats):
    if stats.warnings:
        print(
            f"\n{stats.warnings} warning(s) found in {queue_file}, "
            f"{stats.resolved} resolved"
        )
    else:
        print(f"\nNo inconsistencies found in {queue_file}")


def run_check(queue_file, check_group, check_entry):
    """Check `queue_file`, re-running after each manual edit."""
    while True:
        with open(queue_file, encoding="utf-8") as f:
            raw_text = f.read()
        lines = raw_text.splitlines()
        entries = yaml.safe_load(raw_text) or {}
        stats = CheckStats()
        try:
            run_checks(lines, stats, entries, check_group, check_entry)
        except RestartCheck as restart:
            if stats.changed:
                write_queue_lines(queue_file, lines)
            open_editor(queue_file, restart.line)
            print(f"\nRe-checking {queue_file} after manual edits...\n")
            continue
        if stats.changed:
            write_queue_lines(queue_file, lines)
        print_check_summary(queue_file, stats)
        return stats
