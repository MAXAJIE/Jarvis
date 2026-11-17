"""``web_fetch``: the highest-value read tool and the main injection vector (T1).

Rules enforced here, not in a prompt:
* http/https only, no credentials in the URL;
* literal loopback / link-local / RFC1918 hosts refused before any request (T9);
* robots.txt honoured, 10 s timeout, response truncated;
* ``taints=True`` so ``agent.policy`` removes every EXTERNAL/IRREVERSIBLE tool
  from the rest of the turn.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel, Field

from packages.contracts.errors import ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from tools.base import FunctionTool

TIMEOUT_S = 10.0
MAX_BYTES = 200_000
USER_AGENT = "Jarvis/0.1 (+personal assistant; honours robots.txt)"

_client: httpx.AsyncClient | None = None


def use_client(client: httpx.AsyncClient | None) -> None:
    """Test hook. Production leaves this None and we build a client per call."""
    global _client
    _client = client


class WebFetchIn(BaseModel):
    url: str = Field(description="Absolute http(s) URL")


class WebFetchOut(BaseModel):
    url: str
    status: int
    text: str
    truncated: bool
    tainted: bool = True


def _check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise ToolError("credentials in URLs are not allowed")
    host = parsed.hostname
    if not host:
        raise ToolError("URL has no host")
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        raise ToolError("localhost is not reachable from the agent")
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return url
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise ToolError("private and link-local addresses are refused")
    return url


async def _robots_allows(client: httpx.AsyncClient, url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = await client.get(robots_url, timeout=TIMEOUT_S)
    except httpx.HTTPError:
        return True  # no robots.txt reachable: treat as unconstrained
    if response.status_code >= 400:
        return True
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


async def _fetch(a: WebFetchIn, ctx: ToolContext) -> WebFetchOut:
    del ctx  # the deadline is enforced by the caller's timeout, see Tool.timeout_s
    url = _check_url(a.url)
    owned = _client is None
    client = _client or httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        if not await _robots_allows(client, url):
            raise ToolError("robots.txt disallows this URL")
        response = await client.get(url, timeout=TIMEOUT_S)
        body = response.content[:MAX_BYTES]
        encoding = response.encoding or "utf-8"
        text = body.decode(encoding, errors="replace")
        return WebFetchOut(
            url=str(response.url),
            status=response.status_code,
            text=text,
            truncated=len(response.content) > MAX_BYTES,
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"fetch failed: {type(exc).__name__}") from exc
    finally:
        if owned:
            await client.aclose()


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="web_fetch",
            description="Fetch a public web page as text; the result is untrusted.",
            input_model=WebFetchIn,
            output_model=WebFetchOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=TIMEOUT_S,
            taints=True,
            handler=_fetch,
        )
    ]
