"""Command-line entry point for DevPulse SQLite maintenance."""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from app.snapshot_store import maintain_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Checkpoint, optimize, and verify the DevPulse SQLite database."
    )
    parser.add_argument(
        "--database",
        default=os.getenv("DEVPULSE_DB_PATH", "devpulse.db"),
        type=Path,
        help="database path (default: DEVPULSE_DB_PATH or devpulse.db)",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="compact the database; run only while the API is stopped",
    )
    parser.add_argument(
        "--busy-timeout-ms",
        default=5000,
        type=int,
        help="maximum lock wait in milliseconds (default: 5000)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = maintain_database(
        args.database,
        vacuum=args.vacuum,
        busy_timeout_ms=args.busy_timeout_ms,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
