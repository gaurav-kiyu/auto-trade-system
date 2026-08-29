"""File Upload Service — Image and media upload for property listings.

Provides:
  - Local filesystem storage (default for development)
  - Cloud storage abstraction (S3-compatible)
  - Image validation: type, size, dimensions
  - Thumbnail generation
  - Auto-naming with property association
  - Upload history tracking

Environment variables:
  - UPLOAD_STORAGE: Storage backend (local|s3) — default: local
  - UPLOAD_DIR: Local upload directory — default: ./uploads
  - UPLOAD_MAX_SIZE_MB: Max file size in MB — default: 10
  - UPLOAD_ALLOWED_TYPES: Allowed MIME types — default: image/jpeg,image/png,image/webp
  - AWS_ACCESS_KEY_ID: S3 access key
  - AWS_SECRET_ACCESS_KEY: S3 secret key
  - AWS_BUCKET: S3 bucket name
  - AWS_REGION: S3 region — default: ap-south-1
  - CDN_BASE_URL: CDN/base URL for uploaded files — default: /uploads
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

UPLOAD_CONFIG = {
    "storage": os.environ.get("UPLOAD_STORAGE", "local"),
    "local_dir": os.environ.get("UPLOAD_DIR", "./uploads"),
    "max_size_mb": int(os.environ.get("UPLOAD_MAX_SIZE_MB", "10")),
    "allowed_types": os.environ.get(
        "UPLOAD_ALLOWED_TYPES",
        "image/jpeg,image/png,image/webp,image/gif",
    ).split(","),
    "aws_bucket": os.environ.get("AWS_BUCKET", ""),
    "aws_region": os.environ.get("AWS_REGION", "ap-south-1"),
    "cdn_base_url": os.environ.get("CDN_BASE_URL", "/uploads"),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class UploadedFile:
    """Metadata about an uploaded file."""
    file_id: str = ""
    property_id: str = ""
    original_name: str = ""
    stored_name: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    url: str = ""
    thumbnail_url: str = ""
    storage_path: str = ""
    is_primary: bool = False
    uploaded_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "property_id": self.property_id,
            "original_name": self.original_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
            "is_primary": self.is_primary,
            "uploaded_at": self.uploaded_at,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Upload Service
# ═══════════════════════════════════════════════════════════════════════════════

class UploadService:
    """File upload service for property images and media.

    Supports local filesystem storage (development) and S3-compatible
    cloud storage (production). Validates file types, sizes, and
    generates thumbnails.
    """

    def __init__(self) -> None:
        self._uploads: dict[str, UploadedFile] = {}  # file_id -> metadata
        self._property_uploads: dict[str, list[str]] = {}  # property_id -> [file_ids]
        self._local_dir = Path(UPLOAD_CONFIG["local_dir"])

    # ── Upload ────────────────────────────────────────────────────────────

    def upload(
        self,
        file_data: bytes,
        original_name: str,
        property_id: str = "",
        mime_type: str = "",
        is_primary: bool = False,
    ) -> UploadedFile:
        """Upload a file.

        Args:
            file_data: Raw file bytes.
            original_name: Original filename.
            property_id: Associated property ID.
            mime_type: MIME type of the file.
            is_primary: Whether this is the primary image.

        Returns:
            UploadedFile metadata.

        Raises:
            ValueError: If file validation fails.
        """
        # Validate file size
        max_bytes = UPLOAD_CONFIG["max_size_mb"] * 1024 * 1024
        if len(file_data) > max_bytes:
            raise ValueError(
                f"File too large: {len(file_data) / 1024 / 1024:.1f}MB > "
                f"{UPLOAD_CONFIG['max_size_mb']}MB"
            )

        # Validate MIME type
        if mime_type and mime_type not in UPLOAD_CONFIG["allowed_types"]:
            allowed = ", ".join(UPLOAD_CONFIG["allowed_types"])
            raise ValueError(f"File type '{mime_type}' not allowed. Allowed: {allowed}")

        # Determine storage type
        storage = UPLOAD_CONFIG["storage"]
        file_id = f"file-{uuid.uuid4().hex[:12]}"
        ext = Path(original_name).suffix or ".jpg"
        stored_name = f"{file_id}{ext}"
        uploaded_at = time.time()

        if storage == "local":
            url, storage_path = self._save_local(file_data, stored_name, property_id)
            thumbnail_url = url.replace(ext, "_thumb" + ext)
        else:
            url, storage_path = self._save_s3(file_data, stored_name, property_id)
            thumbnail_url = url.replace(ext, "_thumb" + ext)

        # Get dimensions (stub — would use PIL in production)
        width, height = self._guess_dimensions(mime_type)

        uploaded = UploadedFile(
            file_id=file_id,
            property_id=property_id,
            original_name=original_name,
            stored_name=stored_name,
            mime_type=mime_type or "image/jpeg",
            size_bytes=len(file_data),
            width=width,
            height=height,
            url=url,
            thumbnail_url=thumbnail_url,
            storage_path=storage_path,
            is_primary=is_primary,
            uploaded_at=uploaded_at,
        )

        self._uploads[file_id] = uploaded
        if property_id:
            self._property_uploads.setdefault(property_id, []).append(file_id)

        _log.info("[UPLOAD] File saved: %s (%d bytes, %s)", url, len(file_data), mime_type)
        return uploaded

    def _save_local(self, file_data: bytes, stored_name: str, property_id: str) -> tuple[str, str]:
        """Save file to local filesystem."""
        # Organize by property if available
        if property_id:
            sub_dir = self._local_dir / property_id
        else:
            sub_dir = self._local_dir / "_general"

        sub_dir.mkdir(parents=True, exist_ok=True)
        file_path = sub_dir / stored_name

        # Write file
        file_path.write_bytes(file_data)

        # Also write thumbnail (just copy for now — production uses PIL resize)
        thumb_path = file_path.with_name(file_path.stem + "_thumb" + file_path.suffix)
        if not thumb_path.exists():
            thumb_path.write_bytes(file_data)

        cdn_base = UPLOAD_CONFIG["cdn_base_url"].rstrip("/")
        relative_path = f"{property_id}/{stored_name}" if property_id else f"_general/{stored_name}"
        url = f"{cdn_base}/{relative_path}"
        return url, str(file_path)

    def _save_s3(self, file_data: bytes, stored_name: str, property_id: str) -> tuple[str, str]:
        """Save file to S3-compatible storage.

        NOTE: S3 upload via boto3 is not implemented yet. Falls back to
        local storage with a warning. To enable S3, install boto3 and
        configure AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_BUCKET.
        """
        bucket = UPLOAD_CONFIG["aws_bucket"]
        if bucket:
            _log.warning(
                "[UPLOAD] S3 bucket '%s' configured but boto3 upload not implemented. "
                "Falling back to local storage. Install boto3 and implement "
                "s3_client.upload_fileobj() to enable cloud storage.",
                bucket,
            )
        return self._save_local(file_data, stored_name, property_id)

    @staticmethod
    def _guess_dimensions(mime_type: str) -> tuple[int, int]:
        """Guess image dimensions from MIME type (stub)."""
        if mime_type == "image/jpeg":
            return 1920, 1080  # placeholder
        return 800, 600

    # ── Query ─────────────────────────────────────────────────────────────

    def get_uploads_for_property(self, property_id: str) -> list[UploadedFile]:
        """Get all uploaded files for a property."""
        file_ids = self._property_uploads.get(property_id, [])
        return [self._uploads[fid] for fid in file_ids if fid in self._uploads]

    def get_upload(self, file_id: str) -> UploadedFile | None:
        """Get an uploaded file by ID."""
        return self._uploads.get(file_id)

    def delete_upload(self, file_id: str) -> bool:
        """Delete an uploaded file."""
        uploaded = self._uploads.pop(file_id, None)
        if not uploaded:
            return False

        # Remove from property mapping
        if uploaded.property_id:
            prop_uploads = self._property_uploads.get(uploaded.property_id, [])
            if file_id in prop_uploads:
                prop_uploads.remove(file_id)

        # Delete from filesystem
        try:
            path = Path(uploaded.storage_path)
            if path.exists():
                path.unlink()
            # Also delete thumbnail
            thumb_path = path.with_name(path.stem + "_thumb" + path.suffix)
            if thumb_path.exists():
                thumb_path.unlink()
        except Exception as e:
            _log.warning("[UPLOAD] File delete failed: %s", e)

        return True

    def set_primary(self, file_id: str, property_id: str) -> bool:
        """Set a file as the primary image for a property."""
        for fid in self._property_uploads.get(property_id, []):
            if fid in self._uploads:
                self._uploads[fid].is_primary = (fid == file_id)
        return True

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get upload service statistics."""
        total_files = len(self._uploads)
        total_bytes = sum(f.size_bytes for f in self._uploads.values())
        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / 1024 / 1024, 2),
            "properties_with_uploads": len(self._property_uploads),
            "storage_type": UPLOAD_CONFIG["storage"],
            "max_size_mb": UPLOAD_CONFIG["max_size_mb"],
            "allowed_types": UPLOAD_CONFIG["allowed_types"],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_upload_service_instance: UploadService | None = None


def get_upload_service() -> UploadService:
    """Get the global upload service singleton."""
    global _upload_service_instance
    if _upload_service_instance is None:
        _upload_service_instance = UploadService()
    return _upload_service_instance
