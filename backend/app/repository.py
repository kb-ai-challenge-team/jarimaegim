from __future__ import annotations
import logging
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import UUID, uuid4
from supabase import Client, create_client
from .config import Settings
from .models import CaseCreate, CaseInput, CasePatch, CaseRecord

logger = logging.getLogger(__name__)


def _today() -> str:
    """Module-level seam so tests can monkeypatch the clock without touching Repository state."""
    return datetime.now(UTC).date().isoformat()


class Repository:
    """Supabase-backed in production, isolated in-memory storage for local no-key development."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = RLock()
        self._sessions: dict[UUID, dict[str, Any]] = {}
        self._cases: dict[UUID, CaseRecord] = {}
        self._daily_turns: dict[str, int] = {}
        self._daily_turns_day: str = ""
        self.supabase: Client | None = None
        if settings.supabase_configured:
            self.supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
            logger.warning("일일 턴 한도(ai_daily_request_limit)는 Supabase 모드에서도 프로세스 로컬 메모리로 집계됩니다: "
                            "워커 재시작이나 다중 워커 배포에서는 한도가 실제로 적용되지 않습니다. 이는 알려진 한계이며, "
                            "영구 카운터가 필요하면 별도 마이그레이션(daily_turn_counters 테이블)이 먼저 필요합니다.")

    def create_session(self, token_hash: str, expires_at: datetime) -> UUID:
        session_id = uuid4()
        if self.supabase:
            self.supabase.table("anonymous_sessions").insert({
                "id": str(session_id), "token_hash": token_hash, "token_version": 1,
                "status": "ACTIVE", "last_seen_at": datetime.now(UTC).isoformat(),
                "retention_class": "ANON_24H", "expires_at": expires_at.isoformat()
            }).execute()
        else:
            with self._lock:
                self._sessions[session_id] = {"id": session_id, "token_hash": token_hash, "status": "ACTIVE", "expires_at": expires_at}
        return session_id

    def verify_session(self, token_hash: str) -> UUID | None:
        now = datetime.now(UTC)
        if self.supabase:
            result = self.supabase.table("anonymous_sessions").select("id,expires_at,status").eq("token_hash", token_hash).eq("status", "ACTIVE").limit(1).execute()
            if not result.data:
                return None
            row = result.data[0]
            if datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) <= now:
                return None
            return UUID(row["id"])
        with self._lock:
            for session_id, session in self._sessions.items():
                if session["token_hash"] == token_hash and session["status"] == "ACTIVE" and session["expires_at"] > now:
                    return session_id
        return None

    def consume_daily_turn(self, session_id: UUID, limit: int) -> bool:
        """Atomically check-and-increment today's turn count for a session; returns whether the turn is allowed.
        Process-local in both Supabase and in-memory mode (see the warning logged in __init__) — this is a known
        gap against production multi-worker deployment, not a silent one. The counter dict is keyed by session id
        only and wiped whenever the wall-clock day (via the module-level _today seam) advances, so entries never
        outlive the day they were spent on and cannot grow unbounded across restarts-free long-running processes."""
        if limit <= 0:
            return False
        today = _today()
        with self._lock:
            if self._daily_turns_day != today:
                self._daily_turns.clear()
                self._daily_turns_day = today
            spent = self._daily_turns.get(str(session_id), 0)
            if spent >= limit:
                return False
            self._daily_turns[str(session_id)] = spent + 1
            return True

    def create_case(self, owner_session: UUID, payload: CaseCreate) -> CaseRecord:
        now = datetime.now(UTC)
        record = CaseRecord(id=uuid4(), title=payload.title, version=1, status="ACTIVE", inputs=payload.inputs, created_at=now, updated_at=now)
        if self.supabase:
            self.supabase.table("cases").insert({"id": str(record.id), "anonymous_session_id": str(owner_session), "title": record.title, "status": "ACTIVE", "version": 1}).execute()
            rows = [{"case_id": str(record.id), "field": key, "value_json": value.value if hasattr(value, "value") else value, "source": "FORM", "confirmed_at": now.isoformat()} for key, value in record.inputs.model_dump().items() if value is not None]
            self.supabase.table("case_inputs").insert(rows).execute()
        else:
            with self._lock:
                self._cases[record.id] = record
                self._sessions[owner_session].setdefault("cases", set()).add(record.id)
        return record

    def get_case(self, owner_session: UUID, case_id: UUID) -> CaseRecord | None:
        if self.supabase:
            result = self.supabase.table("cases").select("id,title,version,status,created_at,updated_at,case_inputs(field,value_json)").eq("id", str(case_id)).eq("anonymous_session_id", str(owner_session)).eq("status", "ACTIVE").limit(1).execute()
            if not result.data:
                return None
            row = result.data[0]
            inputs = {item["field"]: item["value_json"] for item in row.pop("case_inputs", [])}
            return CaseRecord(**row, inputs=CaseInput(**inputs))
        with self._lock:
            owned = case_id in self._sessions.get(owner_session, {}).get("cases", set())
            return self._cases.get(case_id) if owned else None

    def update_case(self, owner_session: UUID, case_id: UUID, expected_version: int, payload: CasePatch) -> CaseRecord | None:
        existing = self.get_case(owner_session, case_id)
        if not existing:
            return None
        if existing.version != expected_version:
            raise VersionError(existing.version)
        merged_inputs = existing.inputs.model_dump()
        merged_inputs.update(payload.inputs)
        updated = existing.model_copy(update={"title": payload.title or existing.title, "version": existing.version + 1, "inputs": CaseInput(**merged_inputs), "updated_at": datetime.now(UTC)})
        if self.supabase:
            self.supabase.table("cases").update({"title": updated.title, "version": updated.version, "updated_at": updated.updated_at.isoformat()}).eq("id", str(case_id)).eq("anonymous_session_id", str(owner_session)).eq("version", expected_version).execute()
            for field, value in payload.inputs.items():
                if value is None:
                    continue  # value_json is NOT NULL; a None patch value is a no-op rather than a clear.
                self.supabase.table("case_inputs").upsert({"case_id": str(case_id), "field": field, "value_json": value, "source": "USER", "confirmed_at": updated.updated_at.isoformat()}).execute()
        else:
            with self._lock:
                self._cases[case_id] = updated
        return updated

    def delete_case(self, owner_session: UUID, case_id: UUID) -> bool:
        existing = self.get_case(owner_session, case_id)
        if not existing:
            return False
        if self.supabase:
            self.supabase.table("cases").update({"status": "DELETING"}).eq("id", str(case_id)).eq("anonymous_session_id", str(owner_session)).execute()
        else:
            with self._lock:
                self._cases.pop(case_id, None)
                self._sessions[owner_session].get("cases", set()).discard(case_id)
        return True


class VersionError(Exception):
    def __init__(self, current: int):
        self.current = current
