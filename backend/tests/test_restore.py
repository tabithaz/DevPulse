import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.restore import main
from app.github_client import RepositorySnapshot
from app.snapshot_store import SnapshotStore, restore_database


def snapshot(repository: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description="Restore fixture",
        default_branch="main",
        language="Python",
        stars=12,
        forks=3,
        open_issues=2,
        archived=False,
        created_at="2024-01-01T00:00:00Z",
        pushed_at="2026-10-07T12:00:00Z",
        collected_at="2026-10-07T12:00:00+00:00",
    )


def populated_store(tmp_path: Path) -> SnapshotStore:
    store = SnapshotStore(tmp_path / "devpulse.db")
    store.save_many(
        [snapshot("tabithaz/DevPulse"), snapshot("tabithaz/SentinelStream")],
        trigger="batch",
    )
    return store


def backup_fixture(tmp_path: Path) -> Path:
    store = populated_store(tmp_path)
    backup = tmp_path / "verified-backup.db"
    store.backup(backup)
    return backup


def test_restore_recovers_a_complete_verified_database(tmp_path: Path) -> None:
    backup = backup_fixture(tmp_path)
    destination = tmp_path / "restored.db"

    result = restore_database(backup, destination)

    assert result.backup == str(backup.resolve())
    assert result.destination == str(destination.resolve())
    assert result.repository_snapshots == 2
    assert result.repositories == 2
    assert result.collection_runs == 1
    assert result.integrity_check == "ok"
    assert result.size_bytes == destination.stat().st_size
    assert result.sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    with sqlite3.connect(destination) as connection:
        assert connection.execute(
            "SELECT repository FROM repository_snapshots ORDER BY repository"
        ).fetchall() == [
            ("tabithaz/DevPulse",),
            ("tabithaz/SentinelStream",),
        ]


def test_restore_refuses_to_replace_a_database_without_overwrite(tmp_path: Path) -> None:
    backup = backup_fixture(tmp_path)
    destination = tmp_path / "live.db"
    destination.write_bytes(b"live database")

    with pytest.raises(FileExistsError, match="already exists"):
        restore_database(backup, destination)

    assert destination.read_bytes() == b"live database"


def test_restore_rejects_corrupt_and_incompatible_backups(tmp_path: Path) -> None:
    destination = tmp_path / "restored.db"
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not sqlite")

    with pytest.raises(sqlite3.DatabaseError):
        restore_database(corrupt, destination)

    incompatible = tmp_path / "incompatible.db"
    with sqlite3.connect(incompatible) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(sqlite3.DatabaseError, match="schema is missing"):
        restore_database(incompatible, destination)

    assert not destination.exists()


def test_restore_overwrite_is_atomic_and_removes_temporary_file(tmp_path: Path) -> None:
    backup = backup_fixture(tmp_path)
    destination = tmp_path / "live.db"
    destination.write_bytes(b"old database")

    restore_database(backup, destination, overwrite=True)

    assert destination.read_bytes() == backup.read_bytes()
    assert list(tmp_path.glob(".live.db.*.restore")) == []


def test_restore_cli_outputs_machine_readable_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup = backup_fixture(tmp_path)
    destination = tmp_path / "restored.db"

    assert main([
        "--backup",
        str(backup),
        "--database",
        str(destination),
    ]) == 0

    manifest = json.loads(capsys.readouterr().out)
    assert manifest["backup"] == str(backup.resolve())
    assert manifest["destination"] == str(destination.resolve())
    assert manifest["integrity_check"] == "ok"
    assert manifest["repository_snapshots"] == 2
