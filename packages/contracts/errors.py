"""Tool-level refusals.

Every message here is safe to show to the model: no secrets, no provider text,
no host paths. Anything a provider says stays in logs behind the redactor.
"""

from __future__ import annotations


class ToolError(Exception):
    """Base class for refusals a tool raises. Fail closed by default."""


class BudgetExceeded(ToolError):
    """The monthly ceiling would be crossed. Raised for EXTERNAL/IRREVERSIBLE only."""


class TaintedRefused(ToolError):
    """This turn contains untrusted input, so external effects are refused."""


class ApprovalRequired(ToolError):
    """A human decision is required before this call may proceed."""


class NotConfigured(ToolError):
    """The provider credentials for this tool are absent. Refuse, do not fake."""


class CallerIdNotOwned(ToolError):
    """The caller ID is not a verified row in phone_lines. Fraud guard (T5)."""


class PolicyViolation(ToolError):
    """The tool list or risk value handed to the model was not legal."""
