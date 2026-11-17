"""Turn orchestration: persistence, checkpointer lifecycle, resume, delegation.

The graph is a pure function of (state, deps). This module is the only place
that knows about the database, the checkpointer, and how a turn is recorded.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.types import Command

from agent.graph import GraphDeps, build_graph, dispatch_tool, initial_state
from agent.lang import load_prompt
from agent.policy import filter_tools, needs_approval, taint_after
from apps.api.config import get_settings
from apps.api.db.models import Message
from apps.api.db.session import session_scope
from packages.contracts.errors import NotConfigured
from packages.contracts.tool import ToolContext
from providers.llm import ChatMessage, LLMClient, ToolSpec, get_client
from tools import delegate as delegate_tool
from tools.registry import Registry, build_registry


@dataclass
class TurnResult:
    answer: str
    approval: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    stopped: str = ""
    tainted: bool = False


def _events_from(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            body: dict[str, Any] = json.loads(message.get("content", ""))
        except ValueError:
            continue
        events.append(
            {
                "type": "tool",
                "name": body.get("name"),
                "ok": bool(body.get("ok")),
                "detail": body.get("error") or body.get("result"),
            }
        )
    return events


class Runtime:
    def __init__(
        self,
        registry: Registry | None = None,
        client: LLMClient | None = None,
        checkpoint_path: Path | None = None,
    ) -> None:
        self.registry = registry or build_registry()
        self.client = client or get_client()
        self.checkpoint_path = checkpoint_path or Path(
            os.environ.get("JARVIS_CHECKPOINT_PATH", "var/checkpoints.sqlite")
        )
        self._conn: aiosqlite.Connection | None = None
        self._saver: Any = None

    # --- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        path = self.checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(path)
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        self._saver = AsyncSqliteSaver(self._conn)
        await self._saver.setup()
        delegate_tool.bind_runner(self._run_specialist)

    async def stop(self) -> None:
        delegate_tool.bind_runner(None)
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._saver = None

    def _graph(self) -> Any:
        if self._saver is None:
            raise NotConfigured("runtime not started")
        return build_graph(GraphDeps(registry=self.registry, client=self.client), self._saver)

    # --- one turn ----------------------------------------------------------
    async def turn(self, ctx: ToolContext, user_text: str) -> TurnResult:
        message_id = await self._persist_message(ctx, "user", user_text, tainted=False)
        prompt = load_prompt(ctx.lang)
        prompt += f"\n\ncontext: conversation_id={ctx.conversation_id} message_id={message_id}"
        state = initial_state(ctx, user_text, prompt)
        config = {"configurable": {"thread_id": ctx.thread_id}}
        result: dict[str, Any] = await self._graph().ainvoke(state, config)
        return await self._finish(ctx, result)

    async def resume(self, ctx: ToolContext, decision: str) -> TurnResult:
        config = {"configurable": {"thread_id": ctx.thread_id}}
        result: dict[str, Any] = await self._graph().ainvoke(
            Command(resume={"decision": decision}), config
        )
        return await self._finish(ctx, result)

    async def _finish(self, ctx: ToolContext, result: dict[str, Any]) -> TurnResult:
        messages: list[dict[str, Any]] = list(result.get("messages") or [])
        interrupts = result.get("__interrupt__") or []
        approval: dict[str, Any] | None = None
        if interrupts:
            raw = interrupts[0]
            payload = getattr(raw, "value", None) or {}
            approval = dict(payload)
        answer = str(result.get("answer") or "")
        if answer:
            await self._persist_message(
                ctx, "assistant", answer, tainted=bool(result.get("tainted", False))
            )
        return TurnResult(
            answer=answer,
            approval=approval,
            events=_events_from(messages),
            stopped=str(result.get("stopped") or ""),
            tainted=bool(result.get("tainted", False)),
        )

    async def _history(self, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Recent turns, oldest first. The checkpointer is per conversation, but
        reloading from the database keeps the model's view stable even if a run
        is resumed on a fresh process."""
        from sqlalchemy import select

        async with session_scope() as session:
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .where(Message.role.in_(["user", "assistant"]))
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
        return [{"role": row.role, "content": row.content} for row in reversed(rows)]

    async def _persist_message(
        self, ctx: ToolContext, role: str, content: str, *, tainted: bool
    ) -> str:
        message = Message(
            conversation_id=ctx.conversation_id, role=role, content=content, tainted=tainted
        )
        async with session_scope() as session:
            session.add(message)
            await session.flush()
            return message.id

    # --- delegation --------------------------------------------------------
    async def _run_specialist(self, specialist: str, instruction: str, ctx: ToolContext) -> str:
        """A bounded sub-loop for ``delegate``.

        It refuses anything that would need approval instead of prompting from
        inside a nested run: one approval surface per turn (T11).
        """
        visible = filter_tools(self.registry.for_specialist(specialist), ctx)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=load_prompt(ctx.lang)),
            ChatMessage(role="user", content=instruction),
        ]
        specs = [
            ToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_model.model_json_schema(),
            )
            for tool in visible
        ]
        local = ctx
        for _ in range(3):
            reply = await self.client.chat(messages, specs, deadline_ms=ctx.deadline_ms)
            if not reply.tool_calls:
                return reply.content
            call = reply.tool_calls[0]
            tool = next((t for t in visible if t.name == call.name), None)
            if tool is None:
                return f"{call.name} is not available to {specialist}"
            try:
                args = tool.input_model.model_validate(call.args)
            except Exception:  # noqa: BLE001 - a bad plan is a refusal, not a crash
                return f"{tool.name} was called with invalid arguments"
            if needs_approval(tool, args, local):
                return f"{tool.name} needs your approval; ask me directly and I will queue it."
            ok, payload, error = await dispatch_tool(tool, args, local)
            local = taint_after(tool, local)
            messages.append(
                ChatMessage(
                    role="tool",
                    name=tool.name,
                    content=str(payload if ok else {"error": error}),
                )
            )
        return "stopped after 3 delegated steps"


def default_context(
    *,
    user_id: str,
    conversation_id: str,
    thread_id: str,
    lang: str = "en",
    transport: str = "web",
) -> ToolContext:
    from packages.contracts.tool import Lang, Transport

    return ToolContext(
        user_id=user_id,
        conversation_id=conversation_id,
        thread_id=thread_id,
        lang=Lang(lang),
        transport=Transport(transport),
        deadline_ms=8000 if transport != "voice" else 3000,
    )


def settings_guard() -> None:
    """P6: a production process may not run on the stub provider."""
    settings = get_settings()
    if settings.is_prod and settings.llm_provider != "openai":
        raise SystemExit(
            "refusing to start: APP_ENV=prod requires LLM_PROVIDER=openai and a real key"
        )
    if settings.is_prod and not settings.openai_api_key:
        raise SystemExit("refusing to start: OPENAI_API_KEY is empty")
