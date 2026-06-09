"""Tests for mcp_server.infrastructure.upstream_governor.

The governor bounds concurrent in-flight calls to a single-process upstream
MCP child, across handlers running on independent worker-thread event loops.
"""

import asyncio
import threading
import time

import pytest

from mcp_server.infrastructure import upstream_governor as gov


@pytest.fixture(autouse=True)
def _reset_governor():
    gov.reset()
    yield
    gov.reset()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_default_budget_is_one():
    """A server with no explicit config serialises (one permit)."""

    async def body():
        async with gov.govern("codebase"):
            return gov.current_budget("codebase")

    assert _run(body()) == 1


def test_explicit_budget_is_honoured():
    async def body():
        async with gov.govern("srv", max_concurrent=3):
            return gov.current_budget("srv")

    assert _run(body()) == 3


def test_first_use_fixes_budget():
    """The first caller's budget sticks; later callers reuse it."""

    async def first():
        async with gov.govern("srv", max_concurrent=2):
            pass

    _run(first())

    async def second():
        async with gov.govern("srv", max_concurrent=99):
            return gov.current_budget("srv")

    assert _run(second()) == 2


def test_permit_released_on_exception():
    """The permit must be returned even if the governed body raises."""

    async def boom():
        async with gov.govern("srv", max_concurrent=1):
            raise ValueError("x")

    with pytest.raises(ValueError):
        _run(boom())

    # If the permit leaked, this second acquire would block forever; the
    # test would hang rather than pass.
    async def ok():
        async with gov.govern("srv", max_concurrent=1):
            return True

    assert _run(ok()) is True


def test_serialises_across_threads_and_loops():
    """Two callers on independent event loops in separate threads must not
    hold a single permit simultaneously — the core cross-loop guarantee a
    plain asyncio.Semaphore cannot give (it is bound to one loop)."""
    overlap = {"max": 0, "cur": 0}
    lock = threading.Lock()

    async def worker():
        async with gov.govern("codebase", max_concurrent=1):
            with lock:
                overlap["cur"] += 1
                overlap["max"] = max(overlap["max"], overlap["cur"])
            await asyncio.sleep(0.05)
            with lock:
                overlap["cur"] -= 1

    def run_in_thread():
        _run(worker())

    threads = [threading.Thread(target=run_in_thread) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # With one permit, peak concurrency observed inside the critical section
    # must never exceed 1.
    assert overlap["max"] == 1


def test_two_permits_allow_overlap():
    """Sanity: with two permits, two threads CAN overlap (proves the gate is
    the semaphore, not accidental serialisation)."""
    overlap = {"max": 0, "cur": 0}
    lock = threading.Lock()

    async def worker():
        async with gov.govern("srv", max_concurrent=2):
            with lock:
                overlap["cur"] += 1
                overlap["max"] = max(overlap["max"], overlap["cur"])
            await asyncio.sleep(0.05)
            with lock:
                overlap["cur"] -= 1

    threads = [threading.Thread(target=lambda: _run(worker())) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert overlap["max"] == 2
