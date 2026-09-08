from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .source import SourceProblem


def now() -> str:
    return datetime.now(UTC).isoformat()


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS problems (
                    source_key TEXT PRIMARY KEY, source_hash TEXT NOT NULL,
                    source_file TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0, model TEXT, effort TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    started_at TEXT, completed_at TEXT, last_error TEXT,
                    artifact_path TEXT, request_id TEXT
                )
            """)

    def register(self, item: SourceProblem) -> str:
        stamp = now()
        with self.connect() as db:
            row = db.execute(
                "SELECT source_hash, status FROM problems WHERE source_key=?", (item.key,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO problems(source_key,source_hash,source_file,status,created_at,updated_at) VALUES(?,?,?,'pending',?,?)",
                    (item.key, item.source_hash, str(item.source_file), stamp, stamp),
                )
                return "pending"
            if row["source_hash"] != item.source_hash:
                db.execute(
                    """UPDATE problems SET source_hash=?, source_file=?, status='pending', attempt_count=0,
                    updated_at=?, started_at=NULL, completed_at=NULL, last_error=NULL,
                    artifact_path=NULL, request_id=NULL
                    WHERE source_key=?""",
                    (item.source_hash, str(item.source_file), stamp, item.key),
                )
                return "pending"
            return str(row["status"])

    def mark_processing(self, item: SourceProblem, model: str, effort: str) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE problems SET status='processing',
                model=?, effort=?, started_at=?, updated_at=?, last_error=NULL WHERE source_key=? AND source_hash=?""",
                (model, effort, now(), now(), item.key, item.source_hash),
            )

    def record_request_attempt(self, item: SourceProblem) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE problems SET attempt_count=attempt_count+1, updated_at=? "
                "WHERE source_key=? AND source_hash=?",
                (now(), item.key, item.source_hash),
            )

    def mark_completed(self, item: SourceProblem, artifact: Path, request_id: str | None) -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE problems SET status='completed', completed_at=?, updated_at=?,
                artifact_path=?, request_id=?, last_error=NULL WHERE source_key=? AND source_hash=?""",
                (now(), now(), str(artifact), request_id, item.key, item.source_hash),
            )

    def mark_failed(self, item: SourceProblem, error: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE problems SET status='failed', updated_at=?, last_error=? WHERE source_key=? AND source_hash=?",
                (now(), error[:8000], item.key, item.source_hash),
            )

    def mark_pending(self, item: SourceProblem, error: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE problems SET status='pending', updated_at=?, last_error=? WHERE source_key=? AND source_hash=?",
                (now(), error[:8000], item.key, item.source_hash),
            )

    def recover_processing(self) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE problems SET status='pending', updated_at=?, last_error='Interrupted during processing' WHERE status='processing'",
                (now(),),
            )
            return cursor.rowcount

    def rows(self) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM problems ORDER BY source_key"))

    def artifact_for(self, item: SourceProblem) -> Path | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT artifact_path FROM problems WHERE source_key=? AND source_hash=?",
                (item.key, item.source_hash),
            ).fetchone()
        if row is None or not row["artifact_path"]:
            return None
        return Path(row["artifact_path"])

    def reset_failed(self, source_keys: list[str]) -> int:
        if not source_keys:
            return 0
        placeholders = ",".join("?" for _ in source_keys)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE problems SET status='pending', updated_at=? "
                f"WHERE status='failed' AND source_key IN ({placeholders})",
                (now(), *source_keys),
            )
            return cursor.rowcount
