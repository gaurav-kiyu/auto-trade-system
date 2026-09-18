"""Tests for BIJobRunner thread isolation, caching, deduplication, and concurrency."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from core.bi_job_runner import BIJobRunner


@pytest.fixture(autouse=True)
def clean_bi_runner():
    runner = BIJobRunner.get_instance()
    runner.clear_cache()
    yield
    runner.clear_cache()


@pytest.mark.asyncio
async def test_bi_runner_singleton():
    r1 = BIJobRunner.get_instance()
    r2 = BIJobRunner.get_instance()
    assert r1 is r2


@pytest.mark.asyncio
async def test_bi_runner_caching():
    runner = BIJobRunner.get_instance()
    mock_compute = MagicMock(return_value={"status": "ok", "value": 42})

    # First call - computes
    res1 = await runner.execute_isolated("test_key", mock_compute, max_age=10.0)
    assert res1 == {"status": "ok", "value": 42}
    assert mock_compute.call_count == 1

    # Second call - returns cached without computing again
    res2 = await runner.execute_isolated("test_key", mock_compute, max_age=10.0)
    assert res2 == {"status": "ok", "value": 42}
    assert mock_compute.call_count == 1

    # Force refresh - re-computes
    mock_compute.return_value = {"status": "refreshed", "value": 100}
    res3 = await runner.execute_isolated("test_key", mock_compute, max_age=10.0, force_refresh=True)
    assert res3 == {"status": "refreshed", "value": 100}
    assert mock_compute.call_count == 2


@pytest.mark.asyncio
async def test_bi_runner_ttl_expiry():
    runner = BIJobRunner.get_instance()
    mock_compute = MagicMock(side_effect=[{"v": 1}, {"v": 2}])

    res1 = await runner.execute_isolated("ttl_key", mock_compute, max_age=0.1)
    assert res1 == {"v": 1}
    assert mock_compute.call_count == 1

    # Wait for TTL to expire
    await asyncio.sleep(0.15)

    res2 = await runner.execute_isolated("ttl_key", mock_compute, max_age=0.1)
    assert res2 == {"v": 2}
    assert mock_compute.call_count == 2


@pytest.mark.asyncio
async def test_bi_runner_non_blocking_event_loop():
    """Verify that a heavy synchronous workload in BIJobRunner does not starve the event loop."""
    runner = BIJobRunner.get_instance()

    def heavy_sync_work():
        time.sleep(0.3)
        return "heavy_done"

    event_loop_ticks = 0

    async def lightweight_loop_task():
        nonlocal event_loop_ticks
        for _ in range(10):
            await asyncio.sleep(0.02)
            event_loop_ticks += 1

    t0 = time.perf_counter()
    heavy_task = asyncio.create_task(
        runner.execute_isolated("heavy_task", heavy_sync_work, max_age=10.0, force_refresh=True)
    )
    light_task = asyncio.create_task(lightweight_loop_task())

    heavy_result, _ = await asyncio.gather(heavy_task, light_task)
    total_time = time.perf_counter() - t0

    assert heavy_result == "heavy_done"
    # The event loop ticked multiple times while the heavy worker ran in background thread
    assert event_loop_ticks >= 8
    # Total elapsed should be around the time of the heavy task, proving concurrent execution
    assert 0.25 <= total_time < 0.60


@pytest.mark.asyncio
async def test_bi_runner_concurrent_deduplication():
    """Verify concurrent requests for the same key do not compute twice."""
    runner = BIJobRunner.get_instance()
    compute_count = 0

    def slow_compute():
        nonlocal compute_count
        compute_count += 1
        time.sleep(0.2)
        return {"dedup": True, "count": compute_count}

    # Launch two simultaneous requests for the same uncached key
    t1 = asyncio.create_task(runner.execute_isolated("dedup_key", slow_compute, max_age=10.0))
    t2 = asyncio.create_task(runner.execute_isolated("dedup_key", slow_compute, max_age=10.0))

    r1, r2 = await asyncio.gather(t1, t2)
    assert r1 == {"dedup": True, "count": 1}
    assert r2 == {"dedup": True, "count": 1}
    assert compute_count == 1


@pytest.mark.asyncio
async def test_bi_concurrency_with_health_endpoint():
    """Verify /health route responds instantly while a heavy BI job is executing."""
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()
    runner = BIJobRunner.get_instance()

    @app.get("/health")
    async def health():
        return JSONResponse({"status": "ok", "app": "opb", "ts": time.time()})

    @app.get("/api/heavy-bi")
    async def heavy_bi():
        def _expensive():
            time.sleep(0.3)
            return {"bi_metrics": 999}
        result = await runner.execute_isolated("expensive_bi_route", _expensive, max_age=10.0, force_refresh=True)
        return JSONResponse(result)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Start heavy request in background
        heavy_future = asyncio.create_task(client.get("/api/heavy-bi"))

        # Wait a moment for heavy job to start
        await asyncio.sleep(0.05)

        # Health endpoint should respond immediately without being blocked
        h_start = time.perf_counter()
        health_resp = await client.get("/health")
        h_latency = time.perf_counter() - h_start

        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"
        # /health latency should be very small (< 100ms) even while heavy job is running
        assert h_latency < 0.10, f"Health endpoint was blocked! Latency was {h_latency:.4f}s"

        heavy_resp = await heavy_future
        assert heavy_resp.status_code == 200
        assert heavy_resp.json()["bi_metrics"] == 999
