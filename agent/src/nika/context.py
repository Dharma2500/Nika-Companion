"""Deterministic, bounded context assembly for Nika dialogue."""

from __future__ import annotations

import json
from typing import Any

from nika.memory import ConversationStore, MemoryStore

CONTEXT_SCHEMA_VERSION = 1
DEFAULT_MAX_CONTEXT_BYTES = 12 * 1024
DEFAULT_RECENT_MESSAGES = 12
DEFAULT_RELEVANT_MEMORIES = 6
MAX_CONTEXT_BYTES = 64 * 1024

NIKA_PERSONALITY_CONSTITUTION = (
    "Ты Ника, локальный ИИ-компаньон Виталия. По умолчанию отвечай на русском, "
    "говори о себе в женском роде. Будь дружелюбной, спокойной, прямой и честной. "
    "Отделяй наблюдения от выводов и гипотез. Не выдумывай воспоминания, факты "
    "об игровом мире или выполненные действия. Если данных недостаточно, скажи "
    "об этом. В этой версии ты можешь вести диалог и использовать переданный "
    "контекст, но не можешь изменять мир Minecraft или выполнять команды."
)


class ContextBuildError(ValueError):
    """Raised when a conversation context cannot be assembled safely."""


class ContextBuilder:
    """Build a provider-independent context package from local memory."""

    def __init__(
        self,
        conversations: ConversationStore,
        memories: MemoryStore,
        *,
        max_context_bytes: int = DEFAULT_MAX_CONTEXT_BYTES,
        max_recent_messages: int = DEFAULT_RECENT_MESSAGES,
        max_relevant_memories: int = DEFAULT_RELEVANT_MEMORIES,
    ) -> None:
        if (
            isinstance(max_context_bytes, bool)
            or not isinstance(max_context_bytes, int)
            or not 1024 <= max_context_bytes <= MAX_CONTEXT_BYTES
        ):
            raise ContextBuildError(
                f"max_context_bytes must be between 1024 and {MAX_CONTEXT_BYTES}."
            )
        if (
            isinstance(max_recent_messages, bool)
            or not isinstance(max_recent_messages, int)
            or not 1 <= max_recent_messages <= 100
        ):
            raise ContextBuildError("max_recent_messages must be from 1 to 100.")
        if (
            isinstance(max_relevant_memories, bool)
            or not isinstance(max_relevant_memories, int)
            or not 0 <= max_relevant_memories <= 20
        ):
            raise ContextBuildError("max_relevant_memories must be from 0 to 20.")

        self.conversations = conversations
        self.memories = memories
        self.max_context_bytes = max_context_bytes
        self.max_recent_messages = max_recent_messages
        self.max_relevant_memories = max_relevant_memories

    def build(
        self,
        conversation_id: str,
        query: str,
        *,
        world_id: str | None = None,
    ) -> dict[str, Any]:
        """Assemble recent turns and relevant memories under a strict byte budget."""
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ContextBuildError("conversation_id must be a non-empty string.")
        if not isinstance(query, str) or not query.strip():
            raise ContextBuildError("query must be a non-empty string.")
        if world_id is not None and (
            not isinstance(world_id, str) or not world_id.strip()
        ):
            raise ContextBuildError("world_id must be omitted or a non-empty string.")

        conversation = self.conversations.get_conversation(conversation_id)
        if conversation is None:
            raise ContextBuildError("Conversation does not exist.")

        messages = self.conversations.get_recent_messages(
            conversation_id,
            limit=self.max_recent_messages,
        )
        memories = (
            self.memories.search_memories(
                query,
                limit=self.max_relevant_memories,
                world_id=world_id,
            )
            if self.max_relevant_memories
            else []
        )

        package: dict[str, Any] = {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "conversation_id": conversation_id,
            "world_id": world_id,
            "personality": NIKA_PERSONALITY_CONSTITUTION,
            "history": [
                {
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                }
                for message in messages
            ],
            "memories": [
                {
                    "memory_id": memory.memory_id,
                    "category": memory.category,
                    "content": memory.content[:700],
                    "provenance_type": memory.provenance_type,
                    "source": memory.source,
                    "confidence": memory.confidence,
                    "scope": memory.scope,
                    "world_id": memory.world_id,
                    "tags": list(memory.tags[:12]),
                }
                for memory in memories
            ],
            "world_context": None,
        }

        # Trim the oldest history first. The latest user turn is retained.
        while self._encoded_size(package) > self.max_context_bytes and len(
            package["history"]
        ) > 1:
            package["history"].pop(0)

        # Then remove the lowest-ranked memories until the package fits.
        while self._encoded_size(package) > self.max_context_bytes and package["memories"]:
            package["memories"].pop()

        if self._encoded_size(package) > self.max_context_bytes:
            latest = package["history"][-1] if package["history"] else None
            if latest is not None:
                latest["content"] = self._truncate_to_budget(package, latest["content"])
            if self._encoded_size(package) > self.max_context_bytes:
                raise ContextBuildError("Context cannot fit within the configured byte budget.")

        return package

    def _truncate_to_budget(self, package: dict[str, Any], content: str) -> str:
        """Find the longest UTF-8-safe prefix that keeps the package within budget."""
        low = 0
        high = len(content)
        best = ""
        original = package["history"][-1]["content"]
        try:
            while low <= high:
                middle = (low + high) // 2
                package["history"][-1]["content"] = content[:middle]
                if self._encoded_size(package) <= self.max_context_bytes:
                    best = content[:middle]
                    low = middle + 1
                else:
                    high = middle - 1
        finally:
            package["history"][-1]["content"] = original
        return best

    @staticmethod
    def _encoded_size(package: dict[str, Any]) -> int:
        return len(
            json.dumps(
                package,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
