"""Unit tests for the Zero-Cost Commercial & Operational Suite (v3.0)."""

from core.billing.upi_billing_engine import UpiBillingEngine
from core.backup.disaster_recovery import DisasterRecoveryEngine


def test_upi_billing_engine():
    plans = UpiBillingEngine.get_plans()
    assert len(plans) == 3
    assert any(p["plan_id"] == "plan_free" for p in plans)
    assert any(p["plan_id"] == "plan_options_vip" for p in plans)
    assert any(p["plan_id"] == "plan_all_access" for p in plans)

    # Test UPI QR string generation
    qr_data = UpiBillingEngine.generate_upi_qr_string("plan_options_vip", "test_trader")
    assert "upi_uri" in qr_data
    assert qr_data["upi_uri"].startswith("upi://pay?")
    assert "1999" in qr_data["upi_uri"]

    # Test auto-provisioning
    prov_res = UpiBillingEngine.confirm_and_provision_user("test_client", "plan_options_vip", "TEST-UPI-REF")
    assert prov_res["success"] is True
    assert "Options VIP Pro" in prov_res["message"]
    assert prov_res["user_permissions"]["signals_enabled"] is True
    assert "INDEX_OPTIONS" in prov_res["user_permissions"]["allowed_categories"]


def test_disaster_recovery_engine():
    # 1. Create snapshot
    meta = DisasterRecoveryEngine.create_snapshot()
    assert meta["snapshot_id"].startswith("SNAP_")
    assert meta["size_bytes"] > 0
    assert len(meta["sha256_checksum"]) == 64
    assert len(meta["files_included"]) >= 2

    # 2. List snapshots
    snaps = DisasterRecoveryEngine.list_snapshots()
    assert len(snaps) >= 1
    assert any(s["snapshot_id"] == meta["snapshot_id"] for s in snaps)

    # 3. Test Restore utility
    rest_res = DisasterRecoveryEngine.restore_snapshot(meta["snapshot_id"])
    assert rest_res["success"] is True
    assert rest_res["snapshot_id"] == meta["snapshot_id"]
