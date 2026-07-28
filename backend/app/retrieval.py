"""의미 검색. 챗도 에이전트도 이 함수 하나를 쓴다.

유사도는 결과 순서에만 관여한다. 통과·탈락은 원천이 준 구조화 필드의 결정론적 비교로만
정해지고, 그 비교 결과만 matched_conditions에 남는다 — 설계 §6.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from openai import OpenAI
from supabase import Client, create_client

from .config import Settings
from .models import Provenance, RetrievalResponse, RetrievedDocument

EXCERPT_LIMIT = 300
NOT_CONFIGURED = "의미 검색이 아직 연결되지 않았습니다. 저장된 공고 목록은 계속 확인할 수 있습니다."
UNAVAILABLE = "근거 검색이 지연되고 있습니다. 저장된 공식 원문은 계속 사용할 수 있습니다."

BASE_UNKNOWNS = ("공식 원문의 지역·업종·업력·제외 조건을 직접 확인해야 합니다.",)


class RetrievalService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Client | None = (
            create_client(settings.supabase_url, settings.supabase_service_role_key)
            if settings.supabase_configured else None)
        self._openai = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def _embed(self, text: str) -> list[float]:
        response = self._openai.embeddings.create(model=self.settings.embedding_model, input=[text])
        return response.data[0].embedding

    async def search(self, query: str, *, kinds: list[str] | None = None,
                     regions: list[str] | None = None, only_open: bool = True,
                     limit: int = 8, today: date | None = None) -> RetrievalResponse:
        if not self.settings.retrieval_configured or self._client is None:
            return RetrievalResponse(status="integration_pending", message=NOT_CONFIGURED)
        text = (query or "").strip()
        if not text:
            return RetrievalResponse(status="success")

        try:
            vector = await asyncio.to_thread(self._embed, text)
            rows = await asyncio.to_thread(self._rpc, vector, kinds, regions, only_open, limit)
        except Exception:  # noqa: BLE001 — 검색 실패가 호출자를 죽이면 안 된다
            return RetrievalResponse(status="unavailable", message=UNAVAILABLE)

        as_of = today or datetime.now(UTC).date()
        items = [self._to_document(row, regions, as_of) for row in rows]
        return RetrievalResponse(items=items, status="success")

    def _rpc(self, vector: list[float], kinds: list[str] | None, regions: list[str] | None,
             only_open: bool, limit: int) -> list[dict[str, Any]]:
        response = self._client.rpc("search_knowledge", {
            "query_embedding": vector, "match_kinds": kinds, "match_regions": regions,
            "only_open": only_open, "match_count": limit,
        }).execute()
        return response.data or []

    @staticmethod
    def _to_document(row: dict[str, Any], asked_regions: list[str] | None,
                     today: date) -> RetrievedDocument:
        matched: list[str] = []
        unknown: list[str] = list(BASE_UNKNOWNS)

        row_regions = row.get("regions")
        if row_regions and asked_regions:
            overlap = sorted(set(row_regions) & set(asked_regions))
            if overlap:
                matched.append(f"지원지역에 {', '.join(overlap)}이(가) 포함됨")
        elif not row_regions:
            unknown.append("지원지역이 공고에 명시되지 않아 지역 제한을 확인할 수 없습니다.")

        end = row.get("application_end")
        if end:
            closes = date.fromisoformat(end)
            if closes >= today:
                matched.append(f"접수마감 {end}로 오늘 기준 진행 중")
            else:
                matched.append(f"접수마감 {end}로 이미 종료됨")
        else:
            unknown.append("접수기간이 공고에 명시되지 않았습니다.")

        limit_years = row.get("business_age_limit_years")
        if limit_years:
            matched.append(f"업력 상한 {limit_years}년")

        body = row.get("body_text") or ""
        excerpt = body if len(body) <= EXCERPT_LIMIT else body[:EXCERPT_LIMIT].rstrip() + "…"
        provenance = Provenance(
            source_name=row["provider"], official_url=row["official_url"],
            source_as_of=row.get("source_as_of"), collected_at=row.get("collected_at"),
            industry_scope="전 업종",
            spatial_unit=", ".join(row_regions) if row_regions else "지역 제한 미상",
            # 검색은 원문을 찾아 줄 뿐 자격을 판정하지 않는다. 신뢰도를 높게 말할 근거가 없다.
            confidence="LOW",
            limitations=["의미 검색 결과이며 신청 자격을 판정하지 않습니다.",
                         "공고 원문의 세부 자격은 확인이 필요합니다."],
        )
        return RetrievedDocument(
            id=row["id"], kind=row["kind"], title=row["title"], organization=row["organization"],
            official_url=row["official_url"], provider=row["provider"], category=row["category"],
            excerpt=excerpt, similarity=float(row.get("similarity") or 0.0),
            source_as_of=row.get("source_as_of"), collected_at=row.get("collected_at"),
            application_start=row.get("application_start"), application_end=end,
            matched_conditions=matched, unknown_conditions=unknown, provenance=provenance,
        )
