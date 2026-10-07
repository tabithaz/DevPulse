"""Command-line entry point for guarded DevPulse database restores."""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from app.snapshot_store import restore_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and atomically restore a DevPulse SQLite backup."
    )
    parser.add_argument("--backup", required=True, type=Path, help="backup file path")
    parser.add_argument(
        "--database",
        default=os.getenv("DEVPULSE_DB_PATH", "devpulse.db"),
        type=Path,
        help="restore destination (default: DEVPULSE_DB_PATH or devpulse.db)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="atomically replace an existing database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = restore_database(args.backup, args.database, overwrite=args.overwrite)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
