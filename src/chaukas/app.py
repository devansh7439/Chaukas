"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chaukas import __version__
from chaukas.core.config import load_config
from chaukas.core.errors import ConfigError

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaukas",
        description="On-device AI guardian against social engineering.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser(
        "check-config", help="validate the configuration and print the merged result"
    )
    check.add_argument(
        "--config",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="YAML override applied on top of the defaults (repeatable, applied in order)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check-config":
        return _check_config(args.config)
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


def _check_config(paths: list[Path]) -> int:
    try:
        config = load_config(*paths)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print(config.model_dump_json(indent=2))
    return EXIT_OK
