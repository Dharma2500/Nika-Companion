from pathlib import Path

import pytest

from nika.context import ContextBuilder, ContextBuildError
from nika.database import Database
from nika.memory import (
    ConversationStore,
    MemoryInput,
    MemoryStore,
    MessageInput,
)


@pytest.fixture
def stores(tmp_path: Path):
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    return MemoryStore(database), ConversationStore(database)


def test_context_contains_recent_history_and_provenance(stores) -> None:
    memories, conversations = stores
    conversation = conversations.create_conversation()
    conversations.append_message(
        conversation.conversation_id,
        MessageInput(role="user", content="Как строить ферму?", source="test"),
    )
    conversations.append_message(
        conversation.conversation_id,
        MessageInput(role="assistant", content="Начни с площадки.", source="test"),
    )
    memory = memories.add_memory(
        MemoryInput(
            category="preference",
            content="Виталий предпочитает подробные схемы механизмов.",
            source="user",
            confidence=1.0,
            provenance_type="user_taught",
        )
    )

    builder = ContextBuilder(conversations, memories)
    package = builder.build(conversation.conversation_id, "схемы механизмов")

    assert package["schema_version"] == 1
    assert [message["role"] for message in package["history"]] == [
        "user",
        "assistant",
    ]
    assert package["memories"][0]["memory_id"] == memory.memory_id
    assert package["memories"][0]["provenance_type"] == "user_taught"
    assert package["world_context"] is None


def test_context_respects_world_scope(stores) -> None:
    memories, conversations = stores
    conversation = conversations.create_conversation(world_id="world-a")
    memories.add_memory(
        MemoryInput(
            category="world_fact",
            content="База находится возле реки.",
            source="user",
            confidence=0.9,
            provenance_type="user_taught",
            scope="world",
            world_id="world-b",
        )
    )
    memories.add_memory(
        MemoryInput(
            category="general",
            content="Каменные кирпичи подходят для стен.",
            source="user",
            confidence=0.9,
        )
    )

    builder = ContextBuilder(conversations, memories)
    package = builder.build(
        conversation.conversation_id,
        "база возле реки каменные кирпичи",
        world_id="world-a",
    )
    assert [item["category"] for item in package["memories"]] == ["general"]


def test_context_drops_old_history_before_latest_message(stores) -> None:
    memories, conversations = stores
    conversation = conversations.create_conversation()
    for index in range(8):
        conversations.append_message(
            conversation.conversation_id,
            MessageInput(
                role="user",
                content=f"Сообщение {index}: " + ("текст " * 180),
                source="test",
            ),
        )

    builder = ContextBuilder(
        conversations,
        memories,
        max_context_bytes=2048,
        max_recent_messages=8,
        max_relevant_memories=0,
    )
    package = builder.build(conversation.conversation_id, "последнее сообщение")

    assert len(package["history"]) < 8
    assert "Сообщение 7" in package["history"][-1]["content"]
    assert ContextBuilder._encoded_size(package) <= 2048


def test_context_rejects_missing_conversation(stores) -> None:
    memories, conversations = stores
    builder = ContextBuilder(conversations, memories)
    with pytest.raises(ContextBuildError, match="does not exist"):
        builder.build("missing", "hello")


def test_context_configuration_is_bounded(stores) -> None:
    memories, conversations = stores
    with pytest.raises(ContextBuildError, match="max_context_bytes"):
        ContextBuilder(conversations, memories, max_context_bytes=100)
