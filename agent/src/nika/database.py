"""SQLite persistence with explicit schema versioning and safe transactions."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

SCHEMA_VERSION = 2

_MIGRATION_1 = (
    """CREATE TABLE event_log (
        event_id TEXT PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        event_type TEXT NOT NULL,
        source TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""",
    "CREATE INDEX idx_event_log_occurred_at ON event_log (occurred_at)",
    """CREATE TABLE memories (
        memory_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        source TEXT NOT NULL,
        confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0)
    )""",
    "CREATE INDEX idx_memories_category ON memories (category)",
    """CREATE TABLE skills (
        skill_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        definition_json TEXT NOT NULL,
        source TEXT NOT NULL,
        confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
        UNIQUE (name, version)
    )""",
    """CREATE TABLE world_facts (
        fact_id TEXT PRIMARY KEY,
        world_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        fact_type TEXT NOT NULL,
        value_json TEXT NOT NULL,
        source TEXT NOT NULL,
        confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0)
    )""",
    "CREATE INDEX idx_world_facts_world ON world_facts (world_id, observed_at)",
)

_MIGRATION_2 = (
    """ALTER TABLE memories ADD COLUMN provenance_type TEXT NOT NULL
        DEFAULT 'user_taught'
        CHECK (provenance_type IN (
            'user_taught', 'observed', 'verified', 'inferred', 'hypothesis'
        ))""",
    """ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'
        CHECK (scope IN ('global', 'world'))""",
    "ALTER TABLE memories ADD COLUMN world_id TEXT",
    "ALTER TABLE memories ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'",
    "CREATE INDEX idx_memories_scope_world ON memories (scope, world_id)",
    """CREATE TABLE conversations (
        conversation_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        title TEXT,
        world_id TEXT
    )""",
    "CREATE INDEX idx_conversations_updated_at ON conversations (updated_at)",
    """CREATE TABLE conversation_messages (
        message_id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations (conversation_id)
            ON DELETE CASCADE,
        request_id TEXT UNIQUE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
        content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 12000),
        created_at TEXT NOT NULL,
        source TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE INDEX idx_conversation_messages_timeline
        ON conversation_messages (conversation_id, created_at, message_id)""",
)


class Database:
    """Owns the local SQLite database and its schema migrations."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        """Open a connection configured for concurrent local readers and writers."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run an atomic write transaction and always close its connection."""
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create or migrate the database; refuse unknown future schema versions."""
        with self.transaction() as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {current_version} is newer than supported "
                    f"schema {SCHEMA_VERSION}; refusing to modify it."
                )

            if current_version < 1:
                for statement in _MIGRATION_1:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                current_version = 1

            if current_version < 2:
                for statement in _MIGRATION_2:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 2")

    def health_check(self) -> bool:
        """Return whether SQLite can execute a basic integrity query."""
        with closing(self.connect()) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
            return result is not None and result[0] == "ok"
