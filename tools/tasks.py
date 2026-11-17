"""Task tools: the only writes the agent may make to the task list."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from apps.api.db.models import Task, TaskEvent
from apps.api.db.session import session_scope
from packages.contracts.errors import ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from tools.base import FunctionTool

STATUSES = {"open", "in_progress", "blocked", "done", "cancelled"}


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    detail: str | None = None
    status: str
    priority: int
    due_at: datetime | None = None
    parent_id: str | None = None
    source: str
    recurrence: str | None = None
    completed_at: datetime | None = None


class TaskListIn(BaseModel):
    status: str | None = Field(default=None, description="Filter by status, or omit for all")
    limit: int = Field(default=50, ge=1, le=200)


class TaskListOut(BaseModel):
    tasks: list[TaskOut]
    count: int


class TaskGetIn(BaseModel):
    task_id: str


class TaskGetOut(BaseModel):
    task: TaskOut | None


class TaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    detail: str | None = None
    due_at: datetime | None = None
    priority: int = Field(default=3, ge=1, le=5)
    parent_id: str | None = None
    recurrence: str | None = Field(default=None, description="iCal RRULE, omit for one-shot")


class TaskCreateOut(BaseModel):
    task: TaskOut


class TaskUpdateIn(BaseModel):
    task_id: str
    title: str | None = None
    detail: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None
    status: str | None = None


class TaskUpdateOut(BaseModel):
    task: TaskOut


class TaskCompleteIn(BaseModel):
    task_id: str


class TaskCompleteOut(BaseModel):
    task: TaskOut


class TaskDeleteIn(BaseModel):
    task_id: str


class TaskDeleteOut(BaseModel):
    deleted: bool
    task_id: str


async def _create(a: TaskCreateIn, ctx: ToolContext) -> TaskCreateOut:
    async with session_scope() as session:
        task = Task(
            user_id=ctx.user_id,
            title=a.title,
            detail=a.detail,
            due_at=a.due_at,
            priority=a.priority,
            parent_id=a.parent_id,
            recurrence=a.recurrence,
            source="agent",
        )
        session.add(task)
        await session.flush()
        session.add(TaskEvent(task_id=task.id, event="created", payload={"by": "agent"}))
        await session.commit()
        return TaskCreateOut(task=TaskOut.model_validate(task))


async def _list(a: TaskListIn, ctx: ToolContext) -> TaskListOut:
    async with session_scope() as session:
        stmt = select(Task).where(Task.user_id == ctx.user_id)
        if a.status is not None:
            if a.status not in STATUSES:
                raise ToolError(f"unknown status {a.status!r}")
            stmt = stmt.where(Task.status == a.status)
        stmt = stmt.order_by(Task.priority.asc(), Task.due_at.asc()).limit(a.limit)
        rows = (await session.execute(stmt)).scalars().all()
        return TaskListOut(tasks=[TaskOut.model_validate(r) for r in rows], count=len(rows))


async def _get(a: TaskGetIn, ctx: ToolContext) -> TaskGetOut:
    async with session_scope() as session:
        row = await session.get(Task, a.task_id)
        if row is None or row.user_id != ctx.user_id:
            return TaskGetOut(task=None)
        return TaskGetOut(task=TaskOut.model_validate(row))


async def _update(a: TaskUpdateIn, ctx: ToolContext) -> TaskUpdateOut:
    async with session_scope() as session:
        row = await session.get(Task, a.task_id)
        if row is None or row.user_id != ctx.user_id:
            raise ToolError("task not found")
        if a.status is not None:
            if a.status not in STATUSES:
                raise ToolError(f"unknown status {a.status!r}")
            if a.status == "done":
                raise ToolError("use task_complete so completed_at is set")
            row.status = a.status
            session.add(TaskEvent(task_id=row.id, event="status", payload={"to": a.status}))
        if a.title is not None:
            row.title = a.title
        if a.detail is not None:
            row.detail = a.detail
        if a.priority is not None:
            row.priority = a.priority
        if a.due_at is not None:
            row.due_at = a.due_at
        await session.commit()
        return TaskUpdateOut(task=TaskOut.model_validate(row))


async def _complete(a: TaskCompleteIn, ctx: ToolContext) -> TaskCompleteOut:
    async with session_scope() as session:
        row = await session.get(Task, a.task_id)
        if row is None or row.user_id != ctx.user_id:
            raise ToolError("task not found")
        if row.status == "done":
            return TaskCompleteOut(task=TaskOut.model_validate(row))
        row.status = "done"
        row.completed_at = datetime.now(tz=row.created_at.tzinfo)
        session.add(TaskEvent(task_id=row.id, event="completed", payload=None))
        await session.commit()
        return TaskCompleteOut(task=TaskOut.model_validate(row))


async def _delete(a: TaskDeleteIn, ctx: ToolContext) -> TaskDeleteOut:
    async with session_scope() as session:
        row = await session.get(Task, a.task_id)
        if row is None or row.user_id != ctx.user_id:
            return TaskDeleteOut(deleted=False, task_id=a.task_id)
        await session.delete(row)
        await session.commit()
        return TaskDeleteOut(deleted=True, task_id=a.task_id)


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="task_list",
            description="List the operator's tasks, optionally filtered by status.",
            input_model=TaskListIn,
            output_model=TaskListOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=5.0,
            handler=_list,
        ),
        FunctionTool(
            name="task_get",
            description="Fetch one task by id.",
            input_model=TaskGetIn,
            output_model=TaskGetOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=5.0,
            handler=_get,
        ),
        FunctionTool(
            name="task_create",
            description="Create a task owned by the operator.",
            input_model=TaskCreateIn,
            output_model=TaskCreateOut,
            risk=RiskLevel.WRITE,
            idempotent=False,
            timeout_s=5.0,
            handler=_create,
        ),
        FunctionTool(
            name="task_update",
            description="Change a task's fields; cannot mark it done.",
            input_model=TaskUpdateIn,
            output_model=TaskUpdateOut,
            risk=RiskLevel.WRITE,
            idempotent=True,
            timeout_s=5.0,
            handler=_update,
        ),
        FunctionTool(
            name="task_complete",
            description="Mark a task done and stamp completed_at.",
            input_model=TaskCompleteIn,
            output_model=TaskCompleteOut,
            risk=RiskLevel.WRITE,
            idempotent=True,
            timeout_s=5.0,
            handler=_complete,
        ),
        FunctionTool(
            name="task_delete",
            description="Permanently delete a task and its subtasks.",
            input_model=TaskDeleteIn,
            output_model=TaskDeleteOut,
            risk=RiskLevel.IRREVERSIBLE,
            idempotent=True,
            timeout_s=5.0,
            handler=_delete,
        ),
    ]
