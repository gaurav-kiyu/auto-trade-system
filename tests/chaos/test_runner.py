"""
Chaos: Orchestrated Runner
"""
import pytest


@pytest.mark.parametrize("module_name", [
    "tests.chaos.test_broker_outage",
    "tests.chaos.test_ack_timeout",
    "tests.chaos.ztest_stale_feed",
    "tests.chaos.test_reconnect_storm",
    "tests.chaos.test_partial_fill_disconnect",
    "tests.chaos.test_db_corruption",
    "tests.chaos.test_auth_expiry",
    "tests.chaos.test_restart_mid_session",
])
def test_chaos_module_imports(module_name):
    __import__(module_name)
