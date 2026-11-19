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


def test_explicit_correction_becomes_reviewable_local_candidate(tmp_path) -> None:
    _database, engine = _engine(tmp_path)
    result = engine.process("Поправка: основной ключ должен быть первым.")

    assert result is not None
    assert result.kind == "candidate"
    assert result.candidate_id is not None
    assert engine.learning_store.pending_count() == 1


def test_ordinary_message_does_not_create_learning_record(tmp_path) -> None:
    _database, engine = _engine(tmp_path)
    assert engine.process("Привет, Ника!") is None
    assert engine.learning_store.pending_count() == 0
