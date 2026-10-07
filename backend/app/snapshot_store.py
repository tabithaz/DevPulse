import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
import hashlib
from pathlib import Path
from uuid import uuid4

from app.github_client import RepositorySnapshot


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for a different request."""


@dataclass(frozen=True)
class BackupResult:
    destination: str
    size_bytes: int
    sha256: str
    repository_snapshots: int
    repositories: int
    collection_runs: int
    integrity_check: str


@dataclass(frozen=True)
class RestoreResult:
    backup: str
    destination: str
    size_bytes: int
    sha256: str
    repository_snapshots: int
    repositories: int
    collection_runs: int
    integrity_check: str


REQUIRED_SCHEMA = {
    "repository_snapshots": {
        "repository",
        "description",
        "default_branch",
        "language",
        "stars",
        "forks",
        "open_issues",
        "archived",
        "created_at",
        "pushed_at",
        "collected_at",
    },
    "idempotency_requests": {
        "idempotency_key",
        "request_fingerprint",
        "response_json",
        "created_at",
    },
    "collection_runs": {
        "id",
        "trigger",
        "repository_count",
        "repositories_json",
        "recorded_at",
    },
}


def _database_manifest(path: Path) -> dict:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"database integrity check failed: {integrity}")
        for table, required_columns in REQUIRED_SCHEMA.items():
            columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            missing = sorted(required_columns - columns)
            if missing:
                raise sqlite3.DatabaseError(
                    f"backup schema is missing {table} columns: {', '.join(missing)}"
                )
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM repository_snapshots"
        ).fetchone()[0]
        repository_count = connection.execute(
            "SELECT COUNT(DISTINCT repository) FROM repository_snapshots"
        ).fetchone()[0]
        run_count = connection.execute(
            "SELECT COUNT(*) FROM collection_runs"
        ).fetchone()[0]
    with path.open("rb") as database_file:
        checksum = hashlib.file_digest(database_file, "sha256").hexdigest()
    return {
        "size_bytes": path.stat().st_size,
        "sha256": checksum,
        "repository_snapshots": snapshot_count,
        "repositories": repository_count,
        "collection_runs": run_count,
        "integrity_check": integrity,
    }


def restore_database(
    backup: str | Path,
    destination: str | Path,
    overwrite: bool = False,
) -> RestoreResult:
    """Validate and atomically restore a DevPulse database backup."""
    backup_path = Path(backup).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not backup_path.is_file():
        raise FileNotFoundError(f"backup does not exist: {backup_path}")
    if backup_path == destination_path:
        raise ValueError("restore destination must differ from the backup")
    if not destination_path.parent.is_dir():
        raise FileNotFoundError(
            f"restore directory does not exist: {destination_path.parent}"
        )
    if destination_path.exists() and not overwrite:
        raise FileExistsError(f"restore destination already exists: {destination_path}")

    source_manifest = _database_manifest(backup_path)
    temporary_path = destination_path.with_name(
        f".{destination_path.name}.{uuid4().hex}.restore"
    )
    try:
        shutil.copyfile(backup_path, temporary_path)
        restored_manifest = _database_manifest(temporary_path)
        if restored_manifest != source_manifest:
            raise sqlite3.DatabaseError("restored database does not match backup manifest")
        os.replace(temporary_path, destination_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return RestoreResult(
        backup=str(backup_path),
        destination=str(destination_path),
        **restored_manifest,
    )


class SnapshotStore:
    def __init__(
        self,
        database_path: str | Path,
        retention_per_repository: int = 365,
        collection_run_retention: int = 1000,
    ) -> None:
        if retention_per_repository <= 0:
            raise ValueError("retention_per_repository must be greater than zero")
        if collection_run_retention <= 0:
            raise ValueError("collection_run_retention must be greater than zero")
        self.database_path = str(database_path)
        self.retention_per_repository = retention_per_repository
        self.collection_run_retention = collection_run_retention
        self._initialize()

    @classmethod
    def from_environment(cls) -> "SnapshotStore":
        retention_value = os.getenv("DEVPULSE_SNAPSHOT_RETENTION", "365")
        try:
            retention = int(retention_value)
        except ValueError as error:
            raise ValueError(
                "DEVPULSE_SNAPSHOT_RETENTION must be a positive integer"
            ) from error
        if retention <= 0:
            raise ValueError("DEVPULSE_SNAPSHOT_RETENTION must be a positive integer")
        return cls(
            os.getenv("DEVPULSE_DB_PATH", "devpulse.db"),
            retention_per_repository=retention,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS repository_snapshots (
                    repository TEXT NOT NULL,
                    description TEXT,
                    default_branch TEXT NOT NULL,
                    language TEXT,
                    stars INTEGER NOT NULL,
                    forks INTEGER NOT NULL,
                    open_issues INTEGER NOT NULL,
                    archived INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    pushed_at TEXT,
                    collected_at TEXT NOT NULL,
                    PRIMARY KEY (repository, collected_at)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_requests (
                    idempotency_key TEXT PRIMARY KEY,
                    request_fingerprint TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger TEXT NOT NULL,
                    repository_count INTEGER NOT NULL,
                    repositories_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save(self, snapshot: RepositorySnapshot, trigger: str = "api") -> None:
        self.save_many([snapshot], trigger=trigger)

    def save_many(
        self,
        snapshots: list[RepositorySnapshot],
        trigger: str = "batch",
    ) -> None:
        """Persist and prune a snapshot batch in one transaction."""
        if not snapshots:
            raise ValueError("snapshots must not be empty")
        with self._connect() as connection:
            for snapshot in snapshots:
                connection.execute(
                    """
                    INSERT INTO repository_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.repository,
                        snapshot.description,
                        snapshot.default_branch,
                        snapshot.language,
                        snapshot.stars,
                        snapshot.forks,
                        snapshot.open_issues,
                        snapshot.archived,
                        snapshot.created_at,
                        snapshot.pushed_at,
                        snapshot.collected_at,
                    ),
                )
            for repository in {snapshot.repository for snapshot in snapshots}:
                connection.execute(
                    """
                    DELETE FROM repository_snapshots
                    WHERE repository = ?
                      AND rowid NOT IN (
                          SELECT rowid
                          FROM repository_snapshots
                          WHERE repository = ?
                          ORDER BY collected_at DESC
                          LIMIT ?
                      )
                    """,
                    (repository, repository, self.retention_per_repository),
                )
            self._record_collection_run(connection, snapshots, trigger)

    def idempotency_result(
        self,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict | None:
        """Return a stored response, rejecting keys bound to another request."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT request_fingerprint, response_json
                FROM idempotency_requests
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if row["request_fingerprint"] != request_fingerprint:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different request"
            )
        return json.loads(row["response_json"])

    def save_many_once(
        self,
        snapshots: list[RepositorySnapshot],
        idempotency_key: str,
        request_fingerprint: str,
        response: dict,
        trigger: str = "api",
    ) -> tuple[dict, bool]:
        """Atomically save snapshots and their replayable collection response."""
        if not snapshots:
            raise ValueError("snapshots must not be empty")
        encoded = json.dumps(response, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT request_fingerprint, response_json
                FROM idempotency_requests
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                if row["request_fingerprint"] != request_fingerprint:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different request"
                    )
                return json.loads(row["response_json"]), True

            for snapshot in snapshots:
                connection.execute(
                    """
                    INSERT INTO repository_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.repository,
                        snapshot.description,
                        snapshot.default_branch,
                        snapshot.language,
                        snapshot.stars,
                        snapshot.forks,
                        snapshot.open_issues,
                        snapshot.archived,
                        snapshot.created_at,
                        snapshot.pushed_at,
                        snapshot.collected_at,
                    ),
                )
            for repository in {snapshot.repository for snapshot in snapshots}:
                connection.execute(
                    """
                    DELETE FROM repository_snapshots
                    WHERE repository = ?
                      AND rowid NOT IN (
                          SELECT rowid FROM repository_snapshots
                          WHERE repository = ?
                          ORDER BY collected_at DESC LIMIT ?
                      )
                    """,
                    (repository, repository, self.retention_per_repository),
                )
            connection.execute(
                """
                INSERT INTO idempotency_requests (
                    idempotency_key, request_fingerprint, response_json
                ) VALUES (?, ?, ?)
                """,
                (idempotency_key, request_fingerprint, encoded),
            )
            connection.execute(
                """
                DELETE FROM idempotency_requests
                WHERE rowid NOT IN (
                    SELECT rowid FROM idempotency_requests
                    ORDER BY rowid DESC LIMIT 1000
                )
                """
            )
            self._record_collection_run(connection, snapshots, trigger)
        return response, False

    def _record_collection_run(
        self,
        connection: sqlite3.Connection,
        snapshots: list[RepositorySnapshot],
        trigger: str,
    ) -> None:
        if trigger not in {"api", "batch", "webhook"}:
            raise ValueError("trigger must be api, batch, or webhook")
        repositories = sorted({snapshot.repository for snapshot in snapshots})
        connection.execute(
            """
            INSERT INTO collection_runs (trigger, repository_count, repositories_json)
            VALUES (?, ?, ?)
            """,
            (trigger, len(repositories), json.dumps(repositories, separators=(",", ":"))),
        )
        connection.execute(
            """
            DELETE FROM collection_runs
            WHERE id NOT IN (
                SELECT id FROM collection_runs ORDER BY id DESC LIMIT ?
            )
            """,
            (self.collection_run_retention,),
        )

    def collection_runs(self, limit: int = 50) -> list[dict]:
        """Return the newest successful collection runs."""
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, trigger, repository_count, repositories_json, recorded_at
                FROM collection_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["id"],
                "trigger": row["trigger"],
                "repository_count": row["repository_count"],
                "repositories": json.loads(row["repositories_json"]),
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]

    def check_connection(self) -> None:
        """Raise when the configured SQLite database cannot serve queries."""
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def backup(self, destination: str | Path, overwrite: bool = False) -> BackupResult:
        """Create and verify an atomic online backup of the snapshot database."""
        if self.database_path == ":memory:":
            raise ValueError("in-memory databases cannot be backed up by path")

        destination_path = Path(destination).expanduser().resolve()
        source_path = Path(self.database_path).expanduser().resolve()
        if destination_path == source_path:
            raise ValueError("backup destination must differ from the source database")
        if not destination_path.parent.is_dir():
            raise FileNotFoundError(
                f"backup directory does not exist: {destination_path.parent}"
            )
        if destination_path.exists() and not overwrite:
            raise FileExistsError(f"backup already exists: {destination_path}")

        temporary_path = destination_path.with_name(
            f".{destination_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with self._connect() as source, sqlite3.connect(temporary_path) as target:
                source.backup(target)
                integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
                snapshot_count = target.execute(
                    "SELECT COUNT(*) FROM repository_snapshots"
                ).fetchone()[0]
                repository_count = target.execute(
                    "SELECT COUNT(DISTINCT repository) FROM repository_snapshots"
                ).fetchone()[0]
                run_count = target.execute(
                    "SELECT COUNT(*) FROM collection_runs"
                ).fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(
                    f"backup integrity check failed: {integrity}"
                )

            with temporary_path.open("rb") as backup_file:
                checksum = hashlib.file_digest(backup_file, "sha256").hexdigest()
            size_bytes = temporary_path.stat().st_size
            os.replace(temporary_path, destination_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        return BackupResult(
            destination=str(destination_path),
            size_bytes=size_bytes,
            sha256=checksum,
            repository_snapshots=snapshot_count,
            repositories=repository_count,
            collection_runs=run_count,
            integrity_check=integrity,
        )

    def history(self, repository: str, limit: int = 30) -> list[RepositorySnapshot]:
        return self.history_before(repository, limit=limit)

    def history_before(
        self,
        repository: str,
        limit: int = 30,
        before: str | None = None,
    ) -> list[RepositorySnapshot]:
        """Return newest snapshots strictly before an optional keyset boundary."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM repository_snapshots
                WHERE repository = ?
                  AND (? IS NULL OR collected_at < ?)
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                (repository, before, before, limit),
            ).fetchall()
        return [
            RepositorySnapshot(
                repository=row["repository"],
                description=row["description"],
                default_branch=row["default_branch"],
                language=row["language"],
                stars=row["stars"],
                forks=row["forks"],
                open_issues=row["open_issues"],
                archived=bool(row["archived"]),
                created_at=row["created_at"],
                pushed_at=row["pushed_at"],
                collected_at=row["collected_at"],
            )
            for row in rows
        ]

    def latest(self) -> list[RepositorySnapshot]:
        """Return the newest snapshot for every tracked repository."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshots.*
                FROM repository_snapshots AS snapshots
                JOIN (
                    SELECT repository, MAX(collected_at) AS collected_at
                    FROM repository_snapshots
                    GROUP BY repository
                ) AS latest
                  ON snapshots.repository = latest.repository
                 AND snapshots.collected_at = latest.collected_at
                ORDER BY snapshots.repository COLLATE NOCASE
                """
            ).fetchall()
        return [
            RepositorySnapshot(
                repository=row["repository"],
                description=row["description"],
                default_branch=row["default_branch"],
                language=row["language"],
                stars=row["stars"],
                forks=row["forks"],
                open_issues=row["open_issues"],
                archived=bool(row["archived"]),
                created_at=row["created_at"],
                pushed_at=row["pushed_at"],
                collected_at=row["collected_at"],
            )
            for row in rows
        ]

    def latest_history(self, limit_per_repository: int = 2) -> dict[str, list[RepositorySnapshot]]:
        """Return bounded recent history for every repository in one query."""
        if limit_per_repository <= 0:
            raise ValueError("limit_per_repository must be greater than zero")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY repository ORDER BY collected_at DESC
                    ) AS snapshot_rank
                    FROM repository_snapshots
                )
                SELECT * FROM ranked
                WHERE snapshot_rank <= ?
                ORDER BY repository COLLATE NOCASE, collected_at DESC
                """,
                (limit_per_repository,),
            ).fetchall()

        histories: dict[str, list[RepositorySnapshot]] = {}
        for row in rows:
            histories.setdefault(row["repository"], []).append(
                RepositorySnapshot(
                    repository=row["repository"],
                    description=row["description"],
                    default_branch=row["default_branch"],
                    language=row["language"],
                    stars=row["stars"],
                    forks=row["forks"],
                    open_issues=row["open_issues"],
                    archived=bool(row["archived"]),
                    created_at=row["created_at"],
                    pushed_at=row["pushed_at"],
                    collected_at=row["collected_at"],
                )
            )
        return histories


def snapshot_store_dependency() -> SnapshotStore:
    return SnapshotStore.from_environment()
