"""Typed local memory and conversation storage APIs."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nika.database import Database

PROVENANCE_TYPES = frozenset(
    {"user_taught", "observed", "verified", "inferred", "hypothesis"}
)
MEMORY_SCOPES = frozenset({"global", "world"})
MESSAGE_ROLES = frozenset({"user", "assistant", "system"})

MAX_MEMORY_CONTENT_CHARS = 6000
MAX_MEMORY_CATEGORY_CHARS = 64
MAX_MEMORY_SOURCE_CHARS = 128
MAX_MEMORY_TAGS = 24
MAX_MEMORY_TAG_CHARS = 64
MAX_WORLD_ID_CHARS = 128
MAX_MESSAGE_CHARS = 12000
MAX_USER_MESSAGE_CHARS = 4000
MAX_SOURCE_CHARS = 128
MAX_METADATA_BYTES = 4096
MAX_SEARCH_TERMS = 8
MAX_SEARCH_CANDIDATES = 512
MAX_SEARCH_LIMIT = 100
MAX_RECENT_MESSAGE_LIMIT = 100

_WORD_PATTERN = re.compile(r"[^\W_]{2,}", flags=re.UNICODE)


class MemoryValidationError(ValueError):
    """Raised when a memory or conversation record violates its contract."""


@dataclass(frozen=True, slots=True)
class MemoryInput:
    category: str
    content: str
    source: str
    confidence: float
    provenance_type: str = "hypothesis"
    scope: str = "global"
    world_id: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    created_at: str
    updated_at: str
    category: str
    content: str
    source: str
    confidence: float
    provenance_type: str
    scope: str
    world_id: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    conversation_id: str
    created_at: str
    updated_at: str
    title: str | None
    world_id: str | None


@dataclass(frozen=True, slots=True)
class MessageInput:
    role: str
    content: str
    source: str
    request_id: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    request_id: str | None
    role: str
    content: str
    created_at: str
    source: str
    metadata: dict[str, object]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _require_text(value: str, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"{name} must be a non-empty string.")
    if len(value) > maximum:
        raise MemoryValidationError(f"{name} must not exceed {maximum} characters.")
    if "\x00" in value:
        raise MemoryValidationError(f"{name} must not contain null characters.")
    return value.strip()


def _validate_world_id(world_id: str | None, scope: str) -> str | None:
    if scope == "world":
        if world_id is None:
            raise MemoryValidationError("world_id is required for world-scoped memories.")
        return _require_text(world_id, "world_id", MAX_WORLD_ID_CHARS)
    if world_id is not None:
        raise MemoryValidationError("world_id must be omitted for global memories.")
    return None


def _validate_tags(tags: Sequence[str]) -> tuple[str, ...]:
    if isinstance(tags, (str, bytes)) or not isinstance(tags, Sequence):
        raise MemoryValidationError("tags must be a sequence of strings.")
    if len(tags) > MAX_MEMORY_TAGS:
        raise MemoryValidationError(f"tags must contain at most {MAX_MEMORY_TAGS} items.")
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean = _require_text(tag, "tag", MAX_MEMORY_TAG_CHARS)
        key = clean.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(clean)
    return tuple(normalized)


def _decode_json_object(raw: str, name: str) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"Stored {name} is not a JSON object.")
    return value


class MemoryStore:
    """Validate and persist provenance-aware memories in the local database."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_memory(self, memory: MemoryInput) -> MemoryRecord:
        category = _require_text(memory.category, "category", MAX_MEMORY_CATEGORY_CHARS)
        content = _require_text(memory.content, "content", MAX_MEMORY_CONTENT_CHARS)
        source = _require_text(memory.source, "source", MAX_MEMORY_SOURCE_CHARS)

        if memory.provenance_type not in PROVENANCE_TYPES:
            raise MemoryValidationError("Unsupported memory provenance_type.")
        if memory.scope not in MEMORY_SCOPES:
            raise MemoryValidationError("Unsupported memory scope.")
        world_id = _validate_world_id(memory.world_id, memory.scope)
        tags = _validate_tags(memory.tags)

        if isinstance(memory.confidence, bool) or not isinstance(
            memory.confidence, (int, float)
        ):
            raise MemoryValidationError("confidence must be a finite number from 0 to 1.")
        confidence = float(memory.confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise MemoryValidationError("confidence must be a finite number from 0 to 1.")

        memory_id = str(uuid4())
        created_at = _now()
        tags_json = json.dumps(tags, ensure_ascii=False, separators=(",", ":"))
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    memory_id, created_at, updated_at, category, content, source,
                    confidence, provenance_type, scope, world_id, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    created_at,
                    created_at,
                    category,
                    content,
                    source,
                    confidence,
                    memory.provenance_type,
                    memory.scope,
                    world_id,
                    tags_json,
                ),
            )
        return MemoryRecord(
            memory_id=memory_id,
            created_at=created_at,
            updated_at=created_at,
            category=category,
            content=content,
            source=source,
            confidence=confidence,
            provenance_type=memory.provenance_type,
            scope=memory.scope,
            world_id=world_id,
            tags=tags,
        )

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        memory_id = _require_text(memory_id, "memory_id", 128)
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    def list_recent_memories(self, limit: int = 20) -> list[MemoryRecord]:
        limit = _bounded_limit(limit, MAX_SEARCH_LIMIT, "limit")
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC, memory_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 6,
        world_id: str | None = None,
    ) -> list[MemoryRecord]:
        query = _require_text(query, "query", MAX_MESSAGE_CHARS)
        limit = _bounded_limit(limit, MAX_SEARCH_LIMIT, "limit")
        if world_id is not None:
            world_id = _require_text(world_id, "world_id", MAX_WORLD_ID_CHARS)

        terms = list(dict.fromkeys(term.casefold() for term in _WORD_PATTERN.findall(query)))
        terms = terms[:MAX_SEARCH_TERMS]
        if not terms:
            return []

        parameters: list[object] = []
        if world_id is None:
            scope_clause = "scope = 'global'"
        else:
            scope_clause = "(scope = 'global' OR (scope = 'world' AND world_id = ?))"
            parameters.append(world_id)

        # SQLite's built-in lower() is not Unicode-aware for Cyrillic. Fetch a
        # bounded candidate set and rank with Python casefold() instead.
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM memories
                WHERE {scope_clause}
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
                """,
                (*parameters, MAX_SEARCH_CANDIDATES),
            ).fetchall()

        scored = []
        for row in rows:
            record = self._record_from_row(row)
            searchable = f"{record.content} {' '.join(record.tags)}".casefold()
            hits = sum(term in searchable for term in terms)
            if hits:
                score = hits / len(terms)
                scored.append((score, record.confidence, record.updated_at, record))
        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[3] for item in scored[:limit]]

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
        tags_value = json.loads(row["tags_json"])
        if not isinstance(tags_value, list) or not all(
            isinstance(tag, str) for tag in tags_value
        ):
            raise RuntimeError("Stored memory tags are invalid.")
        return MemoryRecord(
            memory_id=row["memory_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            category=row["category"],
            content=row["content"],
            source=row["source"],
            confidence=float(row["confidence"]),
            provenance_type=row["provenance_type"],
            scope=row["scope"],
            world_id=row["world_id"],
            tags=tuple(tags_value),
        )


class ConversationStore:
    """Persist ordered conversation messages with request-level idempotency."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_conversation(
        self,
        *,
        title: str | None = None,
        world_id: str | None = None,
        conversation_id: str | None = None,
    ) -> ConversationRecord:
        if title is not None:
            title = _require_text(title, "title", 160)
        if world_id is not None:
            world_id = _require_text(world_id, "world_id", MAX_WORLD_ID_CHARS)

        conversation_id = conversation_id or str(uuid4())
        conversation_id = _require_text(conversation_id, "conversation_id", 128)
        created_at = _now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO conversations (
                    conversation_id, created_at, updated_at, title, world_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, created_at, created_at, title, world_id),
            )
        return ConversationRecord(
            conversation_id=conversation_id,
            created_at=created_at,
            updated_at=created_at,
            title=title,
            world_id=world_id,
        )

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        conversation_id = _require_text(conversation_id, "conversation_id", 128)
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return ConversationRecord(
            conversation_id=row["conversation_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            title=row["title"],
            world_id=row["world_id"],
        )

    def append_message(
        self,
        conversation_id: str,
        message: MessageInput,
    ) -> ConversationMessage:
        conversation_id = _require_text(conversation_id, "conversation_id", 128)
        if message.role not in MESSAGE_ROLES:
            raise MemoryValidationError("role must be user, assistant or system.")
        maximum = MAX_USER_MESSAGE_CHARS if message.role == "user" else MAX_MESSAGE_CHARS
        content = _require_text(message.content, "content", maximum)
        source = _require_text(message.source, "source", MAX_SOURCE_CHARS)
        request_id = (
            _require_text(message.request_id, "request_id", 128)
            if message.request_id is not None
            else None
        )
        metadata = {} if message.metadata is None else message.metadata
        if not isinstance(metadata, dict):
            raise MemoryValidationError("metadata must be a JSON object.")
        try:
            metadata_json = json.dumps(
                metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise MemoryValidationError("metadata must contain valid JSON values.") from error
        if len(metadata_json.encode("utf-8")) > MAX_METADATA_BYTES:
            raise MemoryValidationError("metadata exceeds the 4 KiB limit.")

        message_id = str(uuid4())
        created_at = _now()
        with self.database.transaction() as connection:
            conversation = connection.execute(
                "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise MemoryValidationError("Conversation does not exist.")

            if request_id is not None:
                existing = connection.execute(
                    "SELECT * FROM conversation_messages WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    existing_record = self._message_from_row(existing)
                    if (
                        existing_record.conversation_id != conversation_id
                        or existing_record.role != message.role
                        or existing_record.content != content
                        or existing_record.source != source
                    ):
                        raise MemoryValidationError(
                            "request_id was already used for a different message."
                        )
                    return existing_record

            connection.execute(
                """
                INSERT INTO conversation_messages (
                    message_id, conversation_id, request_id, role, content,
                    created_at, source, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    request_id,
                    message.role,
                    content,
                    created_at,
                    source,
                    metadata_json,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (created_at, conversation_id),
            )

        return ConversationMessage(
            message_id=message_id,
            conversation_id=conversation_id,
            request_id=request_id,
            role=message.role,
            content=content,
            created_at=created_at,
            source=source,
            metadata=metadata,
        )

    def get_recent_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 12,
    ) -> list[ConversationMessage]:
        conversation_id = _require_text(conversation_id, "conversation_id", 128)
        limit = _bounded_limit(limit, MAX_RECENT_MESSAGE_LIMIT, "limit")
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in reversed(rows)]

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> ConversationMessage:
        return ConversationMessage(
            message_id=row["message_id"],
            conversation_id=row["conversation_id"],
            request_id=row["request_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            source=row["source"],
            metadata=_decode_json_object(row["metadata_json"], "message metadata"),
        )


def _bounded_limit(value: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise MemoryValidationError(f"{name} must be an integer from 1 to {maximum}.")
    return value
