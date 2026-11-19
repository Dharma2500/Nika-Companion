"""Local token-usage ledger used for conservative daily API limits."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nika.database import Database


@dataclass(frozen=True, slots=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0


class UsageStore:
    """Persist token counts only; never persist prompts, replies or API secrets."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self,
        *,
        provider: str,
        key_slot: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> None:
        values = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        if cached_tokens > input_tokens or reasoning_tokens > output_tokens:
            raise ValueError("Token detail counts cannot exceed their parent totals.")
        if not provider or not model or key_slot not in {"primary", "secondary", "local"}:
            raise ValueError("Usage provider metadata is invalid.")

        occurred_at = datetime.now(UTC).isoformat(timespec="seconds")
        total = input_tokens + output_tokens
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO provider_usage (
                    usage_id, occurred_at, provider, key_slot, model,
                    input_tokens, output_tokens, cached_tokens,
                    reasoning_tokens, total_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    occurred_at,
                    provider,
                    key_slot,
                    model,
                    input_tokens,
                    output_tokens,
                    cached_tokens,
                    reasoning_tokens,
                    total,
                ),
            )

    def daily_totals(self, *, day: str | None = None) -> UsageTotals:
        selected_day = day or datetime.now(UTC).date().isoformat()
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COUNT(*) AS requests
                FROM provider_usage
                WHERE substr(occurred_at, 1, 10) = ?
                """,
                (selected_day,),
            ).fetchone()
        return UsageTotals(
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cached_tokens=int(row["cached_tokens"]),
            reasoning_tokens=int(row["reasoning_tokens"]),
            total_tokens=int(row["total_tokens"]),
            requests=int(row["requests"]),
        )

    def would_exceed_daily_limit(
        self,
        *,
        daily_limit: int,
        estimated_input_tokens: int,
        max_output_tokens: int,
    ) -> bool:
        for name, value in (
            ("daily_limit", daily_limit),
            ("estimated_input_tokens", estimated_input_tokens),
            ("max_output_tokens", max_output_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        totals = self.daily_totals()
        return (
            totals.total_tokens + estimated_input_tokens + max_output_tokens
            > daily_limit
        )
