"""Data models for the AD-KIYU Auth Handler."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuthUser:
    user_id: str
    username: str
    role: str
    display_name: str = ""
    must_change_password: bool = False
    disabled: bool = False
    created_ts: float = field(default_factory=time.time)
    last_login_ts: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "display_name": self.display_name or self.username,
            "must_change_password": self.must_change_password,
            "disabled": self.disabled,
            "created_ts": self.created_ts,
            "last_login_ts": self.last_login_ts,
        }


@dataclass
class AuthToken:
    token: str
    user_id: str
    username: str
    role: str
    created_ts: float
    expires_ts: float
    csrf_token: str = ""

    def is_expired(self) -> bool:
        return time.time() >= self.expires_ts

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "created_ts": self.created_ts,
            "expires_ts": self.expires_ts,
            "csrf_token": self.csrf_token,
            "expires_in": max(0, int(self.expires_ts - time.time())),
        }


@dataclass
class PasswordResetToken:
    token: str
    username: str
    expires_ts: float
    used: bool = False
