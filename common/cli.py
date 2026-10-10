"""argparse helpers shared by every step."""

import argparse
from pathlib import Path

# Working files live here, relative to the current directory -- NOT
# inside root.
DEFAULT_TMP_DIR = "tmp"
DEFAULT_QUEUE_FILE = str(Path(DEFAULT_TMP_DIR) / "changes.yml")
SCANNED_ROOT_HELP = "Root folder the queue was scanned from."


def add_root_arg(subparser, help_text):
    subparser.add_argument("root", help=help_text)


def add_queue_arg(subparser, help_text):
    subparser.add_argument(
        "queue", nargs="?", default=DEFAULT_QUEUE_FILE,
        help=f"{help_text} (default: %(default)s)",
    )


def add_dir_arg(subparser, flag, default, help_text):
    """A `flag` option naming a working directory under tmp/."""
    subparser.add_argument(
        flag, default=default, help=f"{help_text} (default: %(default)s)",
    )


def add_dry_run_arg(subparser):
    subparser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without changing anything.",
    )


def add_check_parser(subparsers):
    check_p = subparsers.add_parser(
        "check", help="Sanity-check a queued changes file.",
    )
    add_queue_arg(check_p, "Queue file to check")


def build_parser(prog, doc, adders):
    """Top-level parser with one subcommand per `adders` callable."""
    parser = argparse.ArgumentParser(
        prog=prog, description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="step", required=True)
    for add in adders:
        add(subparsers)
    return parser


def run_step(parser, handlers, argv=None):
    args = parser.parse_args(argv)
    return handlers[args.step](args)


def add_convert_parser(subparsers, help_text, root_help, example):
    """`convert <root> <from> <to>`; `example` is e.g. ("wma", "mp3")."""
    convert_p = subparsers.add_parser("convert", help=help_text)
    add_root_arg(convert_p, root_help)
    convert_p.add_argument(
        "from_ext", metavar="from",
        help=f"Source extension, e.g. {example[0]}",
    )
    convert_p.add_argument(
        "to_ext", metavar="to", help=f"Target extension, e.g. {example[1]}",
    )
    add_dry_run_arg(convert_p)
