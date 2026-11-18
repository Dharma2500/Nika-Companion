from pathlib import Path

import pytest

from nika.database import Database
from nika.memory import (
    ConversationStore,
    MemoryInput,
    MemoryStore,
    MemoryValidationError,
    MessageInput,
)


@pytest.fixture
def stores(tmp_path: Path) -> tuple[MemoryStore, ConversationStore]:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    return MemoryStore(database), ConversationStore(database)


def test_memory_add_get_and_search_with_provenance(stores) -> None:
    memories, _ = stores
    record = memories.add_memory(
        MemoryInput(
            category="preference",
            content="Vitaly prefers concise explanations in Russian.",
            source="user",
            confidence=1.0,
            provenance_type="user_taught",
            tags=("language", "style"),
        )
    )

    assert memories.get_memory(record.memory_id) == record
    matches = memories.search_memories("Russian explanations", limit=3)
    assert [item.memory_id for item in matches] == [record.memory_id]
    assert matches[0].provenance_type == "user_taught"
    assert matches[0].scope == "global"
    assert matches[0].tags == ("language", "style")


def test_world_scoped_memory_is_not_returned_without_matching_world(stores) -> None:
    memories, _ = stores
    world_memory = memories.add_memory(
        MemoryInput(
            category="world_fact",
            content="The base is next to the river.",
            source="user",
            confidence=0.9,
            provenance_type="user_taught",
            scope="world",
            world_id="local-world-a",
        )
    )
    global_memory = memories.add_memory(
        MemoryInput(
            category="general",
            content="Use stone bricks for the outer wall.",
            source="user",
            confidence=0.9,
        )
    )

    assert memories.search_memories("base river", world_id="local-world-b") == []
    found = memories.search_memories("base river", world_id="local-world-a")
    assert [item.memory_id for item in found] == [world_memory.memory_id]
    assert memories.search_memories("stone bricks", world_id="local-world-b") == [
        global_memory
    ]


@pytest.mark.parametrize(
    ("memory", "message"),
    [
        (
            MemoryInput("x", "content", "user", 1.1),
            "confidence",
        ),
        (
            MemoryInput("x", "content", "user", float("nan")),
            "confidence",
        ),
        (
            MemoryInput("x", "content", "user", 0.5, provenance_type="made_up"),
            "provenance_type",
        ),
        (
            MemoryInput("x", "content", "user", 0.5, scope="world"),
            "world_id",
        ),
    ],
)
def test_memory_validation(memory, message: str, stores) -> None:
    memories, _ = stores
    with pytest.raises(MemoryValidationError, match=message):
        memories.add_memory(memory)


def test_conversation_messages_are_chronological_and_idempotent(stores) -> None:
    _, conversations = stores
    conversation = conversations.create_conversation(title="First session")
    first = conversations.append_message(
        conversation.conversation_id,
        MessageInput(role="user", content="Привет, Ника.", source="minecraft-client"),
    )
    repeated = conversations.append_message(
        conversation.conversation_id,
        MessageInput(
            role="user",
            content="Привет, Ника.",
            source="minecraft-client",
            request_id="request-001",
        ),
    )
    same_request = conversations.append_message(
        conversation.conversation_id,
        MessageInput(
            role="user",
            content="Привет, Ника.",
            source="minecraft-client",
            request_id="request-001",
        ),
    )
    second = conversations.append_message(
        conversation.conversation_id,
        MessageInput(
            role="assistant",
            content="Привет! Я рядом.",
            source="nika-core",
        ),
    )

    assert repeated.message_id == same_request.message_id
    recent = conversations.get_recent_messages(conversation.conversation_id, limit=2)
    assert [item.message_id for item in recent] == [
        repeated.message_id,
        second.message_id,
    ]
    assert recent[-1].content == "Привет! Я рядом."
    assert conversations.get_conversation(conversation.conversation_id) is not None
    assert first.role == "user"


def test_request_id_cannot_be_reused_for_different_content(stores) -> None:
    _, conversations = stores
    conversation = conversations.create_conversation()
    conversations.append_message(
        conversation.conversation_id,
        MessageInput(
            role="user",
            content="Первая фраза",
            source="minecraft-client",
            request_id="same-id",
        ),
    )
    with pytest.raises(MemoryValidationError, match="already used"):
        conversations.append_message(
            conversation.conversation_id,
            MessageInput(
                role="user",
                content="Другая фраза",
                source="minecraft-client",
                request_id="same-id",
            ),
        )


def test_message_requires_existing_conversation(stores) -> None:
    _, conversations = stores
    with pytest.raises(MemoryValidationError, match="does not exist"):
        conversations.append_message(
            "missing",
            MessageInput(role="user", content="hello", source="test"),
        )


def test_recent_message_limit_is_validated(stores) -> None:
    _, conversations = stores
    conversation = conversations.create_conversation()
    with pytest.raises(MemoryValidationError, match="limit"):
        conversations.get_recent_messages(conversation.conversation_id, limit=0)
