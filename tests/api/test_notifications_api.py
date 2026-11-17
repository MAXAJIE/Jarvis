"""The reminder HTTP surface: list what fired, dismiss it, 404 on nonsense."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api.db import session as db_session
from apps.api.db.models import Task, User
from apps.api.services.reminders import deliver
from tests.api.test_api import login


async def _seed_due() -> str:
    async with db_session.session_scope() as session:
        user = User(email="notify@localhost")
        session.add(user)
        await session.flush()
        task = Task(
            user_id=user.id,
            title="stand up and stretch",
            due_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        session.add(task)
        await session.flush()
        return task.id


async def _fire() -> None:
    await _seed_due()
    assert await deliver() == 1


@pytest.mark.anyio
async def test_a_fired_reminder_is_listed_and_can_be_dismissed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, monkeypatch)
    await _fire()

    listed = client.get("/api/notifications")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 1
    reminder = body["reminders"][0]
    assert reminder["title"] == "stand up and stretch"
    assert reminder["status"] == "open"

    acked = client.post("/api/notifications/ack", json={"ids": [reminder["id"]]})
    assert acked.status_code == 200
    assert acked.json()["acknowledged"] == [reminder["id"]]
    assert client.get("/api/notifications").json()["count"] == 0


@pytest.mark.anyio
async def test_unknown_ids_are_reported_not_silently_ignored(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, monkeypatch)
    response = client.post("/api/notifications/ack", json={"ids": [424242]})
    assert response.status_code == 404


@pytest.mark.anyio
async def test_notifications_require_a_session(client: TestClient) -> None:
    assert client.get("/api/notifications").status_code == 401
