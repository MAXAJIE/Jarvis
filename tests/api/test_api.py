"""HTTP and WebSocket surface, exercised through the real app and lifespan."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient

from apps.api.auth import hash_password, reset_rate_limit
from apps.api.config import reset_settings_cache
from apps.api.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[TestClient]:
    from apps.api.db import session as db_session

    secret = pyotp.random_base32()
    import asyncio

    asyncio.get_event_loop_policy()
    monkeypatch.setenv("OPERATOR_EMAIL", "operator@example.test")
    monkeypatch.setenv("OPERATOR_PASSWORD_HASH", hash_password("correct-horse-battery"))
    monkeypatch.setenv("OPERATOR_TOTP_SECRET", secret)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("JARVIS_CHECKPOINT_PATH", str(tmp_path / "cp.sqlite"))
    reset_settings_cache()
    reset_rate_limit()
    _ = db_session
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    reset_settings_cache()


def login(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = client.app.state  # noqa: F841 - keep the attribute access obvious
    from apps.api.config import get_settings

    totp = pyotp.TOTP(get_settings().operator_totp_secret).now()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "operator@example.test",
            "password": "correct-horse-battery",
            "totp": totp,
        },
    )
    assert response.status_code == 200, response.text


def test_health_is_503_and_names_what_is_missing(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "llm" in body["missing"]
    assert any(part["component"] == "db" and part["ok"] for part in body["components"])


def test_login_requires_the_right_password_and_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = client.post(
        "/api/auth/login",
        json={"email": "operator@example.test", "password": "wrong", "totp": "000000"},
    )
    assert bad.status_code == 401
    login(client, monkeypatch)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "operator@example.test"


def test_protected_routes_refuse_anonymous(client: TestClient) -> None:
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/metrics/dashboard").status_code == 401
    assert client.get("/api/approvals").status_code == 401
    assert client.get("/api/system/overview").status_code == 401


def test_overview_feeds_the_command_center_from_real_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every panel number must come from a row, never from a constant."""
    login(client, monkeypatch)
    assert client.post("/api/tasks", json={"title": "audit the ledger"}).status_code == 201

    body = client.get("/api/system/overview").json()

    assert body["health"]["status"] == "degraded"  # no provider keys in tests
    assert "llm" in body["health"]["missing"]
    assert body["counters"]["open_tasks"] == 1
    assert body["counters"]["facts"] == 0
    assert body["budget"]["ceiling_usd"] == 20.0
    assert body["budget"]["remaining_usd"] <= 8.2
    # 22 runnable tools; the 6 this build cannot run are reported separately rather
    # than advertised as available.
    assert len(body["tools"]) == 22
    assert sum(body["tools_by_risk"].values()) == 22
    assert len(body["withheld_tools"]) == 6
    # No speech keys here, so the voice transport must report itself unavailable
    # rather than advertise a loop that cannot run.
    assert body["voice"]["stt_ready"] is False
    assert body["voice"]["transport_ready"] is False
    assert body["llm"]["configured"] is False
    assert [row["title"] for row in body["timeline"]] == []  # no due date set
    assert body["timeline"] == []

    task_id = client.get("/api/tasks").json()[0]["id"]
    soon = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    client.patch(f"/api/tasks/{task_id}", json={"due_at": soon})
    body = client.get("/api/system/overview").json()
    assert body["timeline"][0]["title"] == "audit the ledger"
    assert body["timeline"][0]["overdue"] is False
    assert body["timeline"][0]["due_at"].endswith("+00:00")


def test_task_lifecycle_and_dashboard(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client, monkeypatch)
    created = client.post("/api/tasks", json={"title": "write the runbook", "priority": 2})
    assert created.status_code == 201
    task_id = created.json()["id"]

    patched = client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
    assert patched.json()["status"] == "done"
    assert patched.json()["completed_at"] is not None

    metrics = client.get("/api/metrics/dashboard").json()
    assert metrics["tasks_completed"] == 1
    assert metrics["ceiling_usd"] == 20.0
    assert metrics["fixed_usd"] >= 11.8
    assert metrics["remaining_usd"] < 8.21

    assert client.delete(f"/api/tasks/{task_id}").json()["deleted"] is True
    assert client.get("/api/tasks").json() == []


def test_chat_websocket_runs_a_real_turn(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, monkeypatch)
    with client.websocket_connect("/ws/chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["provider"] == "stub"
        ws.send_json({"type": "user_message", "text": "plan my week"})
        turn = ws.receive_json()
        assert turn["type"] == "turn"
        assert turn["answer"]
        assert len([e for e in turn["events"] if e["type"] == "tool"]) == 5
        ws.send_json({"type": "set_lang", "lang": "zh-TW"})
        assert ws.receive_json() == {"type": "lang", "lang": "zh-TW"}
        ws.send_json({"type": "user_message", "text": "list my tasks"})
        turn = ws.receive_json()
        assert turn["type"] == "turn"
        assert turn["answer"]


def test_websocket_refuses_anonymous(client: TestClient) -> None:
    with pytest.raises(Exception), client.websocket_connect("/ws/chat") as ws:  # noqa: B017
        ws.receive_json()
