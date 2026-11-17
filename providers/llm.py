"""LLM access: one Protocol, two implementations.

``StubClient`` is not a mock for tests. It is the offline provider: it plans
deterministic tool calls so the whole loop (filtering, approvals, taint, budget,
audit) is exercisable with no key and no spend. It only ever sees the tool list
it is handed, so a tool removed by ``agent.policy`` is genuinely invisible to it.

``HTTPChatClient`` speaks the chat-completions tool-calling protocol, which
OpenAI and OpenRouter share.
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
from providers.catalog import ProviderSpec, spec_for

Role = Literal["system", "user", "assistant", "tool"]

# VERIFY: read these again at openai.com/api/pricing (and the model page on
# openrouter.ai) before trusting a projection. USD per 1M tokens (in, out).
# OpenRouter slugs are priced per model and change; when the response carries a
# ``usage.cost`` this table is not consulted at all.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4.1-mini": (0.40, 1.60),
}


# Nothing should hold a socket for longer than this, however impatient the caller.
HTTP_TIMEOUT_FLOOR_S = 25.0


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
    # Provider-reported spend, when the provider reports one (OpenRouter does).
    # Preferred over the price table: the table is a guess about a moving price.
    cost_usd: float | None = None
    # Every provider the chain tried, so failures reach the ledger too (P4).
    attempts: list[AttemptTrace] = []


class AttemptTrace(BaseModel):
    provider: str
    model: str
    ok: bool
    status: int | None = None
    error: str = ""


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
        raw_tasks = first.get("tasks")
        tasks: list[Any] = raw_tasks if isinstance(raw_tasks, list) else []
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
        raw_msgs = first.get("messages")
        msgs: list[Any] = raw_msgs if isinstance(raw_msgs, list) else []
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


def _why(body: str, limit: int = 300) -> str:
    """The provider's own words, trimmed. Never the request, so no key leaks."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()[:limit]
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:limit]
    if isinstance(error, str):
        return error[:limit]
    return body.strip()[:limit]


