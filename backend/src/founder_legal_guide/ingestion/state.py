"""What is in the Corpus (which version of each Source, per language, with per-section
fingerprints) and the Change Records that explain how it got there (CONTEXT.md)."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

import psycopg

ChangeStatus = Literal["applied", "review_needed", "approved", "rejected"]


@dataclass
class SourceVersion:
    version: str
    ingested_at: datetime
    section_hashes: dict[str, str] = field(default_factory=dict)


@dataclass
class ChangeRecord:
    source_id: str
    language: str
    kind: Literal["added", "changed"]
    status: ChangeStatus
    old_version: str | None
    new_version: str
    summary: dict  # {"added": [...labels], "removed": [...], "modified": [...]}
    pending: dict | None = None  # the fetched document, kept until a review decision
    id: int | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None

    def public(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "language": self.language,
            "kind": self.kind,
            "status": self.status,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "summary": self.summary,
            "detected_at": self.detected_at.isoformat(),
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


class CorpusState(Protocol):
    def record(
        self,
        source_id: str,
        language: str,
        version: str,
        section_hashes: dict[str, str] | None = None,
    ) -> None: ...
    def versions(self, source_id: str) -> dict[str, tuple[str, datetime]]: ...
    def current(self, source_id: str, language: str) -> SourceVersion | None: ...
    def add_change(self, change: ChangeRecord) -> int: ...
    def changes(
        self, limit: int = 50, status: ChangeStatus | None = None
    ) -> list[ChangeRecord]: ...
    def change(self, change_id: int) -> ChangeRecord | None: ...
    def decide(self, change_id: int, status: ChangeStatus) -> None: ...
    def indexed_sources(self) -> set[str]: ...


# Kept for code that only needs versions (the live source check).
SourceVersionStore = CorpusState


class MemoryVersionStore:
    """In-process CorpusState for tests and demo mode."""

    def __init__(self):
        self._versions: dict[tuple[str, str], SourceVersion] = {}
        self._changes: list[ChangeRecord] = []

    def record(self, source_id, language, version, section_hashes=None) -> None:
        self._versions[(source_id, language)] = SourceVersion(
            version, datetime.now(UTC), dict(section_hashes or {})
        )

    def versions(self, source_id):
        return {
            lang: (v.version, v.ingested_at)
            for (sid, lang), v in self._versions.items()
            if sid == source_id
        }

    def current(self, source_id, language):
        return self._versions.get((source_id, language))

    def add_change(self, change: ChangeRecord) -> int:
        change.id = len(self._changes) + 1
        self._changes.append(change)
        return change.id

    def indexed_sources(self) -> set[str]:
        return {sid for sid, _ in self._versions}

    def changes(self, limit=50, status=None):
        rows = [c for c in reversed(self._changes) if status is None or c.status == status]
        return rows[:limit]

    def change(self, change_id):
        return next((c for c in self._changes if c.id == change_id), None)

    def decide(self, change_id, status) -> None:
        change = self.change(change_id)
        if change:
            change.status, change.decided_at, change.pending = status, datetime.now(UTC), None


class PostgresVersionStore:
    def __init__(self, database_url: str):
        self._url = database_url
        self._ready = False

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self._url, autocommit=True)
        if not self._ready:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_versions (
                    source_id text NOT NULL,
                    language text NOT NULL,
                    version text NOT NULL,
                    ingested_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (source_id, language)
                )
                """
            )
            conn.execute(
                "ALTER TABLE source_versions ADD COLUMN IF NOT EXISTS section_hashes jsonb NOT NULL DEFAULT '{}'"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS change_records (
                    id serial PRIMARY KEY,
                    source_id text NOT NULL,
                    language text NOT NULL,
                    kind text NOT NULL,
                    status text NOT NULL,
                    old_version text,
                    new_version text NOT NULL,
                    summary jsonb NOT NULL,
                    pending jsonb,
                    detected_at timestamptz NOT NULL DEFAULT now(),
                    decided_at timestamptz
                )
                """
            )
            self._ready = True
        return conn

    def record(self, source_id, language, version, section_hashes=None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_versions (source_id, language, version, section_hashes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_id, language) DO UPDATE SET
                    version = EXCLUDED.version, section_hashes = EXCLUDED.section_hashes, ingested_at = now()
                """,
                (source_id, language, version, json.dumps(section_hashes or {})),
            )

    def versions(self, source_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT language, version, ingested_at FROM source_versions WHERE source_id = %s",
                (source_id,),
            ).fetchall()
        return {lang: (version, at) for lang, version, at in rows}

    def indexed_sources(self) -> set[str]:
        with self._connect() as conn:
            return {
                sid for (sid,) in conn.execute("SELECT DISTINCT source_id FROM source_versions")
            }

    def current(self, source_id, language):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT version, ingested_at, section_hashes FROM source_versions WHERE source_id = %s AND language = %s",
                (source_id, language),
            ).fetchone()
        return SourceVersion(row[0], row[1], row[2] or {}) if row else None

    def add_change(self, change: ChangeRecord) -> int:
        with self._connect() as conn:
            (change_id,) = conn.execute(
                """
                INSERT INTO change_records
                    (source_id, language, kind, status, old_version, new_version, summary, pending, detected_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    change.source_id,
                    change.language,
                    change.kind,
                    change.status,
                    change.old_version,
                    change.new_version,
                    json.dumps(change.summary),
                    json.dumps(change.pending) if change.pending is not None else None,
                    change.detected_at,
                ),
            ).fetchone()
        change.id = change_id
        return change_id

    def changes(self, limit=50, status=None):
        query = (
            "SELECT * FROM change_records"
            + (" WHERE status = %s" if status else "")
            + " ORDER BY id DESC LIMIT %s"
        )
        with self._connect() as conn:
            cur = conn.execute(query, (status, limit) if status else (limit,))
            names = [d.name for d in cur.description]
            return [_change_from_row(dict(zip(names, row, strict=True))) for row in cur.fetchall()]

    def change(self, change_id):
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM change_records WHERE id = %s", (change_id,))
            row = cur.fetchone()
            names = [d.name for d in cur.description]
        return _change_from_row(dict(zip(names, row, strict=True))) if row else None

    def decide(self, change_id, status) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE change_records SET status = %s, decided_at = now(), pending = NULL WHERE id = %s",
                (status, change_id),
            )


def _change_from_row(row: dict) -> ChangeRecord:
    return ChangeRecord(
        id=row["id"],
        source_id=row["source_id"],
        language=row["language"],
        kind=row["kind"],
        status=row["status"],
        old_version=row["old_version"],
        new_version=row["new_version"],
        summary=row["summary"],
        pending=row["pending"],
        detected_at=row["detected_at"],
        decided_at=row["decided_at"],
    )
