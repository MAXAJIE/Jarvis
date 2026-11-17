"""The agent graph: supervisor routing, specialist tool loop, approval gate.

Shape (D-03, D-05): one graph, transport-agnostic. Nothing here asks what
transport it is on; the context carries ``lang`` and ``transport`` and the
adapter decides how to speak.

The loop, per specialist turn::

    START -> route -> agent -> (gate -> act -> agent)*  -> END

``agent`` calls the model with the *filtered* tool list, so a tool removed by
policy is genuinely invisible. ``gate`` enforces budget and approval before any
side effect, and suspends the graph with ``interrupt()`` when a human is needed.
``act`` runs exactly one tool, writes ``tool_runs`` in a ``finally``, and folds
the tool's taint into the rest of the turn.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent.policy import enforce_budget, filter_tools, needs_approval, taint_after
from agent.router import route_specialist
from apps.api.services.audit import ensure_approval, write_tool_run
from apps.api.services.budget import budget_state, record_llm_cost
from packages.contracts.errors import BudgetExceeded, ToolError
from packages.contracts.tool import Lang, Tool, ToolContext
from providers.llm import PRICES_PER_MTOK, ChatMessage, LLMClient, ToolSpec
from tools.registry import Registry

MAX_ITERATIONS = 8


class AgentState(TypedDict, total=False):
    ctx: dict[str, Any]
    messages: list[dict[str, Any]]
    specialist: str
    tainted: bool
    iterations: int
    pending: dict[str, Any] | None
    answer: str
    approval: dict[str, Any] | None
    stopped: str


@dataclass
class GraphDeps:
    registry: Registry
    client: LLMClient


def _ctx(state: AgentState) -> ToolContext:
    return ToolContext.model_validate(state["ctx"])


def _last_user_text(state: AgentState) -> str:
    for message in reversed(state["messages"]):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _tool_message(name: str, ok: bool, payload: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "ok": ok}
    body.update(payload)
    return {"role": "tool", "name": name, "content": json.dumps(body, ensure_ascii=False)}


def _refusal(name: str, reason: str) -> dict[str, Any]:
    return _tool_message(name, False, {"error": reason})


def _spec(tool: Tool) -> ToolSpec:
    return ToolSpec(
        name=tool.name,
        description=tool.description,
        parameters=tool.input_model.model_json_schema(),
    )


async def dispatch_tool(
    tool: Tool, args: Any, ctx: ToolContext
) -> tuple[bool, dict[str, Any], str]:
    """Run one tool. Returns (ok, payload, error). Always writes a tool_runs row."""
    started = time.perf_counter()
    timeout_s = min(tool.timeout_s * 1000.0, float(ctx.deadline_ms)) / 1000.0
    ok = True
    payload: dict[str, Any] = {}
    error: str | None = None
    try:
        result = await asyncio.wait_for(tool.run(args, ctx), timeout=timeout_s)
        payload = {"result": result.model_dump(mode="json")}
    except TimeoutError:
        ok, error = False, f"{tool.name} timed out after {timeout_s:.1f}s"
    except ToolError as exc:
        ok, error = False, str(exc)
    except Exception as exc:  # noqa: BLE001 - provider text never reaches the model
        ok, error = False, f"{tool.name} failed ({type(exc).__name__})"
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        await write_tool_run(
            tool_name=tool.name,
            ok=ok,
            args=getattr(args, "model_dump", lambda **_: {})(mode="json"),
            result=payload or None,
            error=error,
            ms=ms,
            conversation_id=ctx.conversation_id,
        )
    if not ok:
        payload = {"error": error}
    return ok, payload, error or ""


def build_graph(deps: GraphDeps, checkpointer: Any) -> Any:
    registry = deps.registry

    async def route(state: AgentState) -> dict[str, Any]:
        # Route every turn. The graph state lives in the per-thread checkpointer,
        # so trusting an existing value made the specialist sticky: a turn routed
        # to "executor" kept playing executor for the rest of the conversation and
        # silently lost the scheduler's tools (task_delete included). A resumed
        # turn does not re-enter this node, so re-routing cannot break resume.
        return {"specialist": route_specialist(_last_user_text(state))}

    async def agent(state: AgentState) -> dict[str, Any]:
        ctx = _ctx(state)
        specialist = state.get("specialist", "scheduler")
        visible = filter_tools(registry.for_specialist(specialist), ctx)
        messages = [ChatMessage.model_validate(m) for m in state["messages"]]
        if ctx.turn_tainted:
            # State the restriction in-band: the tool list alone tells the model
            # nothing about *why* a tool vanished, and a refusal that blames
            # outside content when the real cause is scope is a lie.
            messages.append(
                ChatMessage(
                    role="system",
                    content="tainted: outside content in this turn",
                )
            )
        reply = await deps.client.chat(
            messages, [_spec(t) for t in visible], deadline_ms=ctx.deadline_ms
        )
        await record_llm_cost(
            provider=deps.client.provider,
            model=deps.client.model,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
            conversation_id=ctx.conversation_id,
            price_per_mtok=PRICES_PER_MTOK.get(deps.client.model),
        )
        transcript = list(state["messages"])
        if reply.content:
            transcript.append({"role": "assistant", "content": reply.content})

        if not reply.tool_calls:
            return {"messages": transcript, "answer": reply.content, "pending": None, "stopped": ""}

        if state.get("iterations", 0) >= MAX_ITERATIONS:
            note = f"Stopped after {MAX_ITERATIONS} tool steps in one turn."
            transcript.append({"role": "assistant", "content": note})
            return {
                "messages": transcript,
                "answer": note,
                "pending": None,
                "stopped": "max_iterations",
            }

        call = reply.tool_calls[0]
        transcript.append(
            {"role": "assistant", "content": json.dumps({"tool_call": call.model_dump()})}
        )
        return {"messages": transcript, "pending": call.model_dump(), "answer": ""}

    async def gate(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending") or {}
        name = str(pending.get("name", ""))
        tool = registry.get(name)
        ctx = _ctx(state)
        try:
            args = tool.input_model.model_validate(pending.get("args", {}))
        except ValidationError as exc:
            first = exc.errors()[0]
            reason = f"bad arguments for {name}: {first.get('msg', 'invalid')}"
            return {"messages": [*state["messages"], _refusal(name, reason)], "pending": None}

        try:
            enforce_budget(tool, await budget_state())
        except BudgetExceeded as exc:
            return {"messages": [*state["messages"], _refusal(name, str(exc))], "pending": None}

        if needs_approval(tool, args, ctx):
            row = await ensure_approval(
                thread_id=ctx.thread_id,
                tool_name=name,
                args=pending.get("args", {}),
                risk=tool.risk.value,
            )
            if row["decision"] is None:
                from langgraph.types import interrupt

                interrupt(row)  # suspends here; the operator's answer lands in the table
            decision = row["decision"]
            if decision is None:
                from apps.api.services.audit import decision_of

                decision = await decision_of(str(row["id"]))
            if decision != "approved":
                reason = f"{name} was not approved"
                return {
                    "messages": [*state["messages"], _refusal(name, reason)],
                    "pending": None,
                }
        return {"pending": pending}

    async def act(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending") or {}
        name = str(pending.get("name", ""))
        tool = registry.get(name)
        ctx = _ctx(state)
        args = tool.input_model.model_validate(pending.get("args", {}))
        ok, payload, _error = await dispatch_tool(tool, args, ctx)
        # A failed read contributes no content, so it cannot inject anything.
        # Tainting on failure would train the operator to ignore the refusal.
        next_ctx = taint_after(tool, ctx) if ok else ctx
        return {
            "messages": [*state["messages"], _tool_message(name, ok, payload)],
            "pending": None,
            "ctx": next_ctx.model_dump(mode="json"),
            "tainted": next_ctx.turn_tainted,
            "iterations": state.get("iterations", 0) + 1,
        }

    def after_agent(state: AgentState) -> str:
        return "gate" if state.get("pending") else "end"

    def after_gate(state: AgentState) -> str:
        return "act" if state.get("pending") else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("route", route)
    graph.add_node("agent", agent)
    graph.add_node("gate", gate)
    graph.add_node("act", act)
    graph.add_edge(START, "route")
    graph.add_edge("route", "agent")
    graph.add_conditional_edges("agent", after_agent, {"gate": "gate", "end": END})
    graph.add_conditional_edges("gate", after_gate, {"act": "act", "agent": "agent"})
    graph.add_edge("act", "agent")
    return graph.compile(checkpointer=checkpointer)


def initial_state(
    ctx: ToolContext,
    user_text: str,
    prompt: str,
    history: list[dict[str, Any]] | None = None,
) -> AgentState:
    return {
        "ctx": ctx.model_dump(mode="json"),
        "messages": [
            {"role": "system", "content": prompt},
            *(history or []),
            {"role": "user", "content": user_text},
        ],
        "specialist": "",
        "tainted": False,
        "iterations": 0,
        "pending": None,
        "answer": "",
        "stopped": "",
    }


def lang_of(ctx: ToolContext) -> Lang:
    return ctx.lang
