"""인덱스에서 목록을 읽는다. 벡터를 쓰지 않는 평범한 조회다.

/programs가 요청마다 공공 API를 때리던 경로를 대체한다 — 설계 §1 결정 6.
display를 그대로 반환한다. 컬럼을 내보내면 lib/types.ts의 유니온이 깨진다.
"""
from __future__ import annotations

import asyncio
from typing import Any

from supabase import Client, create_client

from .config import Settings

TABLE = "knowledge_documents"
LIST_LIMIT = 200
EMPTY_PROGRAMS = "공고 인덱스가 비어 있습니다. 수집 파이프라인이 한 번 이상 실행되어야 표시됩니다."
EMPTY_PRODUCTS = "KB 금융상품 공시 인덱스가 비어 있습니다. 수집 파이프라인 실행 상태를 확인해 주세요."


class KnowledgeReader:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Client | None = (
            create_client(settings.supabase_url, settings.supabase_service_role_key)
            if settings.supabase_configured else None)

    async def programs(self) -> list[dict[str, Any]]:
        return await self._list("PROGRAM")

    async def kb_products(self) -> list[dict[str, Any]]:
        return await self._list("KB_PRODUCT")

    async def _list(self, kind: str) -> list[dict[str, Any]]:
        if self._client is None:
            return []
        try:
            return await asyncio.to_thread(self._select, kind)
        except Exception:  # noqa: BLE001 — 조회 실패는 빈 상태로 내려간다
            return []

    def _select(self, kind: str) -> list[dict[str, Any]]:
        response = (self._client.table(TABLE).select("display,application_end")
                    .eq("kind", kind).neq("status", "CLOSED")
                    .order("application_end", desc=False).limit(LIST_LIMIT).execute())
        return [row["display"] for row in (response.data or []) if row.get("display")]

    async def freshness(self) -> dict[str, Any]:
        if self._client is None:
            return {"documents": 0, "missing_embeddings": 0, "last_collected_at": None}
        try:
            return await asyncio.to_thread(self._freshness)
        except Exception:  # noqa: BLE001
            return {"documents": 0, "missing_embeddings": 0, "last_collected_at": None}

    def _freshness(self) -> dict[str, Any]:
        total = self._client.table(TABLE).select("id", count="exact").limit(1).execute()
        missing = (self._client.table(TABLE).select("id", count="exact")
                   .is_("embedding", "null").limit(1).execute())
        latest = (self._client.table(TABLE).select("collected_at")
                  .order("collected_at", desc=True).limit(1).execute())
        rows = latest.data or []
        return {"documents": total.count or 0, "missing_embeddings": missing.count or 0,
                "last_collected_at": rows[0]["collected_at"] if rows else None}
