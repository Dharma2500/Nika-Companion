"""Capture explicit user-taught facts locally without calling a model.

This first learning layer handles direct remember/correction instructions and
deduplicates exact repeats. It deliberately does not infer facts from ordinary
conversation or silently promote assistant-generated text into verified memory.
Uncertain semantic inferences must be handled by a separate reviewable learning stage.
"""

from __future__ import annotations

import re
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nika.database import Database
from nika.memory import MemoryInput, MemoryStore

_EXPLICIT_MEMORY = re.compile(
    r"^\s*(?:ника[\s,:!.-]+)?(?:запомни|сохрани\s+в\s+память)"
    r"(?:\s*,?\s*что)?\s*[:,-]?\s*(.{4,6000})\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)
_CORRECTION = re.compile(
    r"^\s*(?:поправка|исправление|уточнение)\s*[:,-]\s*(.{4,6000})\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class LearningResult:
    kind: str
    reply: str
    candidate_id: str | None = None
    memory_id: str | None = None


class LearningStore:
    """Store uncertain learning signals locally for later user review."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_candidate(self, content: str, *, source: str, trigger_type: str) -> str:
        value = content.strip()
        if not 4 <= len(value) <= 6000 or "\x00" in value:
            raise ValueError("Learning candidate has an invalid length.")
        if source != "minecraft-private-chat" or trigger_type not in {
            "explicit_correction",
        }:
            raise ValueError("Learning candidate metadata is invalid.")
        candidate_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO learning_candidates (
                    candidate_id, created_at, content, source, trigger_type, status
                ) VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (candidate_id, created_at, value, source, trigger_type),
            )
        return candidate_id

    def pending_count(self) -> int:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM learning_candidates WHERE status = 'pending'"
            ).fetchone()
        return int(row[0])


class LocalLearningEngine:
    """Capture only clear user-directed learning signals without calling an API."""

    def __init__(
        self,
        memory_store: MemoryStore,
        learning_store: LearningStore,
    ) -> None:
        self.memory_store = memory_store
        self.learning_store = learning_store

    def process(self, message: str) -> LearningResult | None:
        explicit = _EXPLICIT_MEMORY.fullmatch(message)
        if explicit is not None:
            fact = explicit.group(1).strip()
            if not fact:
                return None
            category = (
                "preference"
                if re.search(
                    r"\b(предпочитаю|люблю|не люблю|нравится|не нравится|моя цель)\b",
                    fact,
                    flags=re.IGNORECASE,
                )
                else "user_fact"
            )
            existing = next(
                (
                    memory
                    for memory in self.memory_store.search_memories(fact, limit=50)
                    if memory.content.casefold() == fact.casefold()
                    and memory.provenance_type == "user_taught"
                    and memory.category == category
                ),
                None,
            )
            if existing is not None:
                return LearningResult(
                    kind="already_known",
                    reply="Это уже сохранено в моей локальной памяти. Вторую копию не создавала.",
                    memory_id=existing.memory_id,
                )
            memory = self.memory_store.add_memory(
                MemoryInput(
                    category=category,
                    content=fact,
                    source="minecraft-private-chat",
                    confidence=1.0,
                    provenance_type="user_taught",
                    scope="global",
                    tags=("explicit", "local-learning"),
                )
            )
            return LearningResult(
                kind="remembered",
                reply="Запомнила и сохранила локально. API для этого не использовался.",
                memory_id=memory.memory_id,
            )

        correction = _CORRECTION.fullmatch(message)
        if correction is not None:
            fact = correction.group(1).strip()
            existing = next(
                (
                    memory
                    for memory in self.memory_store.search_memories(fact, limit=50)
                    if memory.content.casefold() == fact.casefold()
                    and memory.provenance_type == "user_taught"
                ),
                None,
            )
            if existing is not None:
                return LearningResult(
                    kind="already_known",
                    reply="Эта поправка уже есть в локальной памяти. Повторно не записывала.",
                    memory_id=existing.memory_id,
                )
            memory = self.memory_store.add_memory(
                MemoryInput(
                    category="correction",
                    content=fact,
                    source="minecraft-private-chat",
                    confidence=1.0,
                    provenance_type="user_taught",
                    scope="global",
                    tags=("explicit-correction", "local-learning"),
                )
            )
            return LearningResult(
                kind="corrected",
                reply="Поправку приняла и сохранила локально. API для этого не использовался.",
                memory_id=memory.memory_id,
            )
        return None
