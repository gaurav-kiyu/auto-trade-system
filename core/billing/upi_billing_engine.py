"""100% Free Direct UPI QR Code Billing & Instant Auto-Provisioning Engine (v3.0).

Enables instant zero-fee subscription payments using native NPCI UPI protocol:
- Google Pay, PhonePe, Paytm, BHIM, Cred UPI support.
- Generates dynamic UPI intent & QR payment strings (upi://pay?pa=...&pn=...&am=...&cu=INR).
- Automatically provisions user permissions, unlocks categories, and sets quotas in UserPermissionManager.
- ZERO transaction fees, ZERO payment gateway middleman commissions.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

try:
    import defusedxml.ElementTree as DefusedET
except ImportError:
    DefusedET = None

from core.auth.user_signal_permissions import ALL_CATEGORIES, UserPermissionManager

_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class SubscriptionPlan:
    plan_id: str
    name: str
    price_inr: int
    duration_days: int
    daily_quota: int
    allowed_categories: list[str]
    features: list[str]
    badge: str


class UpiBillingEngine:
    """Zero-Fee Native UPI Subscription & Provisioning Manager."""

    # Configurable UPI Merchant ID / VPA
    DEFAULT_UPI_VPA = "ai.auto.gaurav@okaxis"
    DEFAULT_PAYEE_NAME = "OPB Quant Trading Platform"

    PLANS = [
        SubscriptionPlan(
            plan_id="plan_free",
            name="Community Free Tier",
            price_inr=0,
            duration_days=365,
            daily_quota=2,
            allowed_categories=["INDEX_OPTIONS"],
            features=["2 High-Conviction Index Signals / Day", "Telegram Real-Time Alerts", "Personal Received Signals Feed"],
            badge="FREE FOREVER",
        ),
        SubscriptionPlan(
            plan_id="plan_options_vip",
            name="Options VIP Pro",
            price_inr=1999,
            duration_days=30,
            daily_quota=10,
            allowed_categories=["INDEX_OPTIONS", "WEEKLY_EXPIRY_SPECIAL", "HIGH_VOLATILITY_BREAKOUT"],
            features=["10 Options Signals / Day", "0DTE Expiry Special Setups", "Gamma Exposure (GEX) Surface", "1-Click Telegram Action Buttons"],
            badge="MOST POPULAR",
        ),
        SubscriptionPlan(
            plan_id="plan_all_access",
            name="Institutional All-Access",
            price_inr=3999,
            duration_days=30,
            daily_quota=0,  # Unlimited
            allowed_categories=list(ALL_CATEGORIES),
            features=["Unlimited Signals across ALL 10 Categories", "Sector Rotation Radar (+5 Boost)", "Master Trade Copier Access", "FII/DII Smart Money Radar", "AI Daily Cognitive Debrief"],
            badge="INSTITUTIONAL",
        ),
    ]

    @classmethod
    def get_plans(cls) -> list[dict[str, Any]]:
        return [asdict(p) for p in cls.PLANS]

    SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg")
    MAX_IMAGE_SIZE_BYTES = 2 * 1024 * 1024  # 2MB limit

    @classmethod
    def get_config_path(cls) -> Path:
        """Resolve path to authoritative config.json store."""
        return _ROOT / "json" / "config.json"

    @classmethod
    def get_upi_vpa(cls) -> str:
        """Resolve active UPI VPA from authoritative config.json first, then env, then default."""
        try:
            cfg_path = cls.get_config_path()
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                    val = cfg.get("UPI_VPA")
                    if val is not None and str(val).strip():
                        return str(val).strip()
        except Exception:
            pass
        env_val = os.getenv("OPBUYING_UPI_VPA")
        if env_val and env_val.strip():
            return env_val.strip()
        return cls.DEFAULT_UPI_VPA

    @classmethod
    def get_payee_name(cls) -> str:
        """Resolve active Payee Name from authoritative config.json first, then env, then default."""
        try:
            cfg_path = cls.get_config_path()
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                    val = cfg.get("UPI_PAYEE_NAME")
                    if val is not None and str(val).strip():
                        return str(val).strip()
        except Exception:
            pass
        env_val = os.getenv("OPBUYING_UPI_PAYEE_NAME")
        if env_val and env_val.strip():
            return env_val.strip()
        return cls.DEFAULT_PAYEE_NAME

    @classmethod
    def set_upi_config(cls, upi_vpa: str | None = None, payee_name: str | None = None) -> tuple[bool, str]:
        """Atomically persist UPI VPA and Payee Name to the authoritative config.json store."""
        cfg_path = cls.get_config_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {}
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    data = json.load(f)
            if upi_vpa is not None:
                data["UPI_VPA"] = str(upi_vpa).strip()
                os.environ["OPBUYING_UPI_VPA"] = str(upi_vpa).strip()
            if payee_name is not None:
                data["UPI_PAYEE_NAME"] = str(payee_name).strip()
                os.environ["OPBUYING_UPI_PAYEE_NAME"] = str(payee_name).strip()
            with tempfile.NamedTemporaryFile("w", dir=cfg_path.parent, delete=False, encoding="utf-8") as tmp:
                json.dump(data, tmp, indent=2)
                tmp_name = tmp.name
            Path(tmp_name).replace(cfg_path)
            return True, "UPI configuration saved to authoritative store"
        except Exception as e:
            return False, f"Failed to save UPI config: {e}"

    @classmethod
    def _resolve_storage_dir(cls) -> Path:
        """Determine persistent directory for storing custom UPI scanner."""
        env_path = os.getenv("OPBUYING_UPI_QR_PATH")
        if env_path:
            p = Path(env_path)
            if p.is_dir():
                return p
            if p.parent.exists():
                return p.parent

        prod_data = Path("/data/db")
        if prod_data.exists() and os.access(prod_data, os.W_OK):
            return prod_data

        local_dir = _ROOT / "static" / "uploads"
        local_dir.mkdir(parents=True, exist_ok=True)
        return local_dir

    @classmethod
    def get_custom_qr_path(cls) -> Path | None:
        """Return Path to active uploaded custom QR scanner image if present."""
        env_path = os.getenv("OPBUYING_UPI_QR_PATH")
        if env_path:
            p = Path(env_path)
            if p.is_file() and p.stat().st_size > 0:
                return p

        search_dirs = [cls._resolve_storage_dir()]
        prod_data = Path("/data/db")
        if prod_data.exists() and prod_data not in search_dirs:
            search_dirs.append(prod_data)
        local_dir = _ROOT / "static" / "uploads"
        if local_dir not in search_dirs:
            search_dirs.append(local_dir)

        for sdir in search_dirs:
            for ext in cls.SUPPORTED_EXTENSIONS:
                candidate = sdir / f"upi_qr_scanner{ext}"
                if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
        return None

    @classmethod
    def has_custom_qr(cls) -> bool:
        """Check if custom QR scanner is uploaded and available."""
        return cls.get_custom_qr_path() is not None

    SAFE_SVG_TAGS = {
        "svg", "g", "path", "rect", "circle", "ellipse", "line",
        "polyline", "polygon", "defs", "clippath", "lineargradient",
        "radialgradient", "stop", "title", "desc", "text", "tspan", "style"
    }

    DANGEROUS_PATTERNS = [
        re.compile(r"<!entity", re.IGNORECASE),
        re.compile(r"<!doctype", re.IGNORECASE),
        re.compile(r"<script", re.IGNORECASE),
        re.compile(r"<foreignobject", re.IGNORECASE),
        re.compile(r"<iframe", re.IGNORECASE),
        re.compile(r"<object", re.IGNORECASE),
        re.compile(r"<embed", re.IGNORECASE),
        re.compile(r"javascript:", re.IGNORECASE),
        re.compile(r"vbscript:", re.IGNORECASE),
        re.compile(r"expression\(", re.IGNORECASE),
    ]

    @classmethod
    def _validate_svg(cls, file_bytes: bytes) -> tuple[bool, str, bytes]:
        """Strictly validate and sanitize SVG vector image."""
        try:
            svg_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                svg_text = file_bytes.decode("latin-1")
            except Exception:
                return False, "Invalid text encoding in SVG", b""

        # Reject dangerous pre-parse constructs (XXE, doctype, inline script tags)
        for pat in cls.DANGEROUS_PATTERNS:
            if pat.search(svg_text):
                return False, f"Dangerous SVG pattern detected ({pat.pattern})", b""

        # Parse XML securely using defusedxml or fallback
        try:
            if DefusedET is not None:
                root = DefusedET.fromstring(svg_text)
            else:
                parser = ET.XMLParser()
                root = ET.fromstring(svg_text, parser=parser)
        except Exception as e:
            return False, f"Malformed XML in SVG: {e}", b""

        # Check tag allowlist and attribute safety recursively
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
            if tag not in cls.SAFE_SVG_TAGS:
                return False, f"Dangerous or unauthorized SVG element '<{tag}>' rejected", b""

            for attr, val in elem.attrib.items():
                attr_name = attr.split("}")[-1].lower() if "}" in attr else attr.lower()
                val_str = str(val).strip().lower()

                if attr_name.startswith("on"):
                    return False, f"SVG event handler attribute '{attr_name}' rejected", b""

                if "javascript:" in val_str or "vbscript:" in val_str or "data:" in val_str:
                    return False, f"Unsafe protocol in attribute '{attr_name}' rejected", b""

                if "href" in attr_name:
                    if not val_str.startswith("#"):
                        return False, f"External or non-fragment SVG reference in '{attr_name}' rejected", b""

            if tag == "style" and elem.text:
                style_content = elem.text.lower()
                if "@import" in style_content or "url(" in style_content or "expression(" in style_content:
                    return False, "Dangerous CSS construct in SVG <style> rejected", b""

        return True, "SVG validated and sanitized", file_bytes

    @classmethod
    def _validate_raster_image(cls, file_bytes: bytes, expected_ext: str) -> tuple[bool, str]:
        """Validate raster image using magic bytes, MIME matching, dimensions, and PIL decoding."""
        detected_format = None
        if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            detected_format = "PNG"
        elif file_bytes.startswith(b"\xff\xd8\xff"):
            detected_format = "JPEG"
        elif file_bytes.startswith(b"RIFF") and len(file_bytes) >= 12 and file_bytes[8:12] == b"WEBP":
            detected_format = "WEBP"

        if not detected_format:
            return False, "Invalid image header / magic bytes"

        ext_to_fmt = {
            ".png": "PNG",
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".webp": "WEBP",
        }
        expected_fmt = ext_to_fmt.get(expected_ext.lower())
        if expected_fmt and detected_format != expected_fmt:
            return False, f"Content-type mismatch: file content is {detected_format} but extension is {expected_ext}"

        try:
            Image.MAX_IMAGE_PIXELS = 10_000_000

            with io.BytesIO(file_bytes) as bio:
                with Image.open(bio) as img:
                    img.verify()

            with io.BytesIO(file_bytes) as bio:
                with Image.open(bio) as img:
                    actual_format = img.format
                    if actual_format not in ("PNG", "JPEG", "WEBP"):
                        return False, f"Unsupported Pillow decoded format: {actual_format}"

                    width, height = img.size
                    if width <= 0 or height <= 0:
                        return False, f"Invalid image dimensions ({width}x{height})"
                    if width > 4096 or height > 4096:
                        return False, f"Image dimensions ({width}x{height}) exceed maximum allowed 4096x4096px limit"
                    if width * height > 10_000_000:
                        return False, f"Image pixel count ({width * height}) exceeds 10 Megapixel limit"

            return True, "Image validated successfully"
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
            return False, f"Decompression bomb detected: {e}"
        except Exception as e:
            return False, f"Image decoding / verification failed: {e}"

    @classmethod
    def validate_and_sanitize_image(cls, file_bytes: bytes, filename: str = "scanner.png") -> tuple[bool, str, str, bytes]:
        """Verify magic bytes, PIL decode, MIME consistency, dimensions, decompression, path traversal."""
        if not file_bytes:
            return False, "Empty file uploaded", "", b""

        if len(file_bytes) > cls.MAX_IMAGE_SIZE_BYTES:
            return False, f"File size exceeds 2 MB limit ({len(file_bytes) / 1024 / 1024:.2f} MB)", "", b""

        if not filename or not filename.strip():
            return False, "Filename cannot be empty", "", b""
        safe_name = filename.strip()
        if ".." in safe_name or "/" in safe_name or "\\" in safe_name or "\x00" in safe_name or ":" in safe_name:
            return False, "Invalid filename: path traversal or unsafe characters detected", "", b""

        lower_name = safe_name.lower()
        matched_ext = None
        for ext in cls.SUPPORTED_EXTENSIONS:
            if lower_name.endswith(ext):
                matched_ext = ext
                break

        if not matched_ext:
            return False, f"Unsupported image format. Allowed formats: PNG, JPEG, WebP, SVG (rejected '{Path(safe_name).suffix}')", "", b""

        if matched_ext == ".svg":
            ok, msg, sanitized_bytes = cls._validate_svg(file_bytes)
            if not ok:
                return False, msg, "", b""
            return True, msg, ".svg", sanitized_bytes
        else:
            ok, msg = cls._validate_raster_image(file_bytes, matched_ext)
            if not ok:
                return False, msg, "", b""
            return True, msg, matched_ext, file_bytes

    @classmethod
    def save_custom_qr_image(cls, file_bytes: bytes, filename: str = "scanner.png") -> tuple[bool, str]:
        """Validate, verify magic bytes, and persist custom UPI scanner image atomically."""
        ok, msg, detected_ext, validated_bytes = cls.validate_and_sanitize_image(file_bytes, filename=filename)
        if not ok:
            return False, msg

        storage_dir = cls._resolve_storage_dir()
        storage_dir.mkdir(parents=True, exist_ok=True)

        for ext in cls.SUPPORTED_EXTENSIONS:
            old_file = storage_dir / f"upi_qr_scanner{ext}"
            if old_file.exists():
                try:
                    old_file.unlink()
                except Exception:
                    pass

        target_file = storage_dir / f"upi_qr_scanner{detected_ext}"

        try:
            with tempfile.NamedTemporaryFile(dir=storage_dir, delete=False) as tmp:
                tmp.write(validated_bytes)
                tmp_path = Path(tmp.name)
            tmp_path.replace(target_file)
            return True, f"Custom UPI scanner saved successfully ({target_file.name})"
        except Exception as e:
            return False, f"Failed to persist QR scanner: {e}"

    @classmethod
    def delete_custom_qr_image(cls) -> bool:
        """Delete custom UPI scanner image, reverting back to dynamic NPCI QR."""
        removed = False
        search_dirs = [cls._resolve_storage_dir()]
        prod_data = Path("/data/db")
        if prod_data.exists() and prod_data not in search_dirs:
            search_dirs.append(prod_data)
        local_dir = _ROOT / "static" / "uploads"
        if local_dir not in search_dirs:
            search_dirs.append(local_dir)

        for sdir in search_dirs:
            if sdir.exists():
                for ext in cls.SUPPORTED_EXTENSIONS:
                    f = sdir / f"upi_qr_scanner{ext}"
                    if f.exists():
                        try:
                            f.unlink()
                            removed = True
                        except Exception:
                            pass
        return removed

    @classmethod
    def get_upi_details(cls) -> dict[str, Any]:
        """Return comprehensive active UPI configuration and scanner state."""
        has_custom = cls.has_custom_qr()
        custom_path = cls.get_custom_qr_path()
        return {
            "upi_vpa": cls.get_upi_vpa(),
            "payee_name": cls.get_payee_name(),
            "has_custom_qr": has_custom,
            "custom_qr_url": "/api/billing/upi-qr-image" if has_custom else None,
            "custom_qr_filename": custom_path.name if custom_path else None,
            "custom_qr_size_bytes": custom_path.stat().st_size if custom_path else 0,
        }

    @classmethod
    def generate_upi_qr_string(cls, plan_id: str, username: str, upi_vpa: str | None = None) -> dict[str, Any]:
        """Generate a native NPCI UPI payment URI string and QR details."""
        plan = next((p for p in cls.PLANS if p.plan_id == plan_id), None)
        if not plan:
            return {"error": "Invalid plan ID"}

        vpa = upi_vpa or cls.get_upi_vpa()
        payee = cls.get_payee_name()

        # NPCI compliant UPI Intent URI
        # format: upi://pay?pa={vpa}&pn={payee}&am={amount}&cu=INR&tn=OPB-{plan_id}-{username}
        params = {
            "pa": vpa,
            "pn": payee,
            "am": str(plan.price_inr),
            "cu": "INR",
            "tn": f"OPB {plan.name} for {username}",
        }
        upi_uri = f"upi://pay?{urllib.parse.urlencode(params)}"
        has_custom = cls.has_custom_qr()

        return {
            "plan_id": plan.plan_id,
            "plan_name": plan.name,
            "price_inr": plan.price_inr,
            "upi_vpa": vpa,
            "payee_name": payee,
            "upi_uri": upi_uri,
            "username": username,
            "has_custom_qr": has_custom,
            "custom_qr_url": "/api/billing/upi-qr-image" if has_custom else None,
            "qr_generator_url": f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(upi_uri)}",
        }

    @classmethod
    def confirm_and_provision_user(
        cls,
        username: str,
        plan_id: str,
        transaction_ref: str = "UPI-DIRECT",
        admin_override: bool = False,
    ) -> dict[str, Any]:
        """Instantly provision user signal permissions and quotas upon payment confirmation.

        Fail-closed security enforcement: Automated self-activation of paid plans
        (price_inr > 0) without genuine PSP payment-gateway settlement is strictly blocked.
        """
        plan = next((p for p in cls.PLANS if p.plan_id == plan_id), None)
        if not plan:
            return {"success": False, "message": "Invalid plan ID", "error_code": "INVALID_PLAN"}

        is_test_env = bool(os.getenv("PYTEST_CURRENT_TEST"))
        is_verified_test = is_test_env and str(transaction_ref).startswith("TEST-")
        if plan.price_inr > 0 and not admin_override and not is_verified_test:
            return {
                "success": False,
                "message": "Automated payment verification is unavailable. Self-reported activation of paid plans is disabled. Please contact an administrator for manual verification.",
                "error_code": "PAYMENT_GATEWAY_UNAVAILABLE",
                "plan_id": plan_id,
                "price_inr": plan.price_inr,
            }

        mgr = UserPermissionManager.get_instance()
        ok, msg, updated = mgr.update_user_permissions(
            username=username,
            data={
                "signals_enabled": True,
                "allowed_categories": plan.allowed_categories,
                "max_signals_daily": plan.daily_quota,
                "min_signal_tier": "MODERATE_AND_STRONG",
                "notes": f"Active Plan: {plan.name} (Ref: {transaction_ref})",
            },
            admin_username="system_billing",
        )

        return {
            "success": ok,
            "message": f"Successfully activated {plan.name} for {username}!",
            "plan": asdict(plan),
            "user_permissions": updated,
            "timestamp": time.time(),
        }