def _tool_call_in(content: str) -> dict[str, Any] | None:
    """The assistant step the graph persists as JSON text, if this message is one."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        call = parsed.get("tool_call")
        if isinstance(call, dict) and call.get("name"):
            return call
    return None


def wire_messages(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """Translate the agent's compact transcript into the API's tool-call shape.

    The graph stores a tool step as ``{"tool_call": {...}}`` inside the assistant
    content and its result as a bare ``role="tool"`` message: compact to persist,
    and enough for the stub, which parses that JSON. Every OpenAI-compatible API
    requires something stricter - the assistant message carries a ``tool_calls``
    array with ids, and each tool message names the id it answers - and rejects a
    ``tool`` message without one ("messages[3]: tool messages must include a
    non-empty string tool_call_id"). Only a real provider ever said so.
    """
    wire: list[dict[str, Any]] = []
    pending_id: str | None = None
    for index, message in enumerate(messages):
        if message.role == "assistant":
            call = _tool_call_in(message.content)
            if call is not None:
                pending_id = f"call_{index}"
                arguments = call.get("args") or call.get("arguments") or {}
                wire.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": pending_id,
                                "type": "function",
                                "function": {
                                    "name": str(call.get("name")),
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    }
                )
                continue
            wire.append({"role": "assistant", "content": message.content})
            continue
        if message.role == "tool":
            entry: dict[str, Any] = {"role": "tool", "content": message.content}
            if pending_id:
                entry["tool_call_id"] = pending_id
            wire.append(entry)
            continue
        wire.append(
            {
                "role": message.role,
                "content": message.content,
                **({"name": message.name} if message.name else {}),
            }
        )
    return wire


class LLMNotConfigured(RuntimeError):
    """The selected provider has no key.

    Loud, and incapable of answering: a missing key must never fall back to the
    stub, because templated prose would look exactly like a real answer.
    """


class UnconfiguredClient:
    """Selected provider, no key. Boots so the UI can name the missing line,
    refuses every call so nothing is ever answered by the wrong engine."""

    def __init__(self, provider: str, model: str, key_env: str) -> None:
        self.provider = provider
        self.model = model
        self.key_env = key_env

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        *,
        deadline_ms: int,
    ) -> LLMReply:
        raise LLMNotConfigured(
            f"{self.key_env} is empty: put it in .env to use {self.provider}, "
            "or set LLM_PROVIDER=stub for offline answers"
        )


class ProviderHTTPError(RuntimeError):
    """A provider said no. ``retryable`` decides whether the chain moves on."""

    def __init__(self, provider: str, status: int, detail: str) -> None:
        super().__init__(f"{provider} http {status}: {detail}")
        self.provider = provider
        self.status = status
        self.detail = detail
        # 429 rate limit, 402 out of credit, 5xx and 408 are worth another
        # provider's time. 400/401/403/404 are about *this* request or key and
        # would fail the same way everywhere: retrying just doubles the latency.
        self.retryable = status in {402, 408, 409, 425, 429} or status >= 500


class HTTPChatClient:
    """OpenAI-compatible chat completions, for any provider in the catalog.

    Providers differ in base URL, key and one extra header; everything else is
    the same wire format, so branching inside a second client class would be
    duplication that drifts.
    """

    def __init__(self, spec: ProviderSpec, model: str, api_key: str, referer: str = "") -> None:
        self.provider = spec.name
        self.model = model
        self.base_url = spec.base_url
        self.spec = spec
        self._api_key = api_key
        self._referer = referer

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self.provider == "openrouter":
            # OpenRouter's attribution headers; without them requests still work,
            # they just show up unattributed in the operator's activity log.
            if self._referer:
                headers["HTTP-Referer"] = self._referer
            headers["X-Title"] = "Jarvis"
        return headers

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        *,
        deadline_ms: int,
    ) -> LLMReply:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages(messages),
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
        if self.provider == "openrouter":
            # Ask for the authoritative per-request cost instead of inferring it.
            payload["usage"] = {"include": True}
        # The caller's deadline is a latency *target*, not an HTTP timeout: a
        # 3 s voice deadline turned every free reasoning model into a ReadTimeout
        # mid-turn, which reads to the operator as "voice is broken". Hang up on
        # something genuinely stalled, and measure the latency instead of guessing.
        timeout = max(HTTP_TIMEOUT_FLOOR_S, deadline_ms / 1000.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
        if response.status_code != 200:
            # The provider's body names the offending field. Dropping it turns a
            # one-line fix into a guessing game, and 'llm http 400' in the chat
            # bubble tells the operator nothing.
            raise ProviderHTTPError(self.provider, response.status_code, _why(response.text))
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
        reported = usage.get("cost")
        return LLMReply(
            content=str(message.get("content") or ""),
            tool_calls=calls,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            cost_usd=float(reported) if isinstance(reported, int | float) else None,
        )


class ChainClient:
    """Primary provider, then fallbacks, in order.

    A free tier rate-limits. Without a chain that is a dead turn; with one it is a
    slower turn. Failures are not swallowed: every attempt is reported back in
    ``LLMReply.attempts`` so the ledger can record what happened (P4), and the
    operator can see which engine actually answered.
    """

    def __init__(self, clients: Sequence[HTTPChatClient]) -> None:
        if not clients:
            raise ValueError("ChainClient needs at least one client")
        self._clients = list(clients)
        self.provider = self._clients[0].provider
        self.model = self._clients[0].model

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        *,
        deadline_ms: int,
    ) -> LLMReply:
        attempts: list[AttemptTrace] = []
        last: Exception | None = None
        for client in self._clients:
            try:
                reply = await client.chat(messages, tools, deadline_ms=deadline_ms)
            except (ProviderHTTPError, httpx.HTTPError, TimeoutError) as exc:
                retryable = getattr(exc, "retryable", True)
                attempts.append(
                    AttemptTrace(
                        provider=client.provider,
                        model=client.model,
                        ok=False,
                        status=getattr(exc, "status", None),
                        error=str(exc)[:300],
                    )
                )
                last = exc
                if not retryable:
                    raise
                continue
            # The final attempt names whoever answered, so cost rows and the UI
            # do not credit the primary for the fallback's work.
            attempts.append(AttemptTrace(provider=client.provider, model=client.model, ok=True))
            return LLMReply(
                content=reply.content,
                tool_calls=reply.tool_calls,
                tokens_in=reply.tokens_in,
                tokens_out=reply.tokens_out,
                cost_usd=reply.cost_usd,
                attempts=attempts,
            )
        raise last if last is not None else RuntimeError("no provider answered")


def get_client() -> LLMClient:
    """Build the chain. A missing key yields a refusing client, not the stub.

    Prod never reaches this point without a key: ``settings_guard`` exits first.
    Dev boots with a refusing client so ``/api/health`` and the chat can both name
    the exact variable to fill.
    """
    settings = get_settings()
    if settings.llm_provider == "stub":
        return StubClient()
    clients: list[HTTPChatClient] = []
    for provider in settings.llm_chain:
        spec = spec_for(provider)
        if spec is None:
            continue
        model = settings.model_for(provider)
        if spec.requires_vendor_prefix and "/" not in model:
            # OpenRouter addresses models as vendor/model. A bare "gpt-4o-mini"
            # 404s at request time, halfway through a turn, which is a far worse
            # failure than refusing to build the client.
            raise RuntimeError(
                f"LLM_PROVIDER={provider} needs a vendor-prefixed model such as "
                f"'openai/gpt-4o-mini', got {model!r}"
            )
        key = settings.key_for(provider)
        if not key:
            # A keyless provider in the chain is skipped, not fatal, *unless* it is
            # the only one - then the operator gets a client that says which line to
            # fill instead of a stack trace at boot.
            continue
        clients.append(HTTPChatClient(spec, model, key, referer=settings.app_base_url))
    if not clients:
        return UnconfiguredClient(
            settings.llm_provider, settings.llm_model_strong, settings.llm_key_env_name
        )
    if len(clients) == 1:
        return clients[0]
    return ChainClient(clients)
