import json
from pathlib import Path
import sqlite3

import pytest

from app.github_client import RepositorySnapshot
from app.maintenance import main
from app.snapshot_store import SnapshotStore, maintain_database


def snapshot(repository: str, collected_at: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description="Maintenance fixture",
        default_branch="main",
        language="Python",
        stars=12,
        forks=3,
        open_issues=2,
        archived=False,
        created_at="2024-01-01T00:00:00Z",
        pushed_at="2026-10-08T12:00:00Z",
        collected_at=collected_at,
    )


def populated_database(tmp_path: Path) -> Path:
    path = tmp_path / "devpulse.db"
    store = SnapshotStore(path)
    store.save_many(
        [
            snapshot("tabithaz/DevPulse", "2026-10-08T12:00:00+00:00"),
            snapshot("tabithaz/SentinelStream", "2026-10-08T12:00:00+00:00"),
        ],
        trigger="batch",
    )
    return path


def test_maintenance_checkpoints_and_verifies_database(tmp_path: Path) -> None:
    database = populated_database(tmp_path)

    result = maintain_database(database)

    assert result.database == str(database.resolve())
    assert result.integrity_check == "ok"
    assert result.wal_busy == 0
    assert result.wal_bytes_after == 0
    assert result.vacuumed is False
    assert result.repository_snapshots == 2
    assert result.repositories == 2
    assert result.collection_runs == 1


def test_maintenance_can_compact_database(tmp_path: Path) -> None:
    database = populated_database(tmp_path)

    result = maintain_database(database, vacuum=True)

    assert result.vacuumed is True
    assert result.integrity_check == "ok"
    assert result.database_bytes_after > 0


def test_maintenance_cli_outputs_machine_readable_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = populated_database(tmp_path)

    assert main(["--database", str(database), "--busy-timeout-ms", "1000"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["database"] == str(database.resolve())
    assert result["integrity_check"] == "ok"
    assert result["wal_busy"] == 0
    assert result["repository_snapshots"] == 2


def test_maintenance_rejects_missing_corrupt_and_invalid_configuration(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="database does not exist"):
        maintain_database(tmp_path / "missing.db")

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        maintain_database(corrupt)

    database = populated_database(tmp_path)
    with pytest.raises(ValueError, match="busy_timeout_ms"):
        maintain_database(database, busy_timeout_ms=0)
