"""Shared fixtures for API tests.

``client`` and ``login`` were defined inside ``test_api.py``, so any other module in
this directory silently had no app to talk to. Re-exported here so the voice tests
use the same authenticated app instead of building a second one.
"""

from __future__ import annotations

from tests.api.test_api import client

__all__ = ["client"]
