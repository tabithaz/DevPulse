import os
import sqlite3
from pathlib import Path

from app.github_client import RepositorySnapshot


class SnapshotStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    @classmethod
    def from_environment(cls) -> "SnapshotStore":
        return cls(os.getenv("DEVPULSE_DB_PATH", "devpulse.db"))

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

    def save(self, snapshot: RepositorySnapshot) -> None:
        with self._connect() as connection:
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

    def history(self, repository: str, limit: int = 30) -> list[RepositorySnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM repository_snapshots
                WHERE repository = ?
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                (repository, limit),
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


def snapshot_store_dependency() -> SnapshotStore:
    return SnapshotStore.from_environment()
