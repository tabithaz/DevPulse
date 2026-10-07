"""Command-line entry point for verified DevPulse database backups."""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from app.snapshot_store import SnapshotStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a consistent, integrity-checked DevPulse SQLite backup."
    )
    parser.add_argument(
        "--database",
        default=os.getenv("DEVPULSE_DB_PATH", "devpulse.db"),
        help="source database (default: DEVPULSE_DB_PATH or devpulse.db)",
    )
    parser.add_argument("--output", required=True, type=Path, help="backup file path")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="atomically replace an existing backup",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SnapshotStore(args.database)
    result = store.backup(args.output, overwrite=args.overwrite)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
