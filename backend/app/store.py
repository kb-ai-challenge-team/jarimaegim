from __future__ import annotations

import asyncio
import base64
import hmac
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi.encoders import jsonable_encoder

from .config import Settings
from .errors import APIError
from .security import Actor, token_digest


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> Any:
    return jsonable_encoder(value)


class Store:
    """Owner-scoped persistence. Supabase REST is used only with the server service key."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.supabase = settings.supabase_configured
        self._lock = asyncio.Lock()
        self.sessions: dict[UUID, dict[str, Any]] = {}
        self.cases: dict[UUID, dict[str, Any]] = {}
        self.analyses: dict[UUID, dict[str, Any]] = {}
        self.cost_plans: dict[UUID, dict[str, Any]] = {}
        self.programs: dict[UUID, dict[str, Any]] = {}
        self.documents: dict[UUID, dict[str, Any]] = {}
        self.document_bytes: dict[UUID, bytes] = {}
        self.notifications: dict[UUID, dict[str, Any]] = {}
        self.settings_rows: dict[UUID, dict[str, Any]] = {}
        self.privacy_requests: dict[UUID, dict[str, Any]] = {}
        self.consents: dict[UUID, dict[str, Any]] = {}
        self.consultation_previews: dict[UUID, dict[str, Any]] = {}
        self.deletion_jobs: dict[UUID, dict[str, Any]] = {}
        self.admin_resources: dict[UUID, dict[str, Any]] = {}
        self.kill_switches: dict[str, dict[str, Any]] = {
            name: {"name": name, "enabled": False, "reason": "운영 승인 전 비활성", "expires_at": None, "version": 1, "updated_at": utcnow()}
            for name in ("ai_explanation", "individual_probability", "financial_application", "consultation_transfer")
        }
        self.messages: dict[UUID, list[dict[str, Any]]] = {}
        self.stream_events: dict[UUID, list[dict[str, Any]]] = {}
        self.idempotency: dict[tuple[str, str, UUID], dict[str, Any]] = {}
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) if self.supabase else None

    async def close(self) -> None:
        if self.http:
            await self.http.aclose()

    def _headers(self, *, prefer: str | None = None, content_type: str = "application/json") -> dict[str, str]:
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Content-Type": content_type,
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _rest(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None, prefer: str | None = None) -> Any:
        assert self.http is not None
        try:
            response = await self.http.request(
                method, f"{self.settings.supabase_url.rstrip('/')}/rest/v1/{path}",
                params=params, json=_iso(body) if body is not None else None,
                headers=self._headers(prefer=prefer),
            )
            if response.status_code >= 400:
                try:
                    error_code = str(response.json().get("code", ""))
                except ValueError:
                    error_code = ""
                if error_code == "40001":
                    raise APIError("VERSION_CONFLICT", "리소스가 다른 요청에서 변경되었습니다.", 409)
                if error_code == "23505":
                    raise APIError("IDEMPOTENCY_CONFLICT", "고유 요청 식별자가 이미 사용되었습니다.", 409)
                if error_code == "42501":
                    raise APIError("FORBIDDEN", "요청 권한이 없습니다.", 403)
                response.raise_for_status()
            if not response.content:
                return None
            return response.json()
        except APIError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise APIError("UPSTREAM_UNAVAILABLE", "데이터 저장소에 연결할 수 없습니다.", 503, retryable=True, retry_after=10) from exc

    @staticmethod
    def _owner_params(actor: Actor) -> dict[str, str]:
        if actor.kind == "USER":
            return {"owner_user_id": f"eq.{actor.id}", "anonymous_session_id": "is.null"}
        return {"anonymous_session_id": f"eq.{actor.id}", "owner_user_id": "is.null"}

    async def create_session(self, session_id: UUID, digest: bytes, expires_at: datetime) -> dict[str, Any]:
        row = {
            "id": session_id, "token_hash": "\\x" + digest.hex(), "token_version": 1, "status": "ACTIVE",
            "last_seen_at": utcnow(), "retention_class": "ANON_24H", "expires_at": expires_at,
        }
        if self.supabase:
            data = await self._rest("POST", "anonymous_sessions", body=row, prefer="return=representation")
            return data[0]
        local = deepcopy(row)
        local["token_hash"] = digest
        local["created_at"] = local["updated_at"] = utcnow()
        async with self._lock:
            self.sessions[session_id] = local
        return deepcopy(local)

    async def verify_session(self, session_id: UUID, digest: bytes) -> dict[str, Any]:
        if self.supabase:
            rows = await self._rest("GET", "anonymous_sessions", params={"id": f"eq.{session_id}", "select": "*", "limit": 1})
            row = rows[0] if rows else None
            stored = bytes.fromhex(str(row.get("token_hash", "")).removeprefix("\\x")) if row else b""
        else:
            row = self.sessions.get(session_id)
            stored = row.get("token_hash", b"") if row else b""
        if not row or not hmac.compare_digest(stored, digest):
            raise APIError("AUTH_REQUIRED", "유효한 익명 세션이 필요합니다.", 401)
        expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) if isinstance(row["expires_at"], str) else row["expires_at"]
        if row.get("status") != "ACTIVE" or expires <= utcnow():
            raise APIError("AUTH_REQUIRED", "익명 세션이 만료되었습니다.", 401)
        return deepcopy(row)

    async def delete_session(self, actor: Actor) -> None:
        if actor.kind != "ANONYMOUS":
            raise APIError("AUTH_REQUIRED", "익명 세션이 필요합니다.", 401)
        if self.supabase:
            result = await self._rest("POST", "rpc/request_anonymous_session_deletion", body={"p_session": actor.id})
            if not result:
                raise APIError("NOT_FOUND", "익명 세션을 찾을 수 없습니다.", 404)
            return
        async with self._lock:
            self.sessions.pop(actor.id, None)
            for case_id in [key for key, row in self.cases.items() if row["owner_key"] == actor.owner_key]:
                self.cases.pop(case_id, None)

    async def ensure_profile(self, user_id: UUID) -> None:
        if self.supabase:
            await self._rest("POST", "profiles", body={"user_id": user_id, "locale": "ko-KR"}, prefer="resolution=merge-duplicates,return=minimal")

    async def create_case(self, actor: Actor, title: str, inputs: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        case_id = uuid4()
        if self.supabase:
            if actor.kind == "USER":
                await self.ensure_profile(actor.id)
            created = await self._rest("POST", "rpc/create_case_with_inputs", body={
                "p_case": case_id, "p_user": actor.id if actor.kind == "USER" else None,
                "p_session": actor.id if actor.kind == "ANONYMOUS" else None, "p_title": title, "p_inputs": inputs,
            })
            if not created:
                raise APIError("UPSTREAM_UNAVAILABLE", "케이스를 저장하지 못했습니다.", 503, retryable=True)
            return await self.get_case(actor, case_id)
        row = {"id": case_id, "title": title, "status": "ACTIVE", "version": 1, "inputs": deepcopy(inputs),
               "owner_key": actor.owner_key, "created_at": now, "updated_at": now}
        async with self._lock:
            self.cases[case_id] = row
        return deepcopy(row)

    async def get_case(self, actor: Actor, case_id: UUID) -> dict[str, Any]:
        if self.supabase:
            params: dict[str, Any] = {"id": f"eq.{case_id}", "status": "neq.DELETED", "select": "*", "limit": 1, **self._owner_params(actor)}
            rows = await self._rest("GET", "cases", params=params)
            if not rows:
                raise APIError("NOT_FOUND", "케이스를 찾을 수 없습니다.", 404)
            inputs = await self._rest("GET", "case_inputs", params={"case_id": f"eq.{case_id}", "select": "field,value_json"})
            return {**rows[0], "inputs": {row["field"]: row["value_json"] for row in inputs}}
        row = self.cases.get(case_id)
        if not row or row.get("owner_key") != actor.owner_key or row.get("status") == "DELETED":
            raise APIError("NOT_FOUND", "케이스를 찾을 수 없습니다.", 404)
        return deepcopy(row)

    async def patch_case(self, actor: Actor, case_id: UUID, expected_version: int, patch: dict[str, Any]) -> dict[str, Any]:
        current = await self.get_case(actor, case_id)
        if current["version"] != expected_version:
            raise APIError("VERSION_CONFLICT", "케이스가 다른 곳에서 변경되었습니다.", 409, details={"current_version": current["version"]})
        new_inputs = patch.get("inputs")
        changes = {"version": expected_version + 1, "updated_at": utcnow()}
        if patch.get("title") is not None:
            changes["title"] = patch["title"]
        if self.supabase:
            result = await self._rest("POST", "rpc/patch_case_with_inputs", body={
                "p_case": case_id, "p_user": actor.id if actor.kind == "USER" else None,
                "p_session": actor.id if actor.kind == "ANONYMOUS" else None,
                "p_expected_version": expected_version, "p_title": patch.get("title"), "p_inputs": new_inputs,
            })
            if result is None:
                raise APIError("NOT_FOUND", "케이스를 찾을 수 없습니다.", 404)
            return await self.get_case(actor, case_id)
        async with self._lock:
            row = self.cases.get(case_id)
            if not row or row["version"] != expected_version:
                raise APIError("VERSION_CONFLICT", "케이스가 다른 곳에서 변경되었습니다.", 409)
            row.update(changes)
            if new_inputs is not None:
                row["inputs"] = deepcopy(new_inputs)
        return await self.get_case(actor, case_id)

    async def mark_case_deleting(self, actor: Actor, case_id: UUID, expected_version: int) -> dict[str, Any]:
        return await self.patch_case(actor, case_id, expected_version, {"title": None, "inputs": None, "status": "DELETING"}) if False else await self._mark_deleting(actor, case_id, expected_version)

    async def _mark_deleting(self, actor: Actor, case_id: UUID, expected_version: int) -> dict[str, Any]:
        current = await self.get_case(actor, case_id)
        if current["version"] != expected_version:
            raise APIError("VERSION_CONFLICT", "케이스가 다른 곳에서 변경되었습니다.", 409)
        changes = {"status": "DELETING", "version": expected_version + 1, "updated_at": utcnow()}
        if self.supabase:
            result = await self._rest("POST", "rpc/mark_case_deleting", body={
                "p_case": case_id, "p_user": actor.id if actor.kind == "USER" else None,
                "p_session": actor.id if actor.kind == "ANONYMOUS" else None, "p_expected_version": expected_version,
            })
            if result is None:
                raise APIError("NOT_FOUND", "케이스를 찾을 수 없습니다.", 404)
            return await self.get_case(actor, case_id)
        async with self._lock:
            self.cases[case_id].update(changes)
        return await self.get_case(actor, case_id)

    async def claim_case(self, user: Actor, anonymous: Actor, case_id: UUID) -> dict[str, Any]:
        if user.kind != "USER" or anonymous.kind != "ANONYMOUS":
            raise APIError("AUTH_REQUIRED", "로그인과 익명 세션이 모두 필요합니다.", 401)
        if self.supabase:
            await self.ensure_profile(user.id)
            result = await self._rest("POST", "rpc/claim_anonymous_case", body={"p_case": case_id, "p_session": anonymous.id, "p_user": user.id})
            if not result:
                raise APIError("NOT_FOUND", "이전할 케이스를 찾을 수 없습니다.", 404)
            return await self.get_case(user, case_id)
        async with self._lock:
            row = self.cases.get(case_id)
            if not row or row["owner_key"] != anonymous.owner_key:
                raise APIError("NOT_FOUND", "이전할 케이스를 찾을 수 없습니다.", 404)
            row["owner_key"] = user.owner_key
            row["version"] += 1
            row["updated_at"] = utcnow()
            if anonymous.id in self.sessions:
                self.sessions[anonymous.id]["status"] = "CLAIMED"
                self.sessions[anonymous.id]["token_version"] += 1
        return await self.get_case(user, case_id)

    async def save_analysis(self, actor: Actor, result: dict[str, Any]) -> dict[str, Any]:
        await self.get_case(actor, UUID(str(result["case_id"])))
        analysis_id = UUID(str(result["analysis_id"]))
        if self.supabase:
            row = {"id": analysis_id, "case_id": result["case_id"], "status": result["status"], "evidence_grade": result["evidence_grade"],
                   "survival_grade": result.get("survival_grade"), "context_risk_grade": result.get("context_risk_grade"),
                   "probability_lower": result.get("probability_lower"), "probability_upper": result.get("probability_upper"),
                   "probability_unit": result.get("probability_unit"), "horizon_months": result.get("horizon_months"),
                   "confidence": result["confidence"], "sample_n": result.get("sample_n"), "event_n": result.get("event_n"),
                   "context_signals": result.get("context_signals", []), "blocked_reason": result.get("blocked_reason"),
                   "required_actions": result.get("required_actions", []), "model_version": result["provenance"]["model_version"],
                   "provenance": result["provenance"], "limitations": result["limitations"]}
            await self._rest("POST", "analysis_results", body=row, prefer="return=minimal")
        else:
            async with self._lock:
                self.analyses[analysis_id] = {**deepcopy(result), "owner_key": actor.owner_key}
        return deepcopy(result)

    async def get_analysis(self, actor: Actor, analysis_id: UUID) -> dict[str, Any]:
        if self.supabase:
            rows = await self._rest("GET", "analysis_results", params={"id": f"eq.{analysis_id}", "select": "*", "limit": 1})
            if not rows:
                raise APIError("NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
            row = rows[0]
            await self.get_case(actor, UUID(row["case_id"]))
            return {"analysis_id": row.pop("id"), **row, "display_label": {"A": "개별 검증 결과", "B": "상권 위험등급", "C": "맥락 진단", "U": "분석 불가"}[row["evidence_grade"]]}
        row = self.analyses.get(analysis_id)
        if not row or row.get("owner_key") != actor.owner_key:
            raise APIError("NOT_FOUND", "분석 결과를 찾을 수 없습니다.", 404)
        result = deepcopy(row)
        result.pop("owner_key", None)
        return result

    async def save_cost_plan(self, actor: Actor, row: dict[str, Any]) -> None:
        await self.get_case(actor, UUID(str(row["case_id"])))
        if self.supabase:
            await self._rest("POST", "cost_plans", body={"id": row["cost_plan_id"], "case_id": row["case_id"], "items": row["items"],
                "total_minimum_krw": row["total_minimum_krw"], "total_maximum_krw": row["total_maximum_krw"],
                "equity_krw": row["equity_krw"], "funding_gap_minimum_krw": row["funding_gap_minimum_krw"],
                "funding_gap_maximum_krw": row["funding_gap_maximum_krw"], "calculation_version": row["calculation_version"]})
        else:
            self.cost_plans[UUID(str(row["cost_plan_id"]))] = {**deepcopy(row), "owner_key": actor.owner_key}

    async def cache_programs(self, records: list[dict[str, Any]]) -> None:
        if self.supabase and records:
            rows = []
            for record in records:
                rows.append({
                    "id": record["program_id"], "provider": record["provider"],
                    "source_record_id": record["source_record_id"], "title": record["title"],
                    "official_url": record["official_url"], "published_at": record.get("published_at"),
                    "application_start": record.get("application_start"), "application_end": record.get("application_end"),
                    "structured_criteria": {
                        "region_codes": record.get("region_codes", []), "industry_ids": record.get("industry_ids", []),
                        "business_stages": record.get("business_stages", []),
                    },
                    "collected_at": record["collected_at"],
                })
            await self._rest("POST", "program_records", body=rows, prefer="resolution=merge-duplicates,return=minimal")
        async with self._lock:
            for record in records:
                self.programs[UUID(str(record["program_id"]))] = deepcopy(record)

    async def get_program(self, program_id: UUID) -> dict[str, Any] | None:
        cached = self.programs.get(program_id)
        if cached:
            return deepcopy(cached)
        if not self.supabase:
            return None
        rows = await self._rest("GET", "program_records", params={"id": f"eq.{program_id}", "select": "*", "limit": 1})
        if not rows:
            return None
        row = rows[0]
        criteria = row.get("structured_criteria") or {}
        return {
            "program_id": row["id"], "provider": row["provider"], "source_record_id": row["source_record_id"],
            "title": row["title"], "official_url": row["official_url"], "published_at": row.get("published_at"),
            "application_start": row.get("application_start"), "application_end": row.get("application_end"),
            "region_codes": criteria.get("region_codes", []), "industry_ids": criteria.get("industry_ids", []),
            "business_stages": criteria.get("business_stages", []), "collected_at": row["collected_at"], "raw_summary": {},
        }

    async def save_document(self, actor: Actor, row: dict[str, Any], data: bytes) -> dict[str, Any]:
        await self.get_case(actor, UUID(str(row["case_id"])))
        if self.supabase:
            path = row["object_path"]
            assert self.http is not None
            response = await self.http.post(
                f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/private-documents/{path}",
                content=data, headers=self._headers(content_type="application/pdf") | {"x-upsert": "false"},
            )
            if response.status_code >= 400:
                raise APIError("UPSTREAM_UNAVAILABLE", "PDF 저장에 실패했습니다.", 503, retryable=True)
            await self._rest("POST", "documents", body={"id": row["document_id"], "case_id": row["case_id"], "status": "SUCCEEDED", "template": row["template"], "object_path": path, "manifest": row["manifest"], "completed_at": row["completed_at"]})
        else:
            async with self._lock:
                self.documents[UUID(str(row["document_id"]))] = {**deepcopy(row), "owner_key": actor.owner_key}
                self.document_bytes[UUID(str(row["document_id"]))] = data
        return deepcopy(row)

    async def get_document(self, actor: Actor, document_id: UUID) -> dict[str, Any]:
        if self.supabase:
            rows = await self._rest("GET", "documents", params={"id": f"eq.{document_id}", "select": "*", "limit": 1})
            if not rows:
                raise APIError("NOT_FOUND", "문서를 찾을 수 없습니다.", 404)
            await self.get_case(actor, UUID(rows[0]["case_id"]))
            row = rows[0]
            return {"document_id": row.pop("id"), **row, "status": row["status"].lower()}
        row = self.documents.get(document_id)
        if not row or row.get("owner_key") != actor.owner_key:
            raise APIError("NOT_FOUND", "문서를 찾을 수 없습니다.", 404)
        result = deepcopy(row)
        result.pop("owner_key", None)
        return result

    async def signed_document_url(self, actor: Actor, document_id: UUID, ttl: int, request_id: UUID) -> str:
        row = await self.get_document(actor, document_id)
        if self.supabase:
            assert self.http is not None
            response = await self.http.post(
                f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/sign/private-documents/{row['object_path']}",
                json={"expiresIn": ttl}, headers=self._headers(),
            )
            if response.status_code >= 400:
                raise APIError("UPSTREAM_UNAVAILABLE", "다운로드 URL을 만들 수 없습니다.", 503, retryable=True)
            signed = response.json().get("signedURL") or response.json().get("signedUrl")
            if not signed:
                raise APIError("UPSTREAM_UNAVAILABLE", "다운로드 URL을 만들 수 없습니다.", 503)
            await self._rest("POST", "document_download_audit", body={
                "document_id": document_id,
                "actor_pseudonym": "\\x" + token_digest(self.settings.anon_token_pepper, actor.owner_key).hex(),
                "request_id": request_id, "expires_at": utcnow() + timedelta(days=365),
            }, prefer="return=minimal")
            return signed if signed.startswith("http") else f"{self.settings.supabase_url.rstrip('/')}/storage/v1{signed}"
        expires_at = int(time.time()) + ttl
        signed_value = f"{document_id}:{actor.owner_key}:{expires_at}"
        signature = token_digest(self.settings.anon_token_pepper, signed_value).hex()
        return f"/api/v1/documents/{document_id}/local-download?token={expires_at}.{signature}"

    async def append_message(self, actor: Actor, case_id: UUID, content: str) -> dict[str, Any]:
        await self.get_case(actor, case_id)
        message = {"id": uuid4(), "case_id": case_id, "role": "USER", "content_redacted": content, "created_at": utcnow()}
        if self.supabase:
            conversations = await self._rest("GET", "conversations", params={"case_id": f"eq.{case_id}", "select": "*", "limit": 1})
            if conversations:
                conversation = conversations[0]
            else:
                rows = await self._rest("POST", "conversations", body={"case_id": case_id, "status": "ACTIVE", "retention_class": "USER_UNTIL_DELETE"}, prefer="return=representation")
                conversation = rows[0]
            sequence = int(conversation["last_sequence"]) + 1
            await self._rest("POST", "messages", body={"id": message["id"], "conversation_id": conversation["id"], "role": "USER", "content_redacted": content, "retention_class": "USER_UNTIL_DELETE", "sequence": sequence})
            await self._rest("PATCH", "conversations", params={"id": f"eq.{conversation['id']}", "last_sequence": f"eq.{conversation['last_sequence']}"}, body={"last_sequence": sequence})
        else:
            self.messages.setdefault(case_id, []).append({**message, "owner_key": actor.owner_key})
        return message

    async def list_notifications(self, actor: Actor, unread_only: bool) -> list[dict[str, Any]]:
        if actor.kind != "USER":
            raise APIError("AUTH_REQUIRED", "로그인이 필요합니다.", 401)
        if self.supabase:
            params: dict[str, Any] = {"user_id": f"eq.{actor.id}", "select": "*", "order": "created_at.desc", "limit": 100}
            if unread_only:
                params["read_at"] = "is.null"
            return await self._rest("GET", "notifications", params=params)
        rows = [deepcopy(row) for row in self.notifications.values() if row["user_id"] == actor.id and (not unread_only or row.get("read_at") is None)]
        return sorted(rows, key=lambda item: item["created_at"], reverse=True)

    async def read_notification(self, actor: Actor, notification_id: UUID) -> dict[str, Any]:
        if actor.kind != "USER":
            raise APIError("AUTH_REQUIRED", "로그인이 필요합니다.", 401)
        now = utcnow()
        if self.supabase:
            rows = await self._rest("PATCH", "notifications", params={"id": f"eq.{notification_id}", "user_id": f"eq.{actor.id}"}, body={"read_at": now}, prefer="return=representation")
            if not rows:
                raise APIError("NOT_FOUND", "알림을 찾을 수 없습니다.", 404)
            return rows[0]
        row = self.notifications.get(notification_id)
        if not row or row["user_id"] != actor.id:
            raise APIError("NOT_FOUND", "알림을 찾을 수 없습니다.", 404)
        row["read_at"] = now
        row["updated_at"] = now
        return deepcopy(row)

    async def get_notification_settings(self, actor: Actor) -> dict[str, Any]:
        if actor.kind != "USER":
            raise APIError("AUTH_REQUIRED", "로그인이 필요합니다.", 401)
        default = {"in_app": True, "email_program_deadline": False, "email_document_status": False, "email_data_updates": False}
        if self.supabase:
            rows = await self._rest("GET", "notification_settings", params={"user_id": f"eq.{actor.id}", "select": "*", "limit": 1})
            if not rows:
                await self.ensure_profile(actor.id)
                created = await self._rest("POST", "notification_settings", body={"user_id": actor.id, "settings": default, "version": 1}, prefer="return=representation")
                return created[0]
            return rows[0]
        return deepcopy(self.settings_rows.setdefault(actor.id, {"user_id": actor.id, "settings": default, "version": 1, "created_at": utcnow(), "updated_at": utcnow()}))

    async def patch_notification_settings(self, actor: Actor, expected_version: int, settings: dict[str, Any]) -> dict[str, Any]:
        current = await self.get_notification_settings(actor)
        if current["version"] != expected_version:
            raise APIError("VERSION_CONFLICT", "알림 설정이 다른 곳에서 변경되었습니다.", 409, details={"current_version": current["version"]})
        update = {"settings": settings, "version": expected_version + 1, "updated_at": utcnow()}
        if self.supabase:
            rows = await self._rest("PATCH", "notification_settings", params={"user_id": f"eq.{actor.id}", "version": f"eq.{expected_version}"}, body=update, prefer="return=representation")
            if not rows:
                raise APIError("VERSION_CONFLICT", "알림 설정이 다른 곳에서 변경되었습니다.", 409)
            return rows[0]
        self.settings_rows[actor.id].update(update)
        return deepcopy(self.settings_rows[actor.id])

    async def create_privacy_request(self, actor: Actor, request_type: str, verification_method: str, idempotency_key: UUID) -> dict[str, Any]:
        now = utcnow()
        row = {"id": uuid4(), "requester_user_id": actor.id if actor.kind == "USER" else None,
               "anonymous_session_id": actor.id if actor.kind == "ANONYMOUS" else None, "request_type": request_type,
               "status": "RECEIVED", "verification_method": verification_method, "idempotency_key": idempotency_key,
               "result_manifest": {}, "created_at": now, "updated_at": now}
        if self.supabase:
            rows = await self._rest("POST", "privacy_requests", body=row, prefer="return=representation")
            return rows[0]
        self.privacy_requests[row["id"]] = {**row, "owner_key": actor.owner_key}
        return deepcopy(row)

    async def get_privacy_request(self, actor: Actor, request_id: UUID) -> dict[str, Any]:
        if self.supabase:
            owner = {"requester_user_id": f"eq.{actor.id}"} if actor.kind == "USER" else {"anonymous_session_id": f"eq.{actor.id}"}
            rows = await self._rest("GET", "privacy_requests", params={"id": f"eq.{request_id}", "select": "*", "limit": 1, **owner})
            if not rows:
                raise APIError("NOT_FOUND", "권리요청을 찾을 수 없습니다.", 404)
            return rows[0]
        row = self.privacy_requests.get(request_id)
        if not row or row["owner_key"] != actor.owner_key:
            raise APIError("NOT_FOUND", "권리요청을 찾을 수 없습니다.", 404)
        return deepcopy(row)


    async def delete_document(self, actor: Actor, document_id: UUID) -> None:
        row = await self.get_document(actor, document_id)
        if self.supabase:
            assert self.http is not None
            response = await self.http.delete(
                f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/private-documents/{row['object_path']}",
                headers=self._headers(),
            )
            if response.status_code >= 400 and response.status_code != 404:
                raise APIError("UPSTREAM_UNAVAILABLE", "문서 삭제에 실패했습니다.", 503, retryable=True)
            await self._rest("DELETE", "documents", params={"id": f"eq.{document_id}"})
            return
        async with self._lock:
            self.documents.pop(document_id, None)
            self.document_bytes.pop(document_id, None)

    async def local_document_bytes(self, actor: Actor, document_id: UUID) -> bytes:
        if self.supabase:
            raise APIError("NOT_FOUND", "로컬 문서를 찾을 수 없습니다.", 404)
        await self.get_document(actor, document_id)
        data = self.document_bytes.get(document_id)
        if data is None:
            raise APIError("NOT_FOUND", "문서를 찾을 수 없습니다.", 404)
        return data

    async def list_messages(self, actor: Actor, case_id: UUID) -> list[dict[str, Any]]:
        await self.get_case(actor, case_id)
        if self.supabase:
            conversations = await self._rest("GET", "conversations", params={"case_id": f"eq.{case_id}", "select": "id", "limit": 1})
            if not conversations:
                return []
            return await self._rest("GET", "messages", params={"conversation_id": f"eq.{conversations[0]['id']}", "select": "id,role,content_redacted,sequence,created_at", "order": "sequence.asc", "limit": 200})
        return [{key: value for key, value in row.items() if key != "owner_key"} for row in self.messages.get(case_id, []) if row["owner_key"] == actor.owner_key]


    async def latest_analysis_for_case(self, actor: Actor, case_id: UUID) -> dict[str, Any] | None:
        await self.get_case(actor, case_id)
        if self.supabase:
            rows = await self._rest("GET", "analysis_results", params={"case_id": f"eq.{case_id}", "select": "id", "order": "created_at.desc", "limit": 1})
            return await self.get_analysis(actor, UUID(rows[0]["id"])) if rows else None
        matches = [row for row in self.analyses.values() if UUID(str(row.get("case_id"))) == case_id and row.get("owner_key") == actor.owner_key]
        if not matches:
            return None
        result = deepcopy(matches[-1])
        result.pop("owner_key", None)
        return result


    def validate_local_document_token(self, actor: Actor, document_id: UUID, token: str) -> None:
        try:
            expires_raw, signature = token.split(".", 1)
            expires_at = int(expires_raw)
        except (ValueError, AttributeError) as exc:
            raise APIError("STREAM_EXPIRED", "다운로드 URL이 유효하지 않습니다.", 410) from exc
        expected = token_digest(self.settings.anon_token_pepper, f"{document_id}:{actor.owner_key}:{expires_at}").hex()
        if expires_at < int(time.time()) or not hmac.compare_digest(expected, signature):
            raise APIError("STREAM_EXPIRED", "다운로드 URL이 만료되었거나 유효하지 않습니다.", 410)


    async def get_idempotency(self, actor_hash: bytes, route: str, key: UUID) -> dict[str, Any] | None:
        if self.supabase:
            rows = await self._rest("GET", "idempotency_keys", params={
                "actor_hash": f"eq.\\x{actor_hash.hex()}", "route": f"eq.{route}", "key": f"eq.{key}", "select": "*", "limit": 1,
            })
            row = rows[0] if rows else None
            if row:
                row["request_hash"] = bytes.fromhex(str(row["request_hash"]).removeprefix("\\x"))
            return row
        cache_key = (actor_hash.hex(), route, key)
        row = self.idempotency.get(cache_key)
        if not row:
            return None
        if row["expires_at"] <= utcnow():
            self.idempotency.pop(cache_key, None)
            return None
        return deepcopy(row)

    async def save_idempotency(
        self, actor_hash: bytes, route: str, key: UUID, request_hash: bytes,
        status_code: int, response_redacted: dict[str, Any], resource_id: UUID | None = None,
    ) -> None:
        row = {
            "actor_hash": "\\x" + actor_hash.hex(), "route": route, "key": key,
            "request_hash": "\\x" + request_hash.hex(), "status_code": status_code,
            "response_redacted": response_redacted, "resource_id": resource_id,
            "expires_at": utcnow() + timedelta(hours=24),
        }
        if self.supabase:
            try:
                await self._rest("POST", "idempotency_keys", body=row, prefer="resolution=ignore-duplicates,return=minimal")
            except APIError:
                # The business response must not be replaced by an idempotency bookkeeping outage.
                return
        else:
            local = deepcopy(row)
            local["actor_hash"] = actor_hash
            local["request_hash"] = request_hash
            self.idempotency[(actor_hash.hex(), route, key)] = local



    async def has_admin_role(self, actor: Actor) -> bool:
        if actor.kind != "USER" or actor.aal != "aal2":
            return False
        if self.supabase:
            rows = await self._rest("GET", "app_roles", params={
                "user_id": f"eq.{actor.id}", "role": "eq.ADMIN", "valid_from": f"lte.{utcnow().isoformat()}",
                "or": f"(valid_to.is.null,valid_to.gt.{utcnow().isoformat()})", "select": "user_id", "limit": 1,
            })
            return bool(rows)
        return actor.role in {"ADMIN", "admin"}

    async def begin_message(
        self, actor: Actor, case_id: UUID, client_message_id: UUID, content: str,
        base_version: int, confirmed_patch: list[dict[str, Any]], confirmed_inputs: dict[str, Any],
    ) -> dict[str, Any]:
        if self.supabase:
            result = await self._rest("POST", "rpc/append_message_v2", body={
                "p_case": case_id,
                "p_user": actor.id if actor.kind == "USER" else None,
                "p_session": actor.id if actor.kind == "ANONYMOUS" else None,
                "p_client_message_id": client_message_id,
                "p_content_redacted": content,
                "p_base_version": base_version,
                "p_confirmed_patch": confirmed_patch,
                "p_confirmed_inputs": confirmed_inputs,
            })
            if not result:
                raise APIError("NOT_FOUND", "케이스를 찾을 수 없습니다.", 404)
            if isinstance(result, list):
                result = result[0]
            return {**result, "case": await self.get_case(actor, case_id)}
        now = utcnow()
        async with self._lock:
            case = self.cases.get(case_id)
            if not case or case.get("owner_key") != actor.owner_key or case.get("status") != "ACTIVE":
                raise APIError("NOT_FOUND", "케이스를 찾을 수 없습니다.", 404)
            if case["version"] != base_version:
                raise APIError("VERSION_CONFLICT", "케이스가 다른 곳에서 변경되었습니다.", 409, details={"current_version": case["version"]})
            existing = next((row for row in self.messages.get(case_id, []) if row.get("client_message_id") == client_message_id), None)
            if existing:
                raise APIError("IDEMPOTENCY_CONFLICT", "client_message_id가 이미 사용되었습니다.", 409)
            if confirmed_patch:
                case["inputs"] = deepcopy(confirmed_inputs)
                case["version"] += 1
                case["updated_at"] = now
            rows = self.messages.setdefault(case_id, [])
            message_id = uuid4()
            message = {
                "id": message_id, "case_id": case_id, "client_message_id": client_message_id,
                "role": "USER", "content_redacted": content, "confirmed_case_patch": deepcopy(confirmed_patch) or None,
                "sequence": len(rows) + 1, "created_at": now, "owner_key": actor.owner_key,
            }
            rows.append(message)
            events = [{
                "message_id": message_id, "sequence": 1, "event_type": "message.accepted",
                "payload_redacted": {"conversation_id": str(case_id), "user_message_id": str(message_id), "case_version": case["version"]},
                "expires_at": now + timedelta(hours=24), "created_at": now,
            }]
            if confirmed_patch:
                events.append({
                    "message_id": message_id, "sequence": 2, "event_type": "case.patch.confirmed",
                    "payload_redacted": {"patch": deepcopy(confirmed_patch), "case_version": case["version"]},
                    "expires_at": now + timedelta(hours=24), "created_at": now,
                })
            self.stream_events[message_id] = events
            result_case = deepcopy(case)
        return {"message_id": message_id, "conversation_id": case_id, "case_version": result_case["version"], "case": result_case}

    async def complete_message(
        self, actor: Actor, case_id: UUID, user_message_id: UUID, content: str,
        generated_by: str, model: str | None,
    ) -> list[dict[str, Any]]:
        assistant_id = uuid4()
        safe_model = model or "safe-fallback"
        if self.supabase:
            result = await self._rest("POST", "rpc/complete_message", body={
                "p_case": case_id,
                "p_user": actor.id if actor.kind == "USER" else None,
                "p_session": actor.id if actor.kind == "ANONYMOUS" else None,
                "p_user_message": user_message_id, "p_assistant_message": assistant_id,
                "p_content_redacted": content, "p_model_version": safe_model,
                "p_prompt_version": "chat-explanation-1", "p_generated_by": generated_by,
            })
            if not result:
                raise APIError("NOT_FOUND", "메시지를 찾을 수 없습니다.", 404)
            return await self.get_stream_events(actor, case_id, user_message_id, 0)
        now = utcnow()
        async with self._lock:
            case = self.cases.get(case_id)
            if not case or case.get("owner_key") != actor.owner_key:
                raise APIError("NOT_FOUND", "케이스를 찾을 수 없습니다.", 404)
            user_row = next((row for row in self.messages.get(case_id, []) if row["id"] == user_message_id and row["role"] == "USER"), None)
            if not user_row:
                raise APIError("NOT_FOUND", "메시지를 찾을 수 없습니다.", 404)
            rows = self.messages[case_id]
            rows.append({
                "id": assistant_id, "case_id": case_id, "role": "ASSISTANT", "content_redacted": content,
                "model_version": safe_model, "prompt_version": "chat-explanation-1", "finish_reason": "stop",
                "sequence": len(rows) + 1, "created_at": now, "owner_key": actor.owner_key,
            })
            events = self.stream_events.setdefault(user_message_id, [])
            sequence = len(events) + 1
            events.append({
                "message_id": user_message_id, "sequence": sequence, "event_type": "assistant.delta",
                "payload_redacted": {"message_id": str(assistant_id), "delta": content, "generated_by": generated_by},
                "expires_at": now + timedelta(hours=24), "created_at": now,
            })
            events.append({
                "message_id": user_message_id, "sequence": sequence + 1, "event_type": "message.completed",
                "payload_redacted": {"assistant_message_id": str(assistant_id), "finish_reason": "stop", "usage_bucket": "unavailable", "model": model},
                "expires_at": now + timedelta(hours=24), "created_at": now,
            })
        return await self.get_stream_events(actor, case_id, user_message_id, 0)

    async def get_stream_events(
        self, actor: Actor, case_id: UUID, message_id: UUID, after_sequence: int,
    ) -> list[dict[str, Any]]:
        await self.get_case(actor, case_id)
        if self.supabase:
            messages = await self._rest("GET", "messages", params={"id": f"eq.{message_id}", "select": "id,conversation_id", "limit": 1})
            if not messages:
                raise APIError("NOT_FOUND", "메시지를 찾을 수 없습니다.", 404)
            conversations = await self._rest("GET", "conversations", params={"id": f"eq.{messages[0]['conversation_id']}", "case_id": f"eq.{case_id}", "select": "id", "limit": 1})
            if not conversations:
                raise APIError("NOT_FOUND", "메시지를 찾을 수 없습니다.", 404)
            rows = await self._rest("GET", "message_stream_events", params={
                "message_id": f"eq.{message_id}", "sequence": f"gt.{after_sequence}",
                "expires_at": f"gt.{utcnow().isoformat()}", "select": "sequence,event_type,payload_redacted,expires_at", "order": "sequence.asc",
            })
            if not rows:
                any_rows = await self._rest("GET", "message_stream_events", params={"message_id": f"eq.{message_id}", "select": "sequence", "limit": 1})
                if any_rows:
                    raise APIError("STREAM_EXPIRED", "재생 가능한 스트림 이벤트가 만료되었습니다.", 410)
            return rows
        message = next((row for row in self.messages.get(case_id, []) if row["id"] == message_id and row.get("owner_key") == actor.owner_key), None)
        if not message:
            raise APIError("NOT_FOUND", "메시지를 찾을 수 없습니다.", 404)
        all_rows = self.stream_events.get(message_id, [])
        active = [deepcopy(row) for row in all_rows if row["sequence"] > after_sequence and row["expires_at"] > utcnow()]
        if not active and all_rows and max(row["expires_at"] for row in all_rows) <= utcnow():
            raise APIError("STREAM_EXPIRED", "재생 가능한 스트림 이벤트가 만료되었습니다.", 410)
        return active

    async def create_consent(
        self, actor: Actor, scope: list[str], recipient: str, policy_version: str, expires_at: datetime,
        idempotency_key: UUID,
    ) -> dict[str, Any]:
        if actor.kind != "USER":
            raise APIError("AUTH_REQUIRED", "로그인이 필요합니다.", 401)
        now = utcnow()
        if expires_at <= now or expires_at > now + timedelta(days=90):
            raise APIError("VALIDATION_ERROR", "동의 만료는 현재부터 90일 이내여야 합니다.", 400)
        row = {
            "id": uuid4(), "user_id": actor.id, "type": "CONSULTATION_PREVIEW", "scope": scope,
            "recipient": recipient, "policy_version": policy_version, "status": "GRANTED",
            "granted_at": now, "withdrawn_at": None, "expires_at": expires_at,
            "idempotency_key": idempotency_key, "created_at": now, "updated_at": now,
        }
        if self.supabase:
            await self.ensure_profile(actor.id)
            rows = await self._rest("POST", "consent_records", body=row, prefer="return=representation")
            return rows[0]
        self.consents[row["id"]] = deepcopy(row)
        return row

    async def get_consent(self, actor: Actor, consent_id: UUID) -> dict[str, Any]:
        if actor.kind != "USER":
            raise APIError("AUTH_REQUIRED", "로그인이 필요합니다.", 401)
        if self.supabase:
            rows = await self._rest("GET", "consent_records", params={"id": f"eq.{consent_id}", "user_id": f"eq.{actor.id}", "select": "*", "limit": 1})
            if not rows:
                raise APIError("NOT_FOUND", "동의 기록을 찾을 수 없습니다.", 404)
            return rows[0]
        row = self.consents.get(consent_id)
        if not row or row["user_id"] != actor.id:
            raise APIError("NOT_FOUND", "동의 기록을 찾을 수 없습니다.", 404)
        result = deepcopy(row)
        if result["status"] == "GRANTED" and result["expires_at"] <= utcnow():
            result["status"] = "EXPIRED"
            self.consents[consent_id]["status"] = "EXPIRED"
        return result

    async def withdraw_consent(self, actor: Actor, consent_id: UUID) -> dict[str, Any]:
        if actor.aal != "aal2":
            raise APIError("AUTH_REQUIRED", "재인증이 필요한 작업입니다.", 401)
        current = await self.get_consent(actor, consent_id)
        if current["status"] == "WITHDRAWN":
            return current
        now = utcnow()
        if self.supabase:
            result = await self._rest("POST", "rpc/withdraw_consultation_consent", body={"p_consent": consent_id, "p_user": actor.id})
            if not result:
                raise APIError("NOT_FOUND", "동의 기록을 찾을 수 없습니다.", 404)
            return await self.get_consent(actor, consent_id)
        self.consents[consent_id].update({"status": "WITHDRAWN", "withdrawn_at": now, "updated_at": now})
        for preview in self.consultation_previews.values():
            if preview["consent_id"] == consent_id:
                preview["status"] = "CANCELLED"
        return deepcopy(self.consents[consent_id])

    async def prepare_consultation(
        self, actor: Actor, consent_id: UUID, case_id: UUID, selected_fields: list[str], payload: dict[str, Any],
    ) -> dict[str, Any]:
        consent = await self.get_consent(actor, consent_id)
        if consent["status"] != "GRANTED" or consent["expires_at"] <= utcnow():
            raise APIError("CONSENT_REQUIRED", "유효한 상담 미리보기 동의가 필요합니다.", 422)
        if not set(selected_fields).issubset(set(consent["scope"])):
            raise APIError("CONSENT_REQUIRED", "선택 필드가 동의 범위를 벗어났습니다.", 422)
        await self.get_case(actor, case_id)
        row = {
            "id": uuid4(), "consent_id": consent_id, "case_id": case_id, "user_id": actor.id,
            "recipient": consent["recipient"], "selected_fields": selected_fields, "payload_redacted": payload,
            "status": "PREVIEW_ONLY", "expires_at": min(consent["expires_at"], utcnow() + timedelta(hours=24)),
            "created_at": utcnow(), "updated_at": utcnow(),
        }
        if self.supabase:
            rows = await self._rest("POST", "consultation_previews", body=row, prefer="return=representation")
            return rows[0]
        self.consultation_previews[row["id"]] = deepcopy(row)
        return row

    async def request_account_deletion(self, actor: Actor) -> dict[str, Any]:
        if actor.kind != "USER" or actor.aal != "aal2":
            raise APIError("AUTH_REQUIRED", "계정 재인증이 필요합니다.", 401)
        now = utcnow()
        row = {
            "id": uuid4(), "requester_user_id": actor.id, "anonymous_session_id": None, "case_id": None,
            "scope": {"account": True, "db": True, "storage": True, "vector": True, "cache": True, "notifications": True, "outbox": True},
            "status": "QUEUED", "dedupe_key": f"account:{actor.id}", "attempt_count": 0,
            "next_attempt_at": now, "backup_rolloff_at": now + timedelta(days=30),
            "result_manifest": {}, "created_at": now, "updated_at": now,
        }
        if self.supabase:
            result = await self._rest("POST", "rpc/request_account_deletion", body={"p_user": actor.id})
            if isinstance(result, list):
                result = result[0] if result else None
            if not result:
                raise APIError("VERSION_CONFLICT", "이미 계정 삭제가 진행 중입니다.", 409)
            return result
        existing = next((job for job in self.deletion_jobs.values() if job["requester_user_id"] == actor.id and job["status"] in {"QUEUED", "RUNNING"}), None)
        if existing:
            return deepcopy(existing)
        self.deletion_jobs[row["id"]] = deepcopy(row)
        return row

    async def create_admin_draft(
        self, actor: Actor, kind: str, resource_key: str, payload: dict[str, Any], reason: str,
    ) -> dict[str, Any]:
        if not await self.has_admin_role(actor):
            raise APIError("FORBIDDEN", "관리자 AAL2 권한이 필요합니다.", 403)
        from .security import canonical_hash
        digest = canonical_hash(payload).hex()
        if self.supabase:
            result = await self._rest("POST", "rpc/admin_create_draft", body={
                "p_actor": actor.id, "p_kind": kind.upper(), "p_resource_key": resource_key,
                "p_payload": payload, "p_reason": reason,
            })
            if isinstance(result, list):
                result = result[0]
            return self._admin_public(result)
        revisions = [row["revision"] for row in self.admin_resources.values() if row["kind"] == kind and row["resource_key"] == resource_key]
        row = {"id": uuid4(), "kind": kind, "resource_key": resource_key, "revision": max(revisions, default=0) + 1,
               "state": "DRAFT", "payload": deepcopy(payload), "payload_hash": digest, "reason": reason,
               "created_by": actor.id, "created_at": utcnow(), "published_at": None}
        self.admin_resources[row["id"]] = row
        return self._admin_public(row)

    @staticmethod
    def _admin_public(row: dict[str, Any]) -> dict[str, Any]:
        digest = str(row["payload_hash"]).removeprefix("\\x")
        return {"resource_id": row.get("resource_id") or row["id"], "kind": str(row["kind"]).lower(),
                "resource_key": row["resource_key"], "revision": row["revision"], "state": row["state"],
                "payload_hash": digest, "created_at": row["created_at"], "published_at": row.get("published_at")}

    async def publish_admin_resource(self, actor: Actor, kind: str, resource_id: UUID, expected_hash: str, reason: str, request_id: UUID) -> dict[str, Any]:
        if not await self.has_admin_role(actor):
            raise APIError("FORBIDDEN", "관리자 AAL2 권한이 필요합니다.", 403)
        if self.supabase:
            result = await self._rest("POST", "rpc/admin_publish_resource", body={
                "p_actor": actor.id, "p_kind": kind.upper(), "p_resource": resource_id,
                "p_expected_hash": "\\x" + expected_hash, "p_reason": reason, "p_request_id": request_id,
            })
            if isinstance(result, list):
                result = result[0]
            return self._admin_public(result)
        row = self.admin_resources.get(resource_id)
        if not row or row["kind"] != kind:
            raise APIError("NOT_FOUND", "관리자 리소스를 찾을 수 없습니다.", 404)
        if row["state"] != "DRAFT" or not hmac.compare_digest(row["payload_hash"], expected_hash):
            raise APIError("VERSION_CONFLICT", "리소스 상태 또는 해시가 변경되었습니다.", 409)
        for current in self.admin_resources.values():
            if current["kind"] == kind and current["resource_key"] == row["resource_key"] and current["state"] == "PUBLISHED":
                current["state"] = "SUPERSEDED"
        row["state"] = "PUBLISHED"
        row["published_at"] = utcnow()
        return self._admin_public(row)

    async def rollback_admin_resource(self, actor: Actor, kind: str, resource_id: UUID, target_revision: int, reason: str, request_id: UUID) -> dict[str, Any]:
        if not await self.has_admin_role(actor):
            raise APIError("FORBIDDEN", "관리자 AAL2 권한이 필요합니다.", 403)
        if self.supabase:
            result = await self._rest("POST", "rpc/admin_rollback_resource", body={
                "p_actor": actor.id, "p_kind": kind.upper(), "p_resource": resource_id,
                "p_target_revision": target_revision, "p_reason": reason, "p_request_id": request_id,
            })
            if isinstance(result, list):
                result = result[0]
            return self._admin_public(result)
        current = self.admin_resources.get(resource_id)
        if not current or current["kind"] != kind:
            raise APIError("NOT_FOUND", "관리자 리소스를 찾을 수 없습니다.", 404)
        target = next((row for row in self.admin_resources.values() if row["kind"] == kind and row["resource_key"] == current["resource_key"] and row["revision"] == target_revision), None)
        if not target:
            raise APIError("NOT_FOUND", "롤백 대상 revision을 찾을 수 없습니다.", 404)
        draft = await self.create_admin_draft(actor, kind, current["resource_key"], target["payload"], reason)
        return await self.publish_admin_resource(actor, kind, draft["resource_id"], draft["payload_hash"], reason, request_id)

    async def get_kill_switch(self, actor: Actor, name: str) -> dict[str, Any]:
        if not await self.has_admin_role(actor):
            raise APIError("FORBIDDEN", "관리자 AAL2 권한이 필요합니다.", 403)
        if self.supabase:
            rows = await self._rest("GET", "kill_switches", params={"name": f"eq.{name}", "select": "*", "limit": 1})
            if not rows:
                raise APIError("NOT_FOUND", "kill switch를 찾을 수 없습니다.", 404)
            return rows[0]
        row = self.kill_switches.get(name)
        if not row:
            raise APIError("NOT_FOUND", "kill switch를 찾을 수 없습니다.", 404)
        return deepcopy(row)

    async def set_kill_switch(self, actor: Actor, name: str, enabled: bool, expected_version: int, reason: str, expires_at: datetime | None, request_id: UUID) -> dict[str, Any]:
        if not await self.has_admin_role(actor):
            raise APIError("FORBIDDEN", "관리자 AAL2 권한이 필요합니다.", 403)
        if self.supabase:
            result = await self._rest("POST", "rpc/set_kill_switch_v2", body={
                "p_actor": actor.id, "p_name": name, "p_enabled": enabled, "p_expected_version": expected_version,
                "p_reason": reason, "p_expires_at": expires_at, "p_request_id": request_id,
            })
            if isinstance(result, list):
                result = result[0]
            return result
        row = self.kill_switches.get(name)
        if not row:
            raise APIError("NOT_FOUND", "kill switch를 찾을 수 없습니다.", 404)
        if row["version"] != expected_version:
            raise APIError("VERSION_CONFLICT", "kill switch version이 변경되었습니다.", 409)
        row.update({"enabled": enabled, "reason": reason, "expires_at": expires_at, "version": expected_version + 1, "updated_at": utcnow()})
        return deepcopy(row)



    async def feature_enabled(self, name: str, configured_default: bool = False) -> bool:
        if self.supabase:
            rows = await self._rest("GET", "kill_switches", params={"name": f"eq.{name}", "select": "enabled,expires_at", "limit": 1})
            if not rows:
                return False
            row = rows[0]
            expires_at = row.get("expires_at")
            if expires_at:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry <= utcnow():
                    return False
            return bool(row.get("enabled")) and configured_default
        row = self.kill_switches.get(name)
        if not row or not row.get("enabled"):
            return False
        if row.get("expires_at") and row["expires_at"] <= utcnow():
            return False
        return configured_default
