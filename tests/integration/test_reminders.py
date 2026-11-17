"""Reminder delivery: due tasks fire exactly once, repeats roll forward.

The bug this replaces was quiet: ``remind`` wrote a due time, nothing ever read it,
and the agent still said "I'll remind you at 9". A reminder system that never
reminds is worse than none, because the operator stops watching for it.

These run against the real database layer (temporary SQLite), and call ``deliver``
with an explicit clock so nothing depends on sleeping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from apps.api.db import session as db_session
from apps.api.db.models import Task, TaskEvent, User
from apps.api.services.reminders import (
    acknowledge,
    deliver,
    next_occurrence,
    recent,
)


async def _user() -> str:
    async with db_session.session_scope() as session:
        user = User(email="reminders@localhost")
        session.add(user)
        await session.flush()
        return user.id


async def _task(user_id: str, *, due: datetime, recurrence: str | None = None) -> str:
    async with db_session.session_scope() as session:
        task = Task(user_id=user_id, title="call the dentist", due_at=due, recurrence=recurrence)
        session.add(task)
        await session.flush()
        return task.id


@pytest.mark.asyncio
async def test_a_due_task_fires_once_and_only_once(db: dict[str, str]) -> None:
    user_id = await _user()
    due = datetime.now(UTC) - timedelta(minutes=1)
    await _task(user_id, due=due)

    assert await deliver() == 1
    # A second poll of the same minute, and a third after a restart, must not repeat.
    assert await deliver() == 0
    assert await deliver(now=datetime.now(UTC) + timedelta(hours=1)) == 0

    items = await recent()
    assert len(items) == 1
    assert items[0]["title"] == "call the dentist"
    assert items[0]["status"] == "open"


@pytest.mark.asyncio
async def test_a_future_task_does_not_fire(db: dict[str, str]) -> None:
    user_id = await _user()
    await _task(user_id, due=datetime.now(UTC) + timedelta(hours=2))
    assert await deliver() == 0
    assert await recent() == []


@pytest.mark.asyncio
async def test_a_repeating_task_rolls_forward_instead_of_cloning(db: dict[str, str]) -> None:
    user_id = await _user()
    first = datetime.now(UTC) - timedelta(minutes=5)
    task_id = await _task(user_id, due=first, recurrence="FREQ=DAILY;INTERVAL=1")

    assert await deliver() == 1
    async with db_session.session_scope() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        moved = task.due_at.replace(tzinfo=UTC) if task.due_at.tzinfo is None else task.due_at
        assert moved > first + timedelta(hours=23)
        # Same row, still open: a daily habit is not a growing pile of history.
        assert task.status == "open"
        count = (await session.scalars(select(Task).where(Task.user_id == user_id))).all()
        assert len(count) == 1


@pytest.mark.asyncio
async def test_an_unreadable_recurrence_is_reported_not_guessed(db: dict[str, str]) -> None:
    user_id = await _user()
    due = datetime.now(UTC) - timedelta(minutes=1)
    task_id = await _task(user_id, due=due, recurrence="FREQ=FORTNIGHTLY")

    assert await deliver() == 1
    async with db_session.session_scope() as session:
        events = (
            await session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id))
        ).all()
        kinds = {event.event for event in events}
        assert "reminder_fired" in kinds
        assert "reminder_recurrence_unreadable" in kinds
        task = await session.get(Task, task_id)
        assert task is not None
        # Left where it was: the alternative is repeating every 30 s forever.
        assert task.due_at is not None


@pytest.mark.asyncio
async def test_acknowledging_clears_it_from_the_list(db: dict[str, str]) -> None:
    user_id = await _user()
    await _task(user_id, due=datetime.now(UTC) - timedelta(minutes=1))
    await deliver()

    items = await recent()
    assert len(items) == 1
    assert await acknowledge(int(items[0]["id"])) is True
    assert await recent() == []
    # Acking something that is not a reminder is a no-op with a False, not a crash.
    assert await acknowledge(999_999) is False


@pytest.mark.asyncio
async def test_a_completed_task_does_not_fire(db: dict[str, str]) -> None:
    user_id = await _user()
    due = datetime.now(UTC) - timedelta(minutes=1)
    task_id = await _task(user_id, due=due)
    async with db_session.session_scope() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        task.status = "done"
        task.completed_at = datetime.now(UTC)

    assert await deliver() == 0


@pytest.mark.parametrize(
    ("rule", "expected_delta"),
    [
        ("FREQ=HOURLY", timedelta(hours=1)),
        ("FREQ=HOURLY;INTERVAL=3", timedelta(hours=3)),
        ("FREQ=DAILY", timedelta(days=1)),
        ("FREQ=WEEKLY;INTERVAL=2", timedelta(weeks=2)),
    ],
)
def test_next_occurrence_handles_the_subset(rule: str, expected_delta: timedelta) -> None:
    start = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
    assert next_occurrence(start, rule) == start + expected_delta


def test_monthly_occurrence_clamps_a_short_month() -> None:
    start = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
    assert next_occurrence(start, "FREQ=MONTHLY") == datetime(2026, 2, 28, 9, 0, tzinfo=UTC)


def test_an_unknown_rule_is_none_rather_than_a_wrong_time() -> None:
    start = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
    assert next_occurrence(start, "FREQ=YEARLY") is None
    assert next_occurrence(start, "FREQ=DAILY;INTERVAL=zero") is None
    assert next_occurrence(start, "FREQ=DAILY;INTERVAL=0") is None
