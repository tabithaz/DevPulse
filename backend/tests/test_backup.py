from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.backup import main
from app.github_client import RepositorySnapshot
from app.snapshot_store import SnapshotStore


def snapshot(repository: str, collected_at: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description="Backup fixture",
        default_branch="main",
        language="Python",
        stars=12,
        forks=3,
        open_issues=2,
        archived=False,
        created_at="2024-01-01T00:00:00Z",
        pushed_at="2026-10-07T12:00:00Z",
        collected_at=collected_at,
    )


def populated_store(tmp_path: Path) -> SnapshotStore:
    store = SnapshotStore(tmp_path / "devpulse.db")
    store.save_many(
        [
            snapshot("tabithaz/DevPulse", "2026-10-07T12:00:00+00:00"),
            snapshot("tabithaz/SentinelStream", "2026-10-07T12:00:00+00:00"),
        ],
        trigger="batch",
    )
    return store


def test_backup_is_complete_verified_and_readable(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    destination = tmp_path / "backups" / "devpulse.db"
    destination.parent.mkdir()

    result = store.backup(destination)

    assert asdict(result) == {
        "destination": str(destination.resolve()),
        "size_bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "repository_snapshots": 2,
        "repositories": 2,
        "collection_runs": 1,
        "integrity_check": "ok",
    }
    with sqlite3.connect(destination) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute(
            "SELECT repository FROM repository_snapshots ORDER BY repository"
        ).fetchall() == [
            ("tabithaz/DevPulse",),
            ("tabithaz/SentinelStream",),
        ]


def test_backup_rejects_unsafe_destinations(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"preserve me")

    with pytest.raises(ValueError, match="must differ"):
        store.backup(tmp_path / "devpulse.db")
    with pytest.raises(FileExistsError, match="already exists"):
        store.backup(existing)
    with pytest.raises(FileNotFoundError, match="directory does not exist"):
        store.backup(tmp_path / "missing" / "backup.db")

    assert existing.read_bytes() == b"preserve me"


def test_backup_cli_outputs_machine_readable_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = populated_store(tmp_path)
    destination = tmp_path / "backup.db"

    assert main([
        "--database",
        store.database_path,
        "--output",
        str(destination),
    ]) == 0

    manifest = json.loads(capsys.readouterr().out)
    assert manifest["destination"] == str(destination.resolve())
    assert manifest["integrity_check"] == "ok"
    assert manifest["repository_snapshots"] == 2
    assert len(manifest["sha256"]) == 64


def test_backup_overwrite_is_atomic(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    destination = tmp_path / "backup.db"
    destination.write_bytes(b"old backup")

    result = store.backup(destination, overwrite=True)

    assert result.integrity_check == "ok"
    assert destination.read_bytes() != b"old backup"
    assert list(tmp_path.glob(".backup.db.*.tmp")) == []
