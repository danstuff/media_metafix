"""Console output and interactive prompts."""

import shlex
import sys
from pathlib import Path

# Ways to resolve a `check` warning.
CHECK_OPTIONS = {
    "manual": "Resolve in editor",
    "skip": "Skip",
    "always_skip": "Always skip (mark with '# OK')",
}

# Editors that accept "editor +N file" to open at line N.
LINE_JUMP_EDITORS = {
    "vi", "vim", "nvim", "gvim", "mvim", "nano", "pico", "emacs"
}


def warn(msg):
    print(f"  ! {msg}", file=sys.stderr)


def note(msg):
    print(f"Note: {msg}", file=sys.stderr)


def warn_missing_file(path):
    warn(f"File not found, skipping: {path}")


def missing_package(display_name, pip_name, reason):
    note(f"{display_name} not installed (pip install {pip_name}) -- {reason}")


def past_tense(verb):
    """"convert" -> "converted", "apply" -> "applied"."""
    if verb.endswith("y"):
        return verb[:-1] + "ied"
    return verb + ("d" if verb.endswith("e") else "ed")


def outcome(verb, dry_run):
    """"converted", or "would be converted" in a dry run."""
    done = past_tense(verb)
    return f"would be {done}" if dry_run else done


def report(verb, detail, dry_run):
    """Print "Converted: x", or "Would convert: x" in a dry run."""
    if dry_run:
        print(f"Would {verb}: {detail}")
    else:
        print(f"{past_tense(verb).capitalize()}: {detail}")


def prompt_action(message):
    """Show `message` with a CHECK_OPTIONS menu; return the chosen key
    ("skip" on EOF)."""
    print(f"  ! {message}")
    keys = list(CHECK_OPTIONS)
    for i, key in enumerate(keys, 1):
        print(f"      {i}) {CHECK_OPTIONS[key]}")
    while True:
        try:
            choice = input(f"    Choice [1-{len(keys)}]: ").strip()
        except EOFError:
            print("    (no input available, leaving as-is)")
            return "skip"
        if choice.isdigit() and 1 <= int(choice) <= len(keys):
            return keys[int(choice) - 1]
        print("    Invalid choice.")


def build_editor_command(editor, path, line):
    """argv opening `path` in `editor`, at 1-indexed `line` if
    supported."""
    command = shlex.split(editor) or ["vi"]
    if line is not None and Path(command[0]).name in LINE_JUMP_EDITORS:
        command.append(f"+{line}")
    command.append(str(path))
    return command
