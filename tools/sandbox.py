"""Sandbox tools: allowlisted shell, Python, and browser automation.

The runner (``docker exec`` into a rootless, read-only, egress-filtered
container) is week 7 work and is not implemented in this build. What *is*
implemented is the part that decides whether a call is even allowed: the
binary allowlist, the approval rule that shows the full command, and a
fail-closed refusal when the image is not configured.

That split is deliberate. An unimplemented runner that refuses is safe; an
implemented runner without the allowlist is not.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from pydantic import BaseModel, Field

from apps.api.config import get_settings
from packages.contracts.errors import NotConfigured, ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from tools.base import FunctionTool

# Binaries that are safe to run unattended inside the sandbox. Anything else
# needs a human, and the human sees the command.
BINARY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "awk",
        "cat",
        "cut",
        "diff",
        "echo",
        "find",
        "git",
        "grep",
        "head",
        "jq",
        "ls",
        "mkdir",
        "playwright",
        "python",
        "python3",
        "sed",
        "sort",
        "tail",
        "tr",
        "uniq",
        "wc",
    }
)


def _require_sandbox() -> str:
    image = get_settings().sandbox_image
    if not image:
        raise NotConfigured(
            "sandbox is not configured: SANDBOX_IMAGE is empty (runner ships in week 7)"
        )
    return image


class ShellIn(BaseModel):
    command: str = Field(min_length=1)
    cwd: str = Field(default="/workspace")


class ShellOut(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool = False


class PythonRunIn(BaseModel):
    code: str = Field(min_length=1)
    stdin: str | None = None


class PythonRunOut(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


class BrowserOpenIn(BaseModel):
    url: str


class BrowserOpenOut(BaseModel):
    url: str
    title: str


class BrowserClickIn(BaseModel):
    selector: str


class BrowserClickOut(BaseModel):
    clicked: bool
    selector: str


class BrowserExtractIn(BaseModel):
    url: str
    selector: str


class BrowserExtractOut(BaseModel):
    text: list[str]
    tainted: bool = True


def _binary_of(command: str) -> str:
    try:
        parts: Sequence[str] = shlex.split(command)
    except ValueError as exc:
        raise ToolError("command could not be parsed") from exc
    if not parts:
        raise ToolError("empty command")
    head = parts[0].rsplit("/", 1)[-1]
    return head


def _shell_needs_approval(args: BaseModel, ctx: ToolContext) -> bool:
    del ctx
    if not isinstance(args, ShellIn):
        return True
    try:
        return _binary_of(args.command) not in BINARY_ALLOWLIST
    except ToolError:
        return True  # unparseable command: fail closed and ask


async def _shell(a: ShellIn, ctx: ToolContext) -> ShellOut:
    del ctx
    _require_sandbox()
    if _binary_of(a.command) not in BINARY_ALLOWLIST and not a.command:
        raise ToolError("refused")
    raise NotConfigured("sandbox runner is not implemented in this build")


async def _python(a: PythonRunIn, ctx: ToolContext) -> PythonRunOut:
    del a, ctx
    _require_sandbox()
    raise NotConfigured("sandbox runner is not implemented in this build")


async def _browser_open(a: BrowserOpenIn, ctx: ToolContext) -> BrowserOpenOut:
    del a, ctx
    _require_sandbox()
    raise NotConfigured("sandbox runner is not implemented in this build")


async def _browser_click(a: BrowserClickIn, ctx: ToolContext) -> BrowserClickOut:
    del a, ctx
    _require_sandbox()
    raise NotConfigured("sandbox runner is not implemented in this build")


async def _browser_extract(a: BrowserExtractIn, ctx: ToolContext) -> BrowserExtractOut:
    del a, ctx
    _require_sandbox()
    raise NotConfigured("sandbox runner is not implemented in this build")


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="shell",
            description="Run one shell command inside the sandbox and return its output.",
            input_model=ShellIn,
            output_model=ShellOut,
            risk=RiskLevel.WRITE,
            idempotent=False,
            timeout_s=900.0,
            handler=_shell,
            approval=_shell_needs_approval,
        ),
        FunctionTool(
            name="python_run",
            description="Run Python code inside the sandbox and return its output.",
            input_model=PythonRunIn,
            output_model=PythonRunOut,
            risk=RiskLevel.WRITE,
            idempotent=False,
            timeout_s=900.0,
            handler=_python,
        ),
        FunctionTool(
            name="browser_open",
            description="Open a page in the sandboxed browser.",
            input_model=BrowserOpenIn,
            output_model=BrowserOpenOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=60.0,
            handler=_browser_open,
        ),
        FunctionTool(
            name="browser_click",
            description="Click one element in the sandboxed browser.",
            input_model=BrowserClickIn,
            output_model=BrowserClickOut,
            risk=RiskLevel.READ,
            idempotent=False,
            timeout_s=60.0,
            handler=_browser_click,
        ),
        FunctionTool(
            name="browser_extract",
            description="Extract text from a page in the sandboxed browser.",
            input_model=BrowserExtractIn,
            output_model=BrowserExtractOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=60.0,
            taints=True,
            handler=_browser_extract,
        ),
    ]
