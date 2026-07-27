import asyncio
from datetime import date

import pytest

from app.config import Settings
from app.retrieval import RetrievalService

HIT = {
    "id": "kstartup:1", "kind": "PROGRAM", "title": "서울 청년 창업 지원",
    "organization": "중소벤처기업부", "official_url": "https://www.k-startup.go.kr/x",
    "body_text": "서울 지역 청년 창업자를 대상으로 임차료를 지원합니다. " * 12,
    "provider": "K-Startup", "category": "GOVERNMENT", "source_as_of": None,
    "application_start": "2026-07-01", "application_end": "2026-08-31",
    "regions": ["서울"], "business_age_limit_years": 7,
    "collected_at": "2026-07-27T00:00:00+00:00", "similarity": 0.83,
}


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def execute(self):
        return type("Result", (), {"data": self.rows})()


class FakeClient:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return FakeQuery(self.rows)


def service(rows, *, configured=True) -> RetrievalService:
    settings = Settings(supabase_url="https://x.supabase.co" if configured else "",
                        supabase_service_role_key="k" if configured else "",
                        openai_api_key="k" if configured else "",
                        embedding_model="text-embedding-3-small" if configured else "")
    svc = RetrievalService(settings)
    svc._client = FakeClient(rows)
    svc._embed = lambda text: [0.0] * 1536
    return svc


def search(svc, *args, **kwargs):
    return asyncio.run(svc.search(*args, **kwargs))


def test_search_without_configuration_returns_integration_pending():
    result = search(service([], configured=False), "청년 창업")
    assert result.status == "integration_pending"
    assert result.items == []
    assert result.message


def test_search_returns_documents_with_an_excerpt_and_similarity():
    result = search(service([HIT]), "청년 창업")
    assert result.status == "success"
    assert result.evidence_grade == "C"
    item = result.items[0]
    assert item.id == "kstartup:1"
    assert item.similarity == pytest.approx(0.83)
    assert len(item.excerpt) <= 301
    # 불변조건 3 — 모든 데이터 표면은 출처를 달고 나간다.
    assert item.provenance.source_name == "K-Startup"
    assert item.provenance.confidence == "LOW"
    assert item.provenance.limitations


def test_matched_conditions_carry_only_deterministic_comparisons():
    result = search(service([HIT]), "청년 창업", regions=["서울"], today=date(2026, 7, 27))
    item = result.items[0]
    assert any("서울" in line for line in item.matched_conditions)
    assert any("2026-08-31" in line for line in item.matched_conditions)
    # 유사도는 판정이 아니므로 근거 문장에 새어 들어오면 안 된다.
    assert not any("유사" in line or "0.83" in line for line in item.matched_conditions)
    assert item.unknown_conditions


def test_a_document_without_a_region_is_reported_as_unknown_not_matched():
    hit = dict(HIT, regions=None)
    result = search(service([hit]), "청년 창업", regions=["서울"], today=date(2026, 7, 27))
    item = result.items[0]
    assert not any("지원지역" in line for line in item.matched_conditions)
    assert any("지역" in line for line in item.unknown_conditions)


def test_an_empty_query_does_not_reach_the_provider():
    svc = service([HIT])
    result = search(svc, "   ")
    assert result.status == "success"
    assert result.items == []
    assert svc._client.calls == []


def test_a_transport_failure_degrades_to_an_empty_result():
    svc = service([HIT])

    def boom(name, params):
        raise RuntimeError("PostgREST down")

    svc._client.rpc = boom
    result = search(svc, "청년 창업")
    assert result.status == "unavailable"
    assert result.items == []
    assert result.message
