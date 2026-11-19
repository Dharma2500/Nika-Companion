import pytest

from nika.database import Database
from nika.usage import UsageStore


def test_usage_store_records_token_counts_without_dialogue_content(tmp_path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    store = UsageStore(database)

    store.record(
        provider="openai",
        key_slot="secondary",
        model="gpt-4.1-mini",
        input_tokens=120,
        output_tokens=30,
        cached_tokens=40,
        reasoning_tokens=0,
    )
    totals = store.daily_totals()

    assert totals.input_tokens == 120
    assert totals.output_tokens == 30
    assert totals.cached_tokens == 40
    assert totals.total_tokens == 150
    assert totals.requests == 1

    with database.connect() as connection:
        row = connection.execute("SELECT * FROM provider_usage").fetchone()
    assert row["key_slot"] == "secondary"
    assert "prompt" not in row.keys()
    assert "content" not in row.keys()


def test_daily_budget_blocks_before_a_paid_request(tmp_path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    store = UsageStore(database)
    store.record(
        provider="openai",
        key_slot="primary",
        model="gpt-4.1-mini",
        input_tokens=700,
        output_tokens=200,
    )

    assert store.would_exceed_daily_limit(
        daily_limit=1000,
        estimated_input_tokens=50,
        max_output_tokens=100,
    )
    assert not store.would_exceed_daily_limit(
        daily_limit=2000,
        estimated_input_tokens=50,
        max_output_tokens=100,
    )


def test_usage_rejects_invalid_token_metadata(tmp_path) -> None:
    database = Database(tmp_path / "nika.sqlite3")
    database.initialize()
    store = UsageStore(database)
    with pytest.raises(ValueError):
        store.record(
            provider="openai",
            key_slot="primary",
            model="gpt-4.1-mini",
            input_tokens=-1,
            output_tokens=3,
        )
