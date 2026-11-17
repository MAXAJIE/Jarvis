"""Reminder delivery: a due task fires once, and a repeating one rolls forward.

Until this existed, ``remind`` created a task with a time on it and nothing ever
looked at that time: the agent would cheerfully say "I'll remind you at 9" and then
never mention it again. That is worse than refusing, because the operator plans
around it.

Mechanics, deliberately small:

* A task is due when it is ``open``, has a ``due_at`` in the past, and has no
  ``reminder_fired`` event yet. The event row *is* the idempotency key, so a poll
  that runs twice - or a process that restarts mid-tick - cannot remind twice.
* Repeating tasks are not cloned: the same row's ``due_at`` moves to the next
  occurrence. Cloning leaves a growing pile of history for a daily habit.
* The recurrence parser handles the RRULE subset the planner actually emits
  (``FREQ=HOURLY|DAILY|WEEKLY|MONTHLY`` plus ``INTERVAL=n``). Anything else is
  reported and left alone rather than guessed at.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from apps.api.db.models import Task, TaskEvent
from apps.api.db.session import session_scope

FIRED = "reminder_fired"
ACKED = "reminder_ack"
FAILED_RECURRENCE = "reminder_recurrence_unreadable"


def _utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres aware ones. One clock, always UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _add_months(start: datetime, months: int) -> datetime:
    """Add months without the 31st-of-February trap."""
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def next_occurrence(start: datetime, rrule: str) -> datetime | None:
    """The next time after ``start``, or None if the rule is outside the subset.

    None means "do not guess": the caller records why, and the task keeps its old
    time rather than silently repeating at the wrong interval.
    """
    parts: dict[str, str] = {}
    for chunk in rrule.upper().split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts[key.strip()] = value.strip()
    frequency = parts.get("FREQ", "")
    try:
        interval = int(parts.get("INTERVAL", "1"))
    except ValueError:
        return None
    if interval < 1:
        return None

    if frequency == "MINUTELY":
        return start + timedelta(minutes=interval)
    if frequency == "HOURLY":
        return start + timedelta(hours=interval)
    if frequency == "DAILY":
        return start + timedelta(days=interval)
    if frequency == "WEEKLY":
        return start + timedelta(weeks=interval)
    if frequency == "MONTHLY":
        return _add_months(start, interval)
    return None


async def deliver(*, now: datetime | None = None) -> int:
    """Fire every due reminder. Returns how many fired. Safe to call repeatedly."""
    moment = now or datetime.now(UTC)
    fired = 0
    async with session_scope() as session:
        already = set(
            (await session.scalars(select(TaskEvent.task_id).where(TaskEvent.event == FIRED))).all()
        )
        candidates = (
            await session.scalars(
                select(Task)
                .where(Task.status == "open", Task.due_at.is_not(None), Task.due_at <= moment)
                .order_by(Task.due_at)
                .limit(200)
            )
        ).all()

        for task in candidates:
            if task.id in already:
                continue
            due_at = _utc(task.due_at)
            session.add(
                TaskEvent(
                    task_id=task.id,
                    event=FIRED,
                    payload={
                        "title": task.title,
                        "due_at": due_at.isoformat() if due_at else None,
                        "recurrence": task.recurrence,
                        "fired_at": moment.isoformat(),
                    },
                )
            )
            # Mark locally so a duplicate row inside the same tick is impossible even
            # before the transaction commits.
            already.add(task.id)
            fired += 1

            if task.recurrence:
                following = _utc(task.due_at)
                nxt = next_occurrence(following, task.recurrence) if following else None
                if nxt is None:
                    session.add(
                        TaskEvent(
                            task_id=task.id,
                            event=FAILED_RECURRENCE,
                            payload={"recurrence": task.recurrence},
                        )
                    )
                else:
                    task.due_at = nxt
    return fired


async def recent(*, limit: int = 20) -> list[dict[str, Any]]:
    """Fired reminders still waiting to be acknowledged, newest first."""
    async with session_scope() as session:
        events = (
            await session.scalars(
                select(TaskEvent)
                .where(TaskEvent.event.in_([FIRED, ACKED]))
                .order_by(TaskEvent.id.desc())
                .limit(400)
            )
        ).all()
        acknowledged = {
            int((event.payload or {}).get("of", -1)) for event in events if event.event == ACKED
        }
        tasks = {
            task.id: task
            for task in (
                await session.scalars(
                    select(Task).where(Task.id.in_({event.task_id for event in events}))
                )
            ).all()
        }
        out: list[dict[str, Any]] = []
        for event in events:
            if event.event != FIRED or event.id in acknowledged:
                continue
            task = tasks.get(event.task_id)
            payload = event.payload or {}
            out.append(
                {
                    "id": event.id,
                    "task_id": event.task_id,
                    "title": str(payload.get("title") or (task.title if task else "reminder")),
                    "due_at": payload.get("due_at"),
                    "fired_at": (_utc(event.created_at) or datetime.now(UTC)).isoformat(),
                    "status": task.status if task else "missing",
                }
            )
            if len(out) >= limit:
                break
        return out


async def acknowledge(event_id: int) -> bool:
    """Record that the operator has seen a reminder. Returns False if unknown."""
    async with session_scope() as session:
        event = await session.get(TaskEvent, event_id)
        if event is None or event.event != FIRED:
            return False
        session.add(TaskEvent(task_id=event.task_id, event=ACKED, payload={"of": event_id}))
        return True
