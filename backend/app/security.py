from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .errors import APIError


SENSITIVE_PATTERNS = (
    re.compile(r"\b\d{6}[- ]?[1-4]\d{6}\b"),
    re.compile(r"(?i)(?:otp|one.?time.?password|계좌\s*비밀번호|카드\s*비밀번호)\s*[:=]?\s*\S+"),
)


@dataclass(frozen=True)
class Actor:
    kind: str
    id: UUID
    aal: str | None = None
    role: str | None = None

    @property
    def owner_key(self) -> str:
        return f"{self.kind}:{self.id}"


def token_digest(pepper: str, token: str) -> bytes:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).digest()


def make_anonymous_credential() -> tuple[UUID, str, bytes]:
    session_id = UUID(bytes=secrets.token_bytes(16), version=4)
    token = secrets.token_urlsafe(32)
    return session_id, f"{session_id}.{token}", token.encode()


def split_anonymous_credential(value: str) -> tuple[UUID, str]:
    try:
        raw_id, token = value.split(".", 1)
        session_id = UUID(raw_id)
    except (ValueError, AttributeError) as exc:
        raise APIError("AUTH_REQUIRED", "유효한 익명 세션이 필요합니다.", 401) from exc
    if len(token) < 32:
        raise APIError("AUTH_REQUIRED", "유효한 익명 세션이 필요합니다.", 401)
    return session_id, token


def redact_text(value: str, *, max_length: int = 4000) -> str:
    text = value[:max_length]
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("[민감정보 차단]", text)
    return text


def canonical_hash(value: Any) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).digest()
