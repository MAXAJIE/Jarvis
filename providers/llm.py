"""LLM access: one Protocol, two implementations.

``StubClient`` is not a mock for tests. It is the offline provider: it plans
deterministic tool calls so the whole loop (filtering, approvals, taint, budget,
audit) is exercisable with no key and no spend. It only ever sees the tool list
it is handed, so a tool removed by ``agent.policy`` is genuinely invisible to it.

``OpenAIClient`` speaks the chat-completions tool-calling protocol.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel

from apps.api.config import get_settings

Role = Literal["system", "user", "assistant", "tool"]

# VERIFY: read these again at openai.com/api/pricing before trusting a
# projection. USD per 1M tokens. Not verified by this build.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
}


class ChatMessage(BaseModel):
    role: Role
    content: str
    name: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]


class LLMReply(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = []
    tokens_in: int = 0
    tokens_out: int = 0


class LLMClient(Protocol):
    provider: str
    model: str

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        *,
        deadline_ms: int,
    ) -> LLMReply: ...


def _tool_result(messages: Sequence[ChatMessage]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.role == "tool":
            try:
                parsed: dict[str, Any] = json.loads(message.content)
            except json.JSONDecodeError:
                return None
            return parsed
        if message.role == "user":
            return None
    return None


def _done(messages: Sequence[ChatMessage], call: ToolCall) -> bool:
    """A planned step counts as done only with the same name *and* the same args.

    Comparing names alone makes a five-step plan stop after step one.
    """
    for message in messages:
        if message.role != "assistant":
            continue
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        recorded = parsed.get("tool_call")
        if (
            isinstance(recorded, dict)
            and recorded.get("name") == call.name
            and recorded.get("args") == call.args
        ):
            return True
    return False


def _plan(text: str, message_id: str = "") -> list[ToolCall]:
    lowered = text.lower()
    today = datetime.now(UTC).date()
    plan: list[ToolCall] = []

    if "plan my week" in lowered or "plan my day" in lowered or "計劃" in text:
        blocks = [
            ("Review open tasks and inbox", 0, 1),
            ("Deep work: main project", 0, 3),
            ("Errands and admin", 1, 2),
            ("Prepare next week's calls", 2, 2),
            ("Weekly review", 4, 1),
        ]
        for title, day_offset, priority in blocks:
            plan.append(
                ToolCall(
                    name="task_create",
                    args={
                        "title": title,
                        "due_at": (today + timedelta(days=day_offset)).isoformat(),
                        "priority": priority,
                    },
                )
            )
        return plan

    if match := re.search(r"(?:fetch|read|open)\s+(https?://\S+)", text):
        return [ToolCall(name="web_fetch", args={"url": match.group(1)})]

    if "unread" in lowered or "summarise" in lowered or "summarize" in lowered:
        return [ToolCall(name="mail_search", args={"query": "is:unread newer_than:7d", "limit": 5})]

    if "reply" in lowered:
        plan.append(
            ToolCall(
                name="mail_draft",
                args={
                    "to": "someone@example.com",
                    "subject": "Re: your message",
                    "body": "Thanks, I will get back to you by Friday.",
                },
            )
        )
        plan.append(ToolCall(name="mail_send", args={"draft_id": "<draft>"}))
        return plan

    if match := re.search(r"(\+[1-9]\d{7,14})", text):
        plan.append(
            ToolCall(
                name="call_place",
                args={"to_e164": match.group(1), "purpose": "confirm Friday's appointment"},
            )
        )
        return plan

    if "delete task" in lowered or "刪除" in text:
        match = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})", text)
        if match:
            return [ToolCall(name="task_delete", args={"task_id": match.group(1)})]

    if lowered.startswith("remember") or "記住" in text:
        match = re.search(r"(?:remember(?: that)?|記住)\s+(.+)", text, re.IGNORECASE)
        body = match.group(1) if match else "something"
        return [
            ToolCall(
                name="memory_write_fact",
                args={
                    "subject": "operator",
                    "predicate": "note",
                    "object": body.strip(),
                    "source_message_id": message_id,
                },
            )
        ]

    if "task" in lowered and any(w in lowered for w in ("add", "create", "remind")):
        title = re.sub(r"^.*?(?:add|create|remind me to)\s+", "", text, flags=re.IGNORECASE)
        # "add task buy milk" must not create a task called "task buy milk".
        title = re.sub(r"^(?:a\s+)?task\s+", "", title.strip(), flags=re.IGNORECASE)
        if "remind" in lowered:
            return [
                ToolCall(
                    name="remind",
                    args={
                        "text": title.strip() or "reminder",
                        "when": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    },
                )
            ]
        return [ToolCall(name="task_create", args={"title": title.strip() or "new task"})]

    if any(w in lowered for w in ("list", "show", "what are my", "todo", "to-do")):
        return [ToolCall(name="task_list", args={"limit": 20})]

    if match := re.search(r"(?:run|execute)\s+(.+)", text):
        return [ToolCall(name="shell", args={"command": match.group(1).strip()})]

    return []


def _tool_results(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for message in messages:
        if message.role != "tool":
            continue
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            results.append(parsed)
    return results


def _titles(payloads: list[dict[str, Any]]) -> list[str]:
    titles: list[str] = []
    for payload in payloads:
        task = payload.get("task")
        if isinstance(task, dict) and isinstance(task.get("title"), str):
            titles.append(task["title"])
    return titles


def _describe(name: str, payloads: list[dict[str, Any]], zh: bool) -> str:
    """One readable sentence per tool, instead of dumping JSON at the operator."""
    count = len(payloads)
    titles = _titles(payloads)
    shown = "、".join(titles[:5]) if zh else ", ".join(titles[:5])
    if name == "task_create":
        if zh:
            return f"開咗 {count} 個任務：{shown}。"
        return f"Created {count} task{'s' if count != 1 else ''}: {shown}."
    if name == "task_list":
        first = payloads[0] if payloads else {}
        tasks = first.get("tasks") if isinstance(first.get("tasks"), list) else []
        names = [str(t.get("title", "")) for t in tasks if isinstance(t, dict)]
        joiner = "、" if zh else ", "
        if not names:
            return "你暫時冇任務。" if zh else "You have no tasks."
        return (
            f"你有 {len(names)} 個任務：{joiner.join(names[:6])}。"
            if zh
            else f"You have {len(names)} tasks: {joiner.join(names[:6])}."
        )
    if name == "task_delete":
        return "已經刪除。" if zh else "Deleted."
    if name == "task_complete":
        return "已經完成。" if zh else "Marked done."
    if name == "memory_write_fact":
        return "記低咗，等你確認。" if zh else "Noted. Confirm it and I will treat it as fact."
    if name in {"memory_search", "rag_search"}:
        hits = payloads[0] if payloads else {}
        items = hits.get("facts") or hits.get("hits") or []
        total = len(items) if isinstance(items, list) else 0
        return f"搵到 {total} 項。" if zh else f"Found {total} item(s)."
    if name == "mail_search":
        first = payloads[0] if payloads else {}
        msgs = first.get("messages") if isinstance(first.get("messages"), list) else []
        return f"有 {len(msgs)} 封相關郵件。" if zh else f"{len(msgs)} matching message(s)."
    if name == "web_fetch":
        first = payloads[0] if payloads else {}
        text = first.get("text")
        length = len(text) if isinstance(text, str) else 0
        return f"抓到 {length} 個字元。" if zh else f"Fetched {length} characters."
    if name in {"shell", "python_run"}:
        first = payloads[0] if payloads else {}
        return f"執行完，exit code {first.get('exit_code', '?')}。"
    if name == "remind":
        return "設好提醒。" if zh else "Reminder set."
    return f"{name} × {count}。"


def _summarise(user_text: str, messages: Sequence[ChatMessage], zh: bool) -> str:
    results = _tool_results(messages)
    if not results:
        if zh:
            return "我而家幫你處理。你可以叫我計劃一週、列出任務、讀網頁、或者打電話。"
        return (
            "Tell me what to do - I can plan your week, list tasks, read a page, "
            "draft mail, or place a call."
        )
    failed = [r for r in results if not r.get("ok", False)]
    if failed:
        reason = str(failed[0].get("error", "unknown"))
        return f"呢步做唔到：{reason}。" if zh else f"I could not do that: {reason}."

    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        payload = result.get("result")
        grouped.setdefault(str(result.get("name", "")), []).append(
            payload if isinstance(payload, dict) else {}
        )
    sentences = [_describe(name, payloads, zh) for name, payloads in grouped.items()]
    text = " ".join(part for part in sentences if part)
    if zh:
        return text
    return text


class StubClient:
    """Deterministic planner. Never spends money, never calls a network."""

    provider = "stub"
    model = "stub-planner"

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        *,
        deadline_ms: int,
    ) -> LLMReply:
        del deadline_ms
        available = {tool.name for tool in tools}
        user_text = ""
        for message in messages:
            if message.role == "user":
                user_text = message.content
                break
        system_text = next((m.content for m in messages if m.role == "system"), "")
        zh = "zh-TW" in user_text or "繁體" in system_text
        source = re.search(r"message_id=(\S+)", system_text)

        tainted = any(m.role == "system" and "tainted:" in m.content for m in messages)
        plan = _plan(user_text, source.group(1) if source else "")
        last = _tool_result(messages)
        if last is not None and isinstance(last.get("result"), dict):
            draft_id = last["result"].get("draft_id")
            if isinstance(draft_id, str):
                for call in plan:
                    if call.name == "mail_send" and call.args.get("draft_id") == "<draft>":
                        call.args["draft_id"] = draft_id
        if not plan:
            return LLMReply(content=_summarise(user_text, messages, zh))

        for call in plan:
            if call.name not in available:
                # The tool can be missing for two very different reasons: the turn
                # is tainted, or the specialist does not own it. Say which, instead
                # of blaming outside content for both.
                reason = "呢一輪嘅內容來自外部" if tainted else "呢一輪用唔到呢個工具"
                return LLMReply(
                    content=(
                        f"我唔可以喺呢一輪用 {call.name}：{reason}。"
                        "如果真係要做，請開新一輪再叫我。"
                        if zh
                        else (
                            f"I cannot use {call.name} in this turn: "
                            + (
                                "the turn contains outside content"
                                if tainted
                                else "it is not available for this kind of request"
                            )
                            + ". Ask me again in a new turn if you still want it done."
                        )
                    )
                )
            if not _done(messages, call):
                return LLMReply(tool_calls=[call])
        return LLMReply(content=_summarise(user_text, messages, zh))


class OpenAIClient:
    provider = "openai"

    def __init__(self, model: str) -> None:
        self.model = model

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        *,
        deadline_ms: int,
    ) -> LLMReply:
        settings = get_settings()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})}
                for m in messages
            ],
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        timeout = max(1.0, deadline_ms / 1000.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"llm http {response.status_code}")
        body: dict[str, Any] = response.json()
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls: list[ToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            function = raw_call.get("function") or {}
            try:
                parsed_args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                parsed_args = {}
            calls.append(ToolCall(name=str(function.get("name")), args=parsed_args))
        usage = body.get("usage") or {}
        return LLMReply(
            content=str(message.get("content") or ""),
            tool_calls=calls,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )


def get_client() -> LLMClient:
    """Fail closed: a prod process with the stub provider refuses to start elsewhere."""
    settings = get_settings()
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is empty")
        return OpenAIClient(settings.llm_model_strong)
    return StubClient()
