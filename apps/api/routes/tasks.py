"""Task API.

These routes act for the authenticated operator, who is the principal. The
approval gate exists to stop the *agent* from acting on its own; a human
clicking "delete" is the human acting. The agent path still goes through
``tools/tasks.py`` and the policy engine.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.auth import require_session
from apps.api.db.models import Task, TaskEvent
from apps.api.db.session import session_scope

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskBody(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    detail: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None


class TaskView(BaseModel):
    id: str
    title: str
    detail: str | None
    status: str
    priority: int
    due_at: datetime | None
    completed_at: datetime | None
    source: str


def _view(task: Task) -> TaskView:
    return TaskView(
        id=task.id,
        title=task.title,
        detail=task.detail,
        status=task.status,
        priority=task.priority,
        due_at=task.due_at,
        completed_at=task.completed_at,
        source=task.source,
    )


@router.get("", response_model=list[TaskView])
async def list_tasks(
    status_filter: str | None = None, user_id: str = Depends(require_session)
) -> list[TaskView]:
    async with session_scope() as session:
        stmt = select(Task).where(Task.user_id == user_id)
        if status_filter:
            stmt = stmt.where(Task.status == status_filter)
        rows = (
            (await session.execute(stmt.order_by(Task.priority, Task.created_at))).scalars().all()
        )
        return [_view(row) for row in rows]


@router.post("", response_model=TaskView, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskBody, user_id: str = Depends(require_session)) -> TaskView:
    if not body.title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "title is required")
    async with session_scope() as session:
        task = Task(
            user_id=user_id,
            title=body.title,
            detail=body.detail,
            priority=body.priority or 3,
            due_at=body.due_at,
            source="user",
        )
        session.add(task)
        await session.flush()
        session.add(TaskEvent(task_id=task.id, event="created", payload={"by": "operator"}))
        return _view(task)


@router.patch("/{task_id}", response_model=TaskView)
async def patch_task(
    task_id: str, body: TaskBody, user_id: str = Depends(require_session)
) -> TaskView:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such task")
        if body.title is not None:
            task.title = body.title
        if body.detail is not None:
            task.detail = body.detail
        if body.priority is not None:
            task.priority = body.priority
        if body.due_at is not None:
            task.due_at = body.due_at
        if body.status is not None:
            task.status = body.status
            if body.status == "done" and task.completed_at is None:
                task.completed_at = datetime.now(tz=task.created_at.tzinfo)
            session.add(TaskEvent(task_id=task.id, event="status", payload={"to": body.status}))
        return _view(task)


@router.delete("/{task_id}")
async def delete_task(task_id: str, user_id: str = Depends(require_session)) -> dict[str, bool]:
    async with session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such task")
        await session.delete(task)
        return {"deleted": True}
