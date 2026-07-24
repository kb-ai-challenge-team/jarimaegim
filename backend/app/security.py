from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
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


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def validate_supabase_jwt(token: str, secret: str, issuer: str | None = None) -> dict[str, Any]:
    if not secret:
        raise APIError("AUTH_REQUIRED", "인증 검증이 구성되지 않았습니다.", 401)
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_b64url_decode(header_part))
        payload = json.loads(_b64url_decode(payload_part))
        signature = _b64url_decode(signature_part)
    except Exception as exc:
        raise APIError("AUTH_REQUIRED", "유효하지 않은 인증 토큰입니다.", 401) from exc
    if header.get("alg") != "HS256":
        raise APIError("AUTH_REQUIRED", "지원되지 않는 인증 서명 방식입니다.", 401)
    expected = hmac.new(secret.encode(), f"{header_part}.{payload_part}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise APIError("AUTH_REQUIRED", "유효하지 않은 인증 토큰입니다.", 401)
    now = int(time.time())
    if not isinstance(payload.get("exp"), (int, float)) or payload["exp"] <= now:
        raise APIError("AUTH_REQUIRED", "인증 토큰이 만료되었습니다.", 401)
    if payload.get("nbf") is not None and payload["nbf"] > now:
        raise APIError("AUTH_REQUIRED", "아직 유효하지 않은 인증 토큰입니다.", 401)
    if payload.get("aud") != "authenticated" or payload.get("role") != "authenticated":
        raise APIError("AUTH_REQUIRED", "인증 대상이 올바르지 않습니다.", 401)
    if issuer and payload.get("iss", "").rstrip("/") != issuer.rstrip("/"):
        raise APIError("AUTH_REQUIRED", "인증 발급자가 올바르지 않습니다.", 401)
    try:
        UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise APIError("AUTH_REQUIRED", "인증 주체가 올바르지 않습니다.", 401) from exc
    return payload


def redact_text(value: str, *, max_length: int = 4000) -> str:
    text = value[:max_length]
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("[민감정보 차단]", text)
    return text


def canonical_hash(value: Any) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).digest()
