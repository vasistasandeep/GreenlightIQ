"""Root pytest configuration for the backend test suite.

On Windows, Python's default asyncio loop is the ``ProactorEventLoop``, which
psycopg's async mode cannot use (it raises ``InterfaceError`` on connect). The
async integration tests (which open a real ``AsyncConnection`` to Postgres)
therefore need the ``SelectorEventLoop``. Setting the selector policy at import
time -- before pytest-asyncio creates any loop -- makes every async test use a
psycopg-compatible loop. This is a no-op on non-Windows platforms.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform.startswith("win"):
    # Must be set before pytest-asyncio instantiates the event loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())