from nika.database import Database
from nika.learning import LearningStore, LocalLearningEngine
from nika.memory import MemoryStore


def _engine(tmp_path):
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    return database, LocalLearningEngine(
        MemoryStore(database),
        LearningStore(database),
    )


def test_explicit_remember_is_saved_locally_as_user_taught(tmp_path) -> None:
    database, engine = _engine(tmp_path)
    result = engine.process("Ника, запомни: я предпочитаю короткие ответы.")

    assert result is not None
    assert result.kind == "remembered"
    assert result.memory_id is not None
    memory = MemoryStore(database).get_memory(result.memory_id)
    assert memory is not None
    assert memory.content == "я предпочитаю короткие ответы."
    assert memory.provenance_type == "user_taught"
    assert memory.confidence == 1.0


def test_explicit_correction_is_saved_as_confirmed_local_knowledge(tmp_path) -> None:
    database, engine = _engine(tmp_path)
    result = engine.process("Поправка: основной ключ должен быть первым.")

    assert result is not None
    assert result.kind == "corrected"
    assert result.memory_id is not None
    memory = MemoryStore(database).get_memory(result.memory_id)
    assert memory is not None
    assert memory.category == "correction"
    assert memory.provenance_type == "user_taught"
    assert memory.confidence == 1.0
    assert engine.learning_store.pending_count() == 0


def test_repeated_explicit_correction_is_not_duplicated(tmp_path) -> None:
    database, engine = _engine(tmp_path)
    first = engine.process("Поправка: основной ключ должен быть первым.")
    second = engine.process("Поправка: основной ключ должен быть первым.")

    assert first is not None and first.kind == "corrected"
    assert second is not None and second.kind == "already_known"
    assert second.memory_id == first.memory_id
    assert len(MemoryStore(database).list_recent_memories()) == 1


def test_repeated_explicit_remember_is_not_duplicated(tmp_path) -> None:
    database, engine = _engine(tmp_path)
    first = engine.process("Ника, запомни: я предпочитаю короткие ответы.")
    second = engine.process("Ника, запомни: я предпочитаю короткие ответы.")

    assert first is not None and first.kind == "remembered"
    assert second is not None and second.kind == "already_known"
    assert second.memory_id == first.memory_id
    assert len(MemoryStore(database).list_recent_memories()) == 1


def test_ordinary_message_does_not_create_learning_record(tmp_path) -> None:
    _database, engine = _engine(tmp_path)
    assert engine.process("Привет, Ника!") is None
    assert engine.learning_store.pending_count() == 0
