"""Workspace file tools. Confined to ``var/workspace`` by resolved path, not by string prefix.

``fs_delete`` is the most dangerous tool in the inventory and had no contract in
SKILL.md (found in review, added as D-37). It is IRREVERSIBLE, always approved,
and cannot leave the workspace root.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from packages.contracts.errors import ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from tools.base import FunctionTool

WORKSPACE = Path(__file__).resolve().parents[1] / "var" / "workspace"
MAX_READ_BYTES = 1_000_000


class FsReadIn(BaseModel):
    path: str = Field(description="Path relative to the agent workspace")


class FsReadOut(BaseModel):
    path: str
    content: str
    truncated: bool


class FsWriteIn(BaseModel):
    path: str
    content: str


class FsWriteOut(BaseModel):
    path: str
    bytes_written: int


class FsDeleteIn(BaseModel):
    path: str


class FsDeleteOut(BaseModel):
    deleted: bool
    path: str


def _resolve(path: str) -> Path:
    root = WORKSPACE.resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ToolError("path escapes the agent workspace") from exc
    return candidate


async def _read(a: FsReadIn, ctx: ToolContext) -> FsReadOut:
    del ctx
    target = _resolve(a.path)
    if not target.is_file():
        raise ToolError("no such file")
    raw = target.read_bytes()
    return FsReadOut(
        path=a.path,
        content=raw[:MAX_READ_BYTES].decode("utf-8", errors="replace"),
        truncated=len(raw) > MAX_READ_BYTES,
    )


async def _write(a: FsWriteIn, ctx: ToolContext) -> FsWriteOut:
    del ctx
    target = _resolve(a.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = a.content.encode("utf-8")
    target.write_bytes(data)
    return FsWriteOut(path=a.path, bytes_written=len(data))


async def _delete(a: FsDeleteIn, ctx: ToolContext) -> FsDeleteOut:
    del ctx
    target = _resolve(a.path)
    if not target.exists():
        return FsDeleteOut(deleted=False, path=a.path)
    if target.is_dir():
        raise ToolError("refusing to delete a directory recursively")
    target.unlink()
    return FsDeleteOut(deleted=True, path=a.path)


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="fs_read",
            description="Read a file from the agent workspace.",
            input_model=FsReadIn,
            output_model=FsReadOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=5.0,
            handler=_read,
        ),
        FunctionTool(
            name="fs_write",
            description="Write a file in the agent workspace.",
            input_model=FsWriteIn,
            output_model=FsWriteOut,
            risk=RiskLevel.WRITE,
            idempotent=True,
            timeout_s=5.0,
            handler=_write,
        ),
        FunctionTool(
            name="fs_delete",
            description="Delete one file from the agent workspace.",
            input_model=FsDeleteIn,
            output_model=FsDeleteOut,
            risk=RiskLevel.IRREVERSIBLE,
            idempotent=True,
            timeout_s=5.0,
            handler=_delete,
        ),
    ]
