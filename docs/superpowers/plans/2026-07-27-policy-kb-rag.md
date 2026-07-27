# 정책공고·KB상품 임베딩 검색(RAG) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지원사업 공고와 KB 금융상품을 임베딩해 Supabase pgvector에 저장하고, 백엔드가 의미 검색으로 원문 근거를 찾을 수 있게 한다.

**Architecture:** 쓰기(수집·정규화·임베딩·upsert)는 `pipeline/policy/`의 파이썬 스크립트가 단독 소유하고, 읽기는 백엔드 `RetrievalService`가 Supabase RPC 한 번으로 한다. 정규화는 순수함수라 네트워크 없이 테스트하고, 유사도는 결과 순서에만 관여하며 자격 판정은 구조화 필드의 결정론적 비교로만 한다.

**Tech Stack:** Python 3.12 · FastAPI · supabase-py(PostgREST) · pgvector 0.8.2 / HNSW · OpenAI `text-embedding-3-small`(1536) · pytest

**설계 문서:** `docs/superpowers/specs/2026-07-27-policy-kb-rag-design.md`

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `supabase/migrations/202607280001_knowledge_documents.sql` | 테이블·HNSW 인덱스·RLS·`search_knowledge` 함수 |
| `scripts/apply-migration.py` | `SUPABASE_DB_URL`로 SQL 파일 적용 (psql·supabase CLI 둘 다 없음) |
| `pipeline/policy/normalize.py` | 원시 레코드 → `KnowledgeDocument`. **순수함수.** 네트워크·시계 접근 없음 |
| `pipeline/policy/fetch.py` | 공공 API 3종 호출 + 페이지네이션. I/O만 |
| `pipeline/policy/embed.py` | 텍스트 배치 → 벡터 |
| `pipeline/policy/index.py` | 엔트리포인트. fetch → normalize → diff → embed → upsert → prune |
| `pipeline/policy/verify_index.py` | 사람이 읽는 인덱스 리포트 |
| `pipeline/policy/fixtures/*.json` | 키를 지운 실제 응답 스냅샷 |
| `pipeline/policy/test_normalize.py` | 정규화 회귀 테스트 (무게중심) |
| `backend/app/retrieval.py` | `RetrievalService.search()`. 챗을 모르는 평범한 async 함수 |
| `backend/tests/test_retrieval.py` | 가짜 클라이언트로 검색 계약 검증 |

`normalize.py`가 `fetch.py`를 import하지 않는 것이 중요하다. 그래야 픽스처만으로 전부 테스트된다.

**경계 규칙:** 이 계획의 어떤 파일도 `chat_tools`·`chat_stream`·`mcp_client`를 import하지 않는다(설계 §12).

---

### Task 1: 마이그레이션과 직렬화 실측

PostgREST로 `vector` 컬럼을 읽고 쓸 때 파이썬 `list[float]`가 그대로 통하는지는 문서로 확정할 수 없다. 나머지를 다 만든 뒤 여기서 막히면 손해가 크므로 **가장 먼저 실측한다.**

**Files:**
- Create: `supabase/migrations/202607280001_knowledge_documents.sql`
- Create: `scripts/apply-migration.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 마이그레이션 SQL 작성**

`supabase/migrations/202607280001_knowledge_documents.sql`:

```sql
-- 공고와 KB상품이 한 테이블에 산다. 검색 계층을 공용으로 쓰므로 질의 한 번이
-- 두 종류를 함께 훑을 수 있어야 한다. listings와 같은 성격의 공용 참조 데이터다.
create extension if not exists vector with schema extensions;

create table public.knowledge_documents (
  id text primary key,
  kind text not null check (kind in ('PROGRAM','KB_PRODUCT')),
  provider text not null,
  category text not null,
  title text not null,
  organization text not null,
  official_url text not null check (official_url ~ '^https://'),

  -- 임베딩에 실제로 들어간 텍스트. 인용을 사후 검증하려면 이게 남아 있어야 한다.
  body_text text not null,
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  -- null 허용. 임베딩에 실패한 문서도 행은 남기고 검색에서만 뺀다.
  embedding extensions.vector(1536),
  embedding_model text,

  -- 코드가 판정에 쓰는 구조화 필드. 원천이 주지 않으면 null이고 추정하지 않는다.
  regions text[],
  business_age_limit_years int,
  application_start date,
  application_end date,
  status text not null check (status in ('ACTIVE','CLOSED','UNKNOWN')),
  source_as_of date,

  raw jsonb not null,
  -- 프론트가 이미 쓰는 Program·KbProduct 모양 그대로의 표시용 페이로드.
  -- 컬럼을 그대로 내보내면 lib/types.ts의 유니온이 깨지므로 정규화기가 함께 만든다.
  display jsonb not null,
  collected_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index knowledge_documents_embedding_idx on public.knowledge_documents
  using hnsw (embedding extensions.vector_cosine_ops);
create index knowledge_documents_kind_status_idx on public.knowledge_documents (kind, status);
create index knowledge_documents_provider_collected_idx on public.knowledge_documents (provider, collected_at);

alter table public.knowledge_documents enable row level security;

-- 읽기는 공개, 쓰기는 service role만. service role은 RLS를 우회하므로 정책을 따로 두지 않는다.
create policy knowledge_documents_public_read on public.knowledge_documents
  for select to anon, authenticated using (true);

-- 유사도는 순서에만 관여한다. min_similarity는 무관한 문서를 빼는 하한선이지
-- 자격 판정이 아니다. 지역이 null인 문서는 '제한 미상'이므로 떨어뜨리지 않는다.
create function public.search_knowledge(
  query_embedding extensions.vector(1536),
  match_kinds     text[]  default null,
  match_regions   text[]  default null,
  only_open       boolean default true,
  match_count     int     default 8,
  min_similarity  float   default 0.2
) returns table (
  id text, kind text, title text, organization text, official_url text,
  body_text text, provider text, category text, source_as_of date,
  application_start date, application_end date, regions text[],
  business_age_limit_years int, collected_at timestamptz, similarity float
)
language sql stable
as $$
  select d.id, d.kind, d.title, d.organization, d.official_url, d.body_text,
         d.provider, d.category, d.source_as_of, d.application_start, d.application_end,
         d.regions, d.business_age_limit_years, d.collected_at,
         1 - (d.embedding <=> query_embedding) as similarity
  from public.knowledge_documents d
  where d.embedding is not null
    and (match_kinds is null or d.kind = any(match_kinds))
    and (match_regions is null or d.regions is null or d.regions && match_regions)
    and (not only_open or d.status <> 'CLOSED')
    and 1 - (d.embedding <=> query_embedding) >= min_similarity
  order by d.embedding <=> query_embedding
  limit match_count;
$$;

grant execute on function public.search_knowledge to anon, authenticated, service_role;
```

- [ ] **Step 2: psycopg2를 requirements에 추가**

`backend/requirements.txt` 끝에 한 줄 추가:

```
psycopg2-binary==2.9.10
```

바로 위에 주석을 붙인다:

```
# 마이그레이션·파이프라인 도구 전용. FastAPI 런타임은 PostgREST만 쓰므로 import하지 않는다.
```

설치: `backend/.venv/bin/pip install -r backend/requirements.txt`

- [ ] **Step 3: 마이그레이션 러너 작성**

이 저장소에는 `psql`도 `supabase` CLI도 없다. `scripts/apply-migration.py`:

```python
"""Apply a SQL migration file through SUPABASE_DB_URL.

psql과 supabase CLI가 모두 없는 환경을 위한 최소 러너다. 파일 하나를 한 트랜잭션으로
실행하고, 실패하면 전부 롤백한다. 키 값은 절대 출력하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]


def db_url() -> str:
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "SUPABASE_DB_URL" and value.strip():
                return value.strip().strip('"').strip("'")
    raise SystemExit("SUPABASE_DB_URL이 .env에 없습니다.")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-migration.py <path-to-sql>")
    sql_path = Path(sys.argv[1])
    sql = sql_path.read_text()
    conn = psycopg2.connect(db_url())
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql)
        print(f"applied {sql_path.name}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 마이그레이션 적용**

Run: `backend/.venv/bin/python scripts/apply-migration.py supabase/migrations/202607280001_knowledge_documents.sql`
Expected: `applied 202607280001_knowledge_documents.sql`

- [ ] **Step 5: 직렬화 실측 — 이 계획에서 가장 중요한 단계**

임시 스크립트를 스크래치패드에 만들어 돌린다(저장소에 커밋하지 않는다). 확인할 것은 두 가지다: PostgREST upsert로 `list[float]`가 `vector` 컬럼에 들어가는가, RPC 인자로 `list[float]`가 통하는가.

```python
import os, hashlib, json
from datetime import UTC, datetime
from pathlib import Path
from supabase import create_client

ROOT = Path("/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo")
cfg = {}
for line in (ROOT / ".env").read_text().splitlines():
    k, _, v = line.partition("=")
    cfg[k.strip()] = v.strip().strip('"').strip("'")

client = create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])
vec = [0.0] * 1536
vec[0] = 1.0
row = {
    "id": "smoke:1", "kind": "PROGRAM", "provider": "SMOKE", "category": "GOVERNMENT",
    "title": "직렬화 확인용", "organization": "SMOKE", "official_url": "https://example.com/",
    "body_text": "확인용", "content_sha256": hashlib.sha256(b"body").hexdigest(),
    "embedding": vec, "embedding_model": "smoke", "status": "UNKNOWN",
    "regions": ["서울"], "raw": {}, "display": {}, "collected_at": datetime.now(UTC).isoformat(),
}
print("upsert:", client.table("knowledge_documents").upsert(row).execute().data)
hits = client.rpc("search_knowledge", {
    "query_embedding": vec, "match_kinds": ["PROGRAM"], "match_count": 3, "min_similarity": 0.0,
}).execute().data
print("rpc hits:", [(h["id"], round(h["similarity"], 4)) for h in hits])
client.table("knowledge_documents").delete().eq("provider", "SMOKE").execute()
print("cleaned")
```

Run: `backend/.venv/bin/python <스크래치패드 경로>/smoke_vector.py`
Expected: upsert가 행 하나를 반환하고, `rpc hits`에 `('smoke:1', 1.0)`이 찍히고, `cleaned`로 끝난다.

**실패하면:** `list[float]`가 거부되는 경우다. `embedding`과 `query_embedding`을 `json.dumps(vec)` 문자열로 바꿔 다시 돌린다(pgvector의 텍스트 입력 형식 `[1,2,3]`은 JSON 배열 직렬화와 같다). 어느 쪽이 통했는지를 Task 5·Task 12의 코드에 반영한다.

- [ ] **Step 6: 커밋**

```bash
git add supabase/migrations/202607280001_knowledge_documents.sql scripts/apply-migration.py backend/requirements.txt
git commit -m "feat(db): add the knowledge_documents table and search_knowledge function"
```

---

### Task 2: 정규화 공통 유틸

**Files:**
- Create: `pipeline/policy/__init__.py` (빈 파일)
- Create: `pipeline/policy/normalize.py`
- Create: `pipeline/policy/test_normalize.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`pipeline/policy/test_normalize.py`:

```python
from datetime import date

from normalize import (canonical_regions, display_status, parse_compact_date, parse_range_dates,
                       resolve_status, strip_html)


def test_strip_html_removes_tags_and_entities():
    raw = '<p>지원 대상은 <b>중소기업</b>입니다.</p><p>&nbsp;</p><p>문의: A&amp;B</p>'
    assert strip_html(raw) == "지원 대상은 중소기업입니다. 문의: A&B"


def test_strip_html_on_empty_input_returns_empty_string():
    assert strip_html("") == ""
    assert strip_html(None) == ""


def test_parse_compact_date_reads_yyyymmdd():
    assert parse_compact_date("20260812") == date(2026, 8, 12)


def test_parse_compact_date_returns_none_for_unusable_input():
    assert parse_compact_date("") is None
    assert parse_compact_date("99991231") == date(9999, 12, 31)
    assert parse_compact_date("2026-08") is None


def test_parse_range_dates_splits_on_tilde():
    assert parse_range_dates("2026-07-22 ~ 2026-08-18") == (date(2026, 7, 22), date(2026, 8, 18))


def test_parse_range_dates_returns_none_pair_when_unparseable():
    assert parse_range_dates("접수기간 별도 공지") == (None, None)


def test_canonical_regions_normalises_full_names():
    assert canonical_regions("서울특별시") == ["서울"]
    assert canonical_regions("대구광역시") == ["대구"]


def test_canonical_regions_splits_comma_separated_values():
    assert canonical_regions("서울,경기") == ["경기", "서울"]


def test_canonical_regions_returns_none_when_nothing_maps():
    # '전남광주'처럼 원천이 붙여 보낸 값은 어느 지역인지 확정할 수 없으므로 버린다.
    assert canonical_regions("전남광주") is None
    assert canonical_regions("경북대학교 지산학연협력기술연구소") is None
    assert canonical_regions("") is None


def test_resolve_status_closes_only_on_a_past_end_date():
    today = date(2026, 7, 27)
    assert resolve_status(date(2026, 7, 1), today) == "CLOSED"
    assert resolve_status(date(2026, 8, 18), today) == "ACTIVE"
    assert resolve_status(None, today) == "UNKNOWN"


def test_display_status_never_reports_an_open_window_as_an_eligibility_verdict():
    today = date(2026, 7, 27)
    # 접수 중이어도 자격을 판정한 게 아니므로 UNKNOWN이다.
    assert display_status(date(2026, 8, 18), today) == "UNKNOWN"
    assert display_status(None, today) == "UNKNOWN"
    assert display_status(date(2026, 7, 1), today) == "CLOSED"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'normalize'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/policy/normalize.py`:

```python
"""원시 응답 레코드를 KnowledgeDocument로 바꾼다.

이 모듈은 순수함수만 담는다. 네트워크도 시계도 건드리지 않으므로 오늘 날짜가 필요한
함수는 today를 인자로 받는다. 원천이 모양을 바꾸면 test_normalize.py가 먼저 깨진다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

_TAG = re.compile(r"<[^>]+>")
_ENTITIES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "))

# 광역지자체 표기를 짧은 형태로 모은다. 여기에 없는 문자열은 지역으로 인정하지 않는다.
_REGION_ALIASES = {
    "서울": "서울", "서울특별시": "서울", "부산": "부산", "부산광역시": "부산",
    "대구": "대구", "대구광역시": "대구", "인천": "인천", "인천광역시": "인천",
    "광주": "광주", "광주광역시": "광주", "대전": "대전", "대전광역시": "대전",
    "울산": "울산", "울산광역시": "울산", "세종": "세종", "세종특별자치시": "세종",
    "경기": "경기", "경기도": "경기", "강원": "강원", "강원도": "강원", "강원특별자치도": "강원",
    "충북": "충북", "충청북도": "충북", "충남": "충남", "충청남도": "충남",
    "전북": "전북", "전라북도": "전북", "전북특별자치도": "전북",
    "전남": "전남", "전라남도": "전남", "경북": "경북", "경상북도": "경북",
    "경남": "경남", "경상남도": "경남", "제주": "제주", "제주특별자치도": "제주",
    "전국": "전국",
}


def strip_html(value: str | None) -> str:
    text = _TAG.sub(" ", value or "")
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def parse_compact_date(value: str | None) -> date | None:
    """'20260812' 형식만 읽는다. 다른 형식은 추측하지 않고 None을 낸다."""
    text = (value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def parse_iso_date(value: str | None) -> date | None:
    text = (value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_range_dates(value: str | None) -> tuple[date | None, date | None]:
    """'2026-07-22 ~ 2026-08-18'을 두 날짜로 가른다."""
    text = (value or "").strip()
    if "~" not in text:
        return (None, None)
    head, _, tail = text.partition("~")
    return (parse_iso_date(head.strip()), parse_iso_date(tail.strip()))


def canonical_regions(value: str | None) -> list[str] | None:
    """지역 문자열을 짧은 표기 목록으로 바꾼다. 하나도 못 맞추면 None(=제한 미상)."""
    tokens = [token.strip() for token in re.split(r"[,/·]", value or "") if token.strip()]
    mapped = sorted({_REGION_ALIASES[token] for token in tokens if token in _REGION_ALIASES})
    return mapped or None


def resolve_status(application_end: date | None, today: date) -> str:
    """원천이 준 날짜의 산술이지 판단이 아니다. 날짜가 없으면 UNKNOWN으로 남는다."""
    if application_end is None:
        return "UNKNOWN"
    return "CLOSED" if application_end < today else "ACTIVE"


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    kind: str
    provider: str
    category: str
    title: str
    organization: str
    official_url: str
    body_text: str
    status: str
    raw: dict[str, Any]
    # 프론트가 이미 쓰는 Program/KbProduct 모양. 엔드포인트가 이걸 그대로 반환한다.
    display: dict[str, Any]
    regions: list[str] | None = None
    business_age_limit_years: int | None = None
    application_start: date | None = None
    application_end: date | None = None
    source_as_of: date | None = None

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.body_text.encode("utf-8")).hexdigest()

    def to_row(self, *, collected_at: str, embedding: list[float] | None,
               embedding_model: str | None) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "provider": self.provider, "category": self.category,
            "title": self.title, "organization": self.organization, "official_url": self.official_url,
            "body_text": self.body_text, "content_sha256": self.content_sha256,
            "embedding": embedding, "embedding_model": embedding_model,
            "regions": self.regions, "business_age_limit_years": self.business_age_limit_years,
            "application_start": self.application_start.isoformat() if self.application_start else None,
            "application_end": self.application_end.isoformat() if self.application_end else None,
            "status": self.status,
            "source_as_of": self.source_as_of.isoformat() if self.source_as_of else None,
            "raw": self.raw, "display": self.display, "collected_at": collected_at,
        }


def display_status(application_end: date | None, today: date) -> str:
    """프론트 Program.status용 값.

    테이블의 status는 접수창이 열려 있는지를 뜻하고 프론트의 status는 자격 사전판정
    결과를 뜻한다. 접수 중이라는 사실은 자격이 있다는 뜻이 아니므로 ACTIVE를 잇지 않고
    UNKNOWN으로 둔다. 마감일이 지난 것만 CLOSED다 — 그건 날짜의 산술이다.
    """
    if application_end is not None and application_end < today:
        return "CLOSED"
    return "UNKNOWN"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v`
Expected: 11 passed

- [ ] **Step 5: 커밋**

```bash
git add pipeline/policy/__init__.py pipeline/policy/normalize.py pipeline/policy/test_normalize.py
git commit -m "feat(pipeline): add pure helpers for policy document normalisation"
```

---

### Task 3: 픽스처 저장과 기업마당 정규화

**Files:**
- Create: `pipeline/policy/fixtures/bizinfo.sample.xml`
- Modify: `pipeline/policy/normalize.py`
- Modify: `pipeline/policy/test_normalize.py`

- [ ] **Step 1: 픽스처 저장**

Task 1의 스모크와 같은 방식으로 임시 스크립트를 돌려 기업마당 응답을 받아 `pipeline/policy/fixtures/bizinfo.sample.xml`로 저장한다. **저장 전에 URL·키가 본문에 들어 있지 않은지 확인한다** — 기업마당 응답에는 키가 실려 오지 않지만, 저장 후 `grep -c "$BIZINFO_API_KEY" pipeline/policy/fixtures/bizinfo.sample.xml`이 0인지 확인한다.

`<item>` 3개만 남기고 나머지는 지운다. 픽스처는 회귀 고정용이지 데이터셋이 아니다.

- [ ] **Step 2: 실패하는 테스트 작성**

`pipeline/policy/test_normalize.py`에 추가:

```python
from pathlib import Path
from xml.etree import ElementTree

from normalize import normalize_bizinfo

FIXTURES = Path(__file__).parent / "fixtures"


def bizinfo_records() -> list[dict[str, str]]:
    root = ElementTree.fromstring((FIXTURES / "bizinfo.sample.xml").read_bytes())
    return [{child.tag: (child.text or "").strip() for child in item}
            for item in root.findall(".//body/items/item")]


def test_normalize_bizinfo_builds_an_embeddable_document():
    record = bizinfo_records()[0]
    doc = normalize_bizinfo(record, today=date(2026, 7, 27))
    assert doc is not None
    assert doc.kind == "PROGRAM"
    assert doc.provider == "기업마당"
    assert doc.id.startswith("bizinfo:PBLN_")
    assert doc.official_url.startswith("https://")
    # 본문에 HTML 태그가 남으면 임베딩 품질이 떨어지고 인용문도 깨진다.
    assert "<" not in doc.body_text
    assert len(doc.body_text) > 100


def test_normalize_bizinfo_reads_the_application_window():
    record = bizinfo_records()[0]
    doc = normalize_bizinfo(record, today=date(2026, 7, 27))
    assert doc.application_start == date(2026, 7, 22)
    assert doc.application_end == date(2026, 8, 18)
    assert doc.status == "ACTIVE"


def test_normalize_bizinfo_takes_region_only_from_the_jurisdiction_field():
    # 소관기관이 광역지자체명일 때만 지역이 확정된다. 해시태그의 '대구'는 근거가 아니다.
    doc = normalize_bizinfo({"pblancNm": "제목", "pblancId": "PBLN_1",
                             "pblancUrl": "https://www.bizinfo.go.kr/x",
                             "jrsdInsttNm": "대구광역시", "bsnsSumryCn": "<p>내용</p>",
                             "hashtags": "서울,창업"}, today=date(2026, 7, 27))
    assert doc.regions == ["대구"]

    doc = normalize_bizinfo({"pblancNm": "제목", "pblancId": "PBLN_2",
                             "pblancUrl": "https://www.bizinfo.go.kr/x",
                             "jrsdInsttNm": "중소벤처기업부", "bsnsSumryCn": "<p>내용</p>",
                             "hashtags": "서울,창업"}, today=date(2026, 7, 27))
    assert doc.regions is None


def test_normalize_bizinfo_rejects_records_without_a_title_or_url():
    assert normalize_bizinfo({"pblancId": "PBLN_3"}, today=date(2026, 7, 27)) is None
    assert normalize_bizinfo({"pblancNm": "제목", "pblancUrl": ""}, today=date(2026, 7, 27)) is None


def test_normalize_bizinfo_display_matches_the_existing_frontend_contract():
    doc = normalize_bizinfo(bizinfo_records()[0], today=date(2026, 7, 27))
    display = doc.display
    # lib/types.ts의 Program과 필드 대 필드로 맞는다. 유니온 밖 값이 새면 UI가 깨진다.
    assert set(display) == {"id", "category", "title", "organization", "status",
                            "application_period", "matched_conditions",
                            "unknown_conditions", "official_url", "source_as_of"}
    assert display["status"] == "UNKNOWN"
    assert display["category"] == "GOVERNMENT"
    assert display["application_period"] == "2026-07-22 ~ 2026-08-18"
    assert display["matched_conditions"] == []
    assert display["unknown_conditions"]
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v -k bizinfo`
Expected: FAIL — `ImportError: cannot import name 'normalize_bizinfo'`

- [ ] **Step 4: 구현 추가**

`pipeline/policy/normalize.py` 끝에 추가:

```python
def _https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url.removeprefix("http://")
    return url


PROGRAM_UNKNOWNS = ["공식 원문의 지역·업종·업력·제외 조건을 직접 확인해야 합니다."]


def _program_display(*, doc_id: str, category: str, title: str, organization: str, status: str,
                     application_period: str | None, official_url: str,
                     source_as_of: date | None) -> dict[str, Any]:
    """lib/types.ts의 Program과 필드 대 필드로 맞춘 표시용 페이로드.

    matched_conditions는 목록 조회에서 비어 있다. 케이스 조건 없이 비교할 것이 없기
    때문이고, 조건 비교는 검색 경로(RetrievalService)가 한다.
    """
    return {
        "id": doc_id, "category": category, "title": title, "organization": organization,
        "status": status, "application_period": application_period,
        "matched_conditions": [], "unknown_conditions": list(PROGRAM_UNKNOWNS),
        "official_url": official_url,
        "source_as_of": source_as_of.isoformat() if source_as_of else None,
    }


def normalize_bizinfo(record: dict[str, Any], *, today: date) -> KnowledgeDocument | None:
    """기업마당 XML item 하나를 문서로 바꾼다. 제목이나 URL이 없으면 버린다."""
    title = (record.get("pblancNm") or "").strip()
    url = _https((record.get("pblancUrl") or "").strip())
    external_id = (record.get("pblancId") or "").strip()
    if not title or not url.startswith("https://"):
        return None

    summary = strip_html(record.get("bsnsSumryCn"))
    organization = (record.get("jrsdInsttNm") or "").strip() or "기업마당"
    executor = (record.get("excInsttNm") or "").strip()
    target = (record.get("trgetNm") or "").strip()
    realm = (record.get("pldirSportRealmLclasCodeNm") or "").strip()
    apply_method = (record.get("reqstMthPapersCn") or "").strip()
    hashtags = (record.get("hashtags") or "").strip()

    # 임베딩에 들어가는 텍스트. 제목과 분류를 앞에 두어 짧은 질의와도 맞물리게 한다.
    body_text = " ".join(part for part in (
        title, f"소관 {organization}" if organization else "",
        f"수행 {executor}" if executor else "",
        f"지원분야 {realm}" if realm else "",
        f"지원대상 {target}" if target else "",
        f"신청방법 {apply_method}" if apply_method else "",
        summary, hashtags,
    ) if part).strip()

    start, end = parse_range_dates(record.get("reqstBeginEndDe"))
    doc_id = f"bizinfo:{external_id or hashlib.sha256(url.encode()).hexdigest()[:20]}"
    source_as_of = parse_iso_date(record.get("creatPnttm"))
    period = (record.get("reqstBeginEndDe") or "").strip() or None
    return KnowledgeDocument(
        id=doc_id, kind="PROGRAM", provider="기업마당", category="GOVERNMENT",
        title=title, organization=organization, official_url=url,
        body_text=body_text, status=resolve_status(end, today),
        # 지역 필드가 없는 원천이다. 소관기관이 광역지자체명일 때만 확정한다.
        regions=canonical_regions(organization),
        application_start=start, application_end=end,
        source_as_of=source_as_of,
        raw=record,
        display=_program_display(doc_id=doc_id, category="GOVERNMENT", title=title,
                                 organization=organization,
                                 status=display_status(end, today),
                                 application_period=period, official_url=url,
                                 source_as_of=source_as_of),
    )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v`
Expected: 16 passed

- [ ] **Step 6: 커밋**

```bash
git add pipeline/policy/fixtures/bizinfo.sample.xml pipeline/policy/normalize.py pipeline/policy/test_normalize.py
git commit -m "feat(pipeline): normalise 기업마당 announcements into embeddable documents"
```

---

### Task 4: K-Startup 정규화

**Files:**
- Create: `pipeline/policy/fixtures/kstartup.sample.json`
- Modify: `pipeline/policy/normalize.py`
- Modify: `pipeline/policy/test_normalize.py`

- [ ] **Step 1: 픽스처 저장**

K-Startup 응답에서 `data` 배열의 3건만 남겨 `pipeline/policy/fixtures/kstartup.sample.json`으로 저장한다. 형태는 `{"data": [ ... ]}`. 저장 후 `grep -c "$KSTARTUP_API_KEY" pipeline/policy/fixtures/kstartup.sample.json`이 0인지 확인한다.

- [ ] **Step 2: 실패하는 테스트 작성**

`pipeline/policy/test_normalize.py`에 추가:

```python
import json

from normalize import normalize_kstartup, parse_business_age_limit


def kstartup_records() -> list[dict]:
    return json.loads((FIXTURES / "kstartup.sample.json").read_text())["data"]


def test_parse_business_age_limit_takes_the_widest_bound():
    assert parse_business_age_limit("7년미만,10년미만") == 10
    assert parse_business_age_limit("3년미만") == 3
    assert parse_business_age_limit("") is None
    assert parse_business_age_limit("예비창업자") is None


def test_normalize_kstartup_builds_an_embeddable_document():
    doc = normalize_kstartup(kstartup_records()[0], today=date(2026, 7, 27))
    assert doc is not None
    assert doc.provider == "K-Startup"
    assert doc.id.startswith("kstartup:")
    assert doc.official_url.startswith("https://")
    assert len(doc.body_text) > 50


def test_normalize_kstartup_keeps_the_declared_region():
    doc = normalize_kstartup({"pbanc_sn": "1", "biz_pbanc_nm": "제목",
                              "detl_pg_url": "https://www.k-startup.go.kr/x",
                              "supt_regin": "서울", "pbanc_rcpt_end_dt": "20260812",
                              "biz_enyy": "7년미만"}, today=date(2026, 7, 27))
    assert doc.regions == ["서울"]
    assert doc.business_age_limit_years == 7
    assert doc.application_end == date(2026, 8, 12)
    assert doc.status == "ACTIVE"


def test_normalize_kstartup_drops_regions_it_cannot_resolve():
    doc = normalize_kstartup({"pbanc_sn": "2", "biz_pbanc_nm": "제목",
                              "detl_pg_url": "https://www.k-startup.go.kr/x",
                              "supt_regin": "전남광주"}, today=date(2026, 7, 27))
    assert doc.regions is None


def test_normalize_kstartup_rejects_records_without_a_usable_url():
    assert normalize_kstartup({"pbanc_sn": "3", "biz_pbanc_nm": "제목"},
                              today=date(2026, 7, 27)) is None


def test_normalize_kstartup_display_renders_the_period_in_the_same_shape():
    # 기업마당은 원천이 '2026-07-22 ~ 2026-08-18' 문자열을 주지만 K-Startup은 두 필드로
    # 온다. 화면에서 같은 모양이어야 하므로 여기서 합쳐 준다.
    doc = normalize_kstartup({"pbanc_sn": "4", "biz_pbanc_nm": "제목",
                              "detl_pg_url": "https://www.k-startup.go.kr/x",
                              "pbanc_rcpt_bgng_dt": "20260724",
                              "pbanc_rcpt_end_dt": "20260812"}, today=date(2026, 7, 27))
    assert doc.display["application_period"] == "2026-07-24 ~ 2026-08-12"
    assert doc.display["status"] == "UNKNOWN"
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v -k kstartup`
Expected: FAIL — `ImportError: cannot import name 'normalize_kstartup'`

- [ ] **Step 4: 구현 추가**

`pipeline/policy/normalize.py` 끝에 추가:

```python
_AGE_LIMIT = re.compile(r"(\d+)\s*년")


def parse_business_age_limit(value: str | None) -> int | None:
    """'7년미만,10년미만'에서 가장 넓은 상한을 뽑는다. 숫자가 없으면 None."""
    years = [int(match) for match in _AGE_LIMIT.findall(value or "")]
    return max(years) if years else None


def normalize_kstartup(record: dict[str, Any], *, today: date) -> KnowledgeDocument | None:
    title = str(record.get("biz_pbanc_nm") or "").strip()
    url = _https(str(record.get("detl_pg_url") or record.get("biz_aply_url") or "").strip())
    external_id = str(record.get("pbanc_sn") or "").strip()
    if not title or not url.startswith("https://"):
        return None

    summary = strip_html(str(record.get("pbanc_ctnt") or ""))
    target = strip_html(str(record.get("aply_trgt_ctnt") or ""))
    excluded = strip_html(str(record.get("aply_excl_trgt_ctnt") or ""))
    classification = str(record.get("supt_biz_clsfc") or "").strip()
    region_text = str(record.get("supt_regin") or "").strip()
    organization = str(record.get("pbanc_ntrp_nm") or "").strip() or "K-Startup"

    body_text = " ".join(part for part in (
        title,
        f"소관 {organization}" if organization else "",
        f"지원분야 {classification}" if classification else "",
        f"지원지역 {region_text}" if region_text else "",
        f"신청대상 {target}" if target else "",
        f"신청제외 {excluded}" if excluded else "",
        summary,
    ) if part).strip()

    end = parse_compact_date(str(record.get("pbanc_rcpt_end_dt") or ""))
    start = parse_compact_date(str(record.get("pbanc_rcpt_bgng_dt") or ""))
    doc_id = f"kstartup:{external_id or hashlib.sha256(url.encode()).hexdigest()[:20]}"
    period = f"{start.isoformat()} ~ {end.isoformat()}" if start and end else None
    return KnowledgeDocument(
        id=doc_id, kind="PROGRAM", provider="K-Startup", category="GOVERNMENT",
        title=title, organization=organization, official_url=url,
        body_text=body_text, status=resolve_status(end, today),
        regions=canonical_regions(region_text),
        business_age_limit_years=parse_business_age_limit(str(record.get("biz_enyy") or "")),
        application_start=start, application_end=end,
        source_as_of=None,
        raw=record,
        display=_program_display(doc_id=doc_id, category="GOVERNMENT", title=title,
                                 organization=organization,
                                 status=display_status(end, today),
                                 application_period=period, official_url=url,
                                 source_as_of=None),
    )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v`
Expected: 22 passed

- [ ] **Step 6: 커밋**

```bash
git add pipeline/policy/fixtures/kstartup.sample.json pipeline/policy/normalize.py pipeline/policy/test_normalize.py
git commit -m "feat(pipeline): normalise K-Startup announcements into embeddable documents"
```

---

### Task 5: KB 상품 문장화

finlife는 본문을 주지 않는다. 구조화 필드를 템플릿으로 문장화한다. 만들어 내는 것은 문장 구조뿐이고 값은 전부 공시 원문에서 온다.

**Files:**
- Modify: `pipeline/policy/normalize.py`
- Modify: `pipeline/policy/test_normalize.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from normalize import normalize_kb_product

KB_BASE = {"fin_prdt_cd": "CR0001A", "fin_prdt_nm": "KB Star 신용대출",
           "kor_co_nm": "KB국민은행", "join_way": "영업점,인터넷,스마트폰",
           "crdt_prdt_type_nm": "일반신용대출", "dcls_month": "202607", "loan_limit": "최대 1억원"}
KB_OPTION = {"lend_rate_min": "4.5", "lend_rate_max": "6.2", "lend_rate_avg": "5.1",
             "lend_rate_type_nm": "변동금리"}


def test_normalize_kb_product_states_only_disclosed_values():
    doc = normalize_kb_product(KB_BASE, KB_OPTION, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN",
                               source_url="https://finlife.fss.or.kr/finlife/ldng/indvCrdt/list.do")
    assert doc.kind == "KB_PRODUCT"
    assert doc.id == "kb-credit_loan-CR0001A"
    assert doc.status == "UNKNOWN"          # 공시 상품에 신청기간이 없다
    assert doc.regions is None
    assert "KB Star 신용대출" in doc.body_text
    assert "4.5" in doc.body_text and "6.2" in doc.body_text
    assert "개인신용대출" in doc.body_text


def test_normalize_kb_product_omits_rates_the_disclosure_does_not_carry():
    doc = normalize_kb_product(KB_BASE, {}, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN",
                               source_url="https://finlife.fss.or.kr/x")
    # 금리가 공시되지 않았으면 문장에 금리 문구 자체가 없어야 한다. 0%로 채우지 않는다.
    assert "금리" not in doc.body_text
    assert doc.body_text.startswith("KB국민은행 개인신용대출")


def test_normalize_kb_product_rejects_records_without_a_code_or_name():
    assert normalize_kb_product({"fin_prdt_nm": "이름만"}, {}, category="CREDIT_LOAN",
                                label="개인신용대출", kind_of_rate="LOAN",
                                source_url="https://finlife.fss.or.kr/x") is None


def test_normalize_kb_product_display_matches_the_existing_frontend_contract():
    doc = normalize_kb_product(KB_BASE, KB_OPTION, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN", source_url="https://finlife.fss.or.kr/x")
    display = doc.display
    # lib/types.ts의 KbProduct와 필드 대 필드로 맞는다.
    assert set(display) == {"id", "name", "category", "category_label", "rate_kind",
                            "organization", "product_type", "rate_min", "rate_max", "rate_avg",
                            "rate_type", "loan_limit", "join_way", "repay_type",
                            "source_as_of", "official_url", "unknown_conditions"}
    assert display["rate_min"] == 4.5 and display["rate_max"] == 6.2
    assert display["category_label"] == "개인신용대출"
    assert display["rate_kind"] == "대출금리"
    assert display["source_as_of"] == "2026-07-01"
    assert len(display["unknown_conditions"]) == 2


def test_normalize_kb_product_display_leaves_undisclosed_rates_null():
    doc = normalize_kb_product(KB_BASE, {}, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN", source_url="https://finlife.fss.or.kr/x")
    # 공시되지 않은 금리를 0으로 채우지 않는다. null이 '모른다'는 뜻이다.
    assert doc.display["rate_min"] is None
    assert doc.display["rate_max"] is None
    assert doc.display["rate_avg"] is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v -k kb_product`
Expected: FAIL — `ImportError: cannot import name 'normalize_kb_product'`

- [ ] **Step 3: 구현 추가**

```python
KB_UNKNOWNS = [
    "공시 금리는 기준월 범위이며 실제 적용 금리·한도가 아닙니다.",
    "자격과 심사 결과는 KB국민은행에서 직접 확인해야 합니다.",
]


def _rate_value(option: dict[str, Any], *fields: str) -> float | None:
    for name in fields:
        value = option.get(name)
        if value in (None, "", "-"):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _rate(option: dict[str, Any], *fields: str) -> str | None:
    value = _rate_value(option, *fields)
    return None if value is None else f"{value:g}"


def normalize_kb_product(record: dict[str, Any], option: dict[str, Any], *, category: str,
                         label: str, kind_of_rate: str, source_url: str) -> KnowledgeDocument | None:
    """finlife 공시 레코드를 문장화한다. 만들어 내는 것은 문장 구조뿐이고 값은 전부 공시에서 온다."""
    name = str(record.get("fin_prdt_nm") or "").strip()
    code = str(record.get("fin_prdt_cd") or "").strip()
    if not name or not code:
        return None

    organization = str(record.get("kor_co_nm") or "KB국민은행").strip()
    if kind_of_rate == "LOAN":
        low, high = _rate(option, "lend_rate_min"), _rate(option, "lend_rate_max")
        average = _rate(option, "lend_rate_avg", "crdt_grad_avg")
        rate_label, limit = "대출금리", str(record.get("loan_limit") or "").strip()
    else:
        low, high = _rate(option, "intr_rate"), _rate(option, "intr_rate2")
        average, rate_label = None, "저축금리"
        limit = str(record.get("max_limit") or "").strip()

    parts = [f"{organization} {label} 상품 '{name}'."]
    if low and high:
        parts.append(f"{rate_label} 연 {low}~{high}%.")
    elif low:
        parts.append(f"{rate_label} 연 {low}%.")
    if average:
        parts.append(f"평균 {average}%.")
    rate_type = str(record.get("lend_rate_type") or record.get("intr_rate_type_nm") or "").strip()
    if rate_type:
        parts.append(f"금리방식 {rate_type}.")
    if limit and limit not in ("기타", "0"):
        parts.append(f"한도 {limit}.")
    join_way = str(record.get("join_way") or "").strip()
    if join_way:
        parts.append(f"가입방법 {join_way}.")
    repay = str(record.get("rpay_type") or "").strip()
    if repay:
        parts.append(f"상환방식 {repay}.")
    product_type = str(record.get("fin_prdt_type_nm") or record.get("crdt_prdt_type_nm") or "").strip()
    if product_type:
        parts.append(f"상품유형 {product_type}.")

    dcls_month = str(record.get("dcls_month") or "").strip()
    source_as_of = None
    if len(dcls_month) == 6 and dcls_month.isdigit():
        source_as_of = date(int(dcls_month[:4]), int(dcls_month[4:]), 1)

    doc_id = f"kb-{category.lower()}-{code}"
    display = {
        "id": doc_id, "name": name, "category": category, "category_label": label,
        "rate_kind": rate_label, "organization": organization,
        "product_type": str(record.get("fin_prdt_type_nm") or record.get("crdt_prdt_type_nm") or "").strip() or None,
        "rate_min": _rate_value(option, "lend_rate_min") if kind_of_rate == "LOAN" else _rate_value(option, "intr_rate"),
        "rate_max": _rate_value(option, "lend_rate_max") if kind_of_rate == "LOAN" else _rate_value(option, "intr_rate2"),
        "rate_avg": _rate_value(option, "lend_rate_avg", "crdt_grad_avg") if kind_of_rate == "LOAN" else None,
        "rate_type": rate_type or None,
        "loan_limit": None if limit in ("", "기타", "0") else limit,
        "join_way": join_way or None,
        "repay_type": repay or None,
        "source_as_of": source_as_of.isoformat() if source_as_of else None,
        "official_url": source_url, "unknown_conditions": list(KB_UNKNOWNS),
    }
    return KnowledgeDocument(
        id=doc_id, kind="KB_PRODUCT", provider="금융상품 한눈에",
        category=category, title=name, organization=organization, official_url=source_url,
        body_text=" ".join(parts), status="UNKNOWN", source_as_of=source_as_of, raw=record,
        display=display,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest test_normalize.py -v`
Expected: 27 passed

- [ ] **Step 5: 커밋**

```bash
git add pipeline/policy/normalize.py pipeline/policy/test_normalize.py
git commit -m "feat(pipeline): turn KB product disclosures into sentences worth embedding"
```

---

### Task 6: 수집기

**Files:**
- Create: `pipeline/policy/fetch.py`

- [ ] **Step 1: 구현 작성**

이 모듈은 I/O만 한다. 순수 로직이 없으므로 단위 테스트를 붙이지 않고, Task 9의 `verify_index.py`가 실측으로 확인한다.

`pipeline/policy/fetch.py`:

```python
"""공공 API 3종에서 원시 레코드를 긁어 온다. 해석은 normalize.py가 한다.

수집 실패는 예외로 올리지 않고 (records, ok) 튜플의 ok=False로 알린다. prune이
'이 provider를 정말 다 봤는가'를 알아야 하기 때문이다 — 설계 §4.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
KB_FIN_CO_NO = "0010927"
KB_CATEGORIES = (
    ("BUSINESS_LOAN", "개인사업자대출", "busiLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/indvlBusi/list.do?menuNo=700072"),
    ("CREDIT_LOAN", "개인신용대출", "creditLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/indvCrdt/list.do?menuNo=700009"),
    ("MORTGAGE_LOAN", "주택담보대출", "mortgageLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/houseMortgage/list.do?menuNo=700007"),
    ("RENT_LOAN", "전세자금대출", "rentHouseLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/rentHouse/list.do?menuNo=700008"),
    ("DEPOSIT", "정기예금", "depositProductsSearch", "SAVING",
     "https://finlife.fss.or.kr/finlife/svings/fxdDpst/list.do?menuNo=700002"),
    ("SAVING", "적금", "savingProductsSearch", "SAVING",
     "https://finlife.fss.or.kr/finlife/svings/instsav/list.do?menuNo=700003"),
)


def _resolved(template: str, key: str) -> str:
    return template.replace("{api_key}", quote(key, safe="")) if "{api_key}" in template else template


def _paged(url: str, page: int) -> str:
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}page={page}"


def fetch_bizinfo(client: httpx.Client, template: str, key: str) -> tuple[list[dict[str, str]], bool]:
    if not template or not key or not template.startswith("https://"):
        return ([], False)
    try:
        response = client.get(_resolved(template, key), headers={"X-Api-Key": key}, timeout=TIMEOUT)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except (httpx.HTTPError, ElementTree.ParseError):
        return ([], False)
    records = [{child.tag: (child.text or "").strip() for child in item}
               for item in root.findall(".//body/items/item")]
    return (records, True)


def fetch_kstartup(client: httpx.Client, template: str, key: str, *,
                   max_pages: int = 20) -> tuple[list[dict[str, Any]], bool]:
    """진행 중인 공고만 모은다. 종료된 공고를 인덱싱할 이유가 없다."""
    if not template or not key or not template.startswith("https://"):
        return ([], False)
    url = _resolved(template, key)
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        try:
            response = client.get(_paged(url, page), headers={"Accept": "application/json"}, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return (records, False)
        batch = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
        if not batch:
            break
        records.extend(item for item in batch if str(item.get("rcrt_prgs_yn") or "").upper() == "Y")
        if len(batch) < int(payload.get("perPage") or len(batch)):
            break
    return (records, True)


def fetch_kb_products(client: httpx.Client, base_url: str, key: str, *,
                      max_pages: int = 5) -> tuple[list[tuple[dict, dict, str, str, str, str]], bool]:
    """(base, option, category, label, kind_of_rate, source_url) 튜플을 낸다."""
    base = (base_url or "").rstrip("/")
    if not base or not key or not base.startswith("https://"):
        return ([], False)
    out: list[tuple[dict, dict, str, str, str, str]] = []
    ok = True
    for category, label, endpoint, kind_of_rate, source_url in KB_CATEGORIES:
        url = f"{base}/{endpoint}.json?auth={quote(key, safe='')}&topFinGrpNo=020000"
        bases: list[dict] = []
        options: list[dict] = []
        for page in range(1, max_pages + 1):
            try:
                response = client.get(f"{url}&pageNo={page}", headers={"Accept": "application/json"}, timeout=TIMEOUT)
                response.raise_for_status()
                result = (response.json() or {}).get("result") or {}
            except (httpx.HTTPError, ValueError):
                ok = False
                break
            if str(result.get("err_cd") or "000") != "000":
                break
            bases.extend(item for item in (result.get("baseList") or []) if isinstance(item, dict))
            options.extend(item for item in (result.get("optionList") or []) if isinstance(item, dict))
            if page >= int(result.get("max_page_no") or page):
                break
        rates: dict[str, dict] = {}
        for option in options:
            code = str(option.get("fin_prdt_cd") or "")
            if code and code not in rates:
                rates[code] = option
        for record in bases:
            if str(record.get("fin_co_no") or "") != KB_FIN_CO_NO:
                continue
            out.append((record, rates.get(str(record.get("fin_prdt_cd") or ""), {}),
                        category, label, kind_of_rate, source_url))
    return (out, ok)
```

- [ ] **Step 2: import가 깨지지 않는지 확인**

Run: `backend/.venv/bin/python -c "import sys; sys.path.insert(0, 'pipeline/policy'); import fetch; print(len(fetch.KB_CATEGORIES))"`
Expected: `6`

- [ ] **Step 3: 커밋**

```bash
git add pipeline/policy/fetch.py
git commit -m "feat(pipeline): collect raw records from the three configured providers"
```

---

### Task 7: 임베딩기

**Files:**
- Create: `pipeline/policy/embed.py`

- [ ] **Step 1: 구현 작성**

`pipeline/policy/embed.py`:

```python
"""텍스트 배치를 벡터로 바꾼다.

배치 하나가 실패하면 그 배치만 None으로 돌려준다. 호출자가 embedding=null로 저장하고
다음 회차가 재시도한다 — 설계 §8.
"""
from __future__ import annotations

from openai import OpenAI

BATCH_SIZE = 100


def embed_texts(client: OpenAI, model: str, texts: list[str]) -> list[list[float] | None]:
    vectors: list[list[float] | None] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        try:
            response = client.embeddings.create(model=model, input=batch)
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 배치 단위로 흡수한다
            print(f"  embedding batch {start // BATCH_SIZE} failed: {type(exc).__name__}")
            vectors.extend([None] * len(batch))
            continue
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend(item.embedding for item in ordered)
    return vectors
```

- [ ] **Step 2: import 확인**

Run: `backend/.venv/bin/python -c "import sys; sys.path.insert(0, 'pipeline/policy'); import embed; print(embed.BATCH_SIZE)"`
Expected: `100`

- [ ] **Step 3: 커밋**

```bash
git add pipeline/policy/embed.py
git commit -m "feat(pipeline): batch-embed document text, absorbing per-batch failures"
```

---

### Task 8: 인제스트 엔트리포인트

**Files:**
- Create: `pipeline/policy/index.py`
- Modify: `package.json`

- [ ] **Step 1: 구현 작성**

`pipeline/policy/index.py`:

```python
"""수집 → 정규화 → 차분 → 임베딩 → upsert → prune.

prune은 provider 단위로, 그 provider의 수집이 완전히 성공했을 때만 한다. 한 원천이
5xx를 뱉은 회차에 다른 원천의 결과로 전체를 정리하면 외부 장애가 우리 인덱스를
비우는 사고가 된다 — 설계 §4.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from openai import OpenAI
from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent))

from embed import embed_texts                                            # noqa: E402
from fetch import fetch_bizinfo, fetch_kb_products, fetch_kstartup       # noqa: E402
from normalize import (KnowledgeDocument, normalize_bizinfo,             # noqa: E402
                       normalize_kb_product, normalize_kstartup)

ROOT = Path(__file__).resolve().parents[2]
TABLE = "knowledge_documents"
UPSERT_CHUNK = 200


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    return cfg


def collect(cfg: dict[str, str], today: date) -> tuple[list[KnowledgeDocument], dict[str, bool]]:
    documents: list[KnowledgeDocument] = []
    healthy: dict[str, bool] = {}
    with httpx.Client(follow_redirects=True) as client:
        records, ok = fetch_bizinfo(client, cfg.get("BIZINFO_API_URL", ""), cfg.get("BIZINFO_API_KEY", ""))
        healthy["기업마당"] = ok
        documents.extend(doc for doc in (normalize_bizinfo(r, today=today) for r in records) if doc)
        print(f"기업마당: {len(records)} records, ok={ok}")

        records, ok = fetch_kstartup(client, cfg.get("KSTARTUP_API_URL", ""), cfg.get("KSTARTUP_API_KEY", ""))
        healthy["K-Startup"] = ok
        documents.extend(doc for doc in (normalize_kstartup(r, today=today) for r in records) if doc)
        print(f"K-Startup: {len(records)} records, ok={ok}")

        products, ok = fetch_kb_products(client, cfg.get("FINLIFE_API_BASE_URL", ""), cfg.get("FINLIFE_API_KEY", ""))
        healthy["금융상품 한눈에"] = ok
        documents.extend(doc for doc in (
            normalize_kb_product(base, option, category=category, label=label,
                                 kind_of_rate=kind_of_rate, source_url=source_url)
            for base, option, category, label, kind_of_rate, source_url in products) if doc)
        print(f"금융상품 한눈에: {len(products)} records, ok={ok}")

    unique: dict[str, KnowledgeDocument] = {}
    for doc in documents:
        unique.setdefault(doc.id, doc)
    return (list(unique.values()), healthy)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reembed", action="store_true",
                        help="본문이 그대로여도 전량 재임베딩한다. 임베딩 모델을 바꿀 때만 쓴다.")
    args = parser.parse_args()

    cfg = load_env()
    model = cfg.get("EMBEDDING_MODEL", "")
    if not (cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY가 없습니다.", file=sys.stderr)
        return 1
    if not (cfg.get("OPENAI_API_KEY") and model):
        print("OPENAI_API_KEY / EMBEDDING_MODEL이 없습니다.", file=sys.stderr)
        return 1

    run_started_at = datetime.now(UTC)
    today = run_started_at.date()
    supabase = create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])
    openai = OpenAI(api_key=cfg["OPENAI_API_KEY"])

    documents, healthy = collect(cfg, today)
    if not any(healthy.values()):
        print("모든 원천 수집에 실패했습니다. 인덱스를 건드리지 않고 종료합니다.", file=sys.stderr)
        return 1

    existing = {row["id"]: row for row in
                (supabase.table(TABLE).select("id,content_sha256,embedding_model")
                 .execute().data or [])}

    # 임베딩 모델이 섞이면 유사도가 의미를 잃는다. 자동으로 섞지 않고 멈춘다 — 설계 §8.
    stale_models = {row.get("embedding_model") for row in existing.values()
                    if row.get("embedding_model") and row.get("embedding_model") != model}
    if stale_models and not args.reembed:
        print(f"인덱스에 다른 임베딩 모델이 있습니다: {sorted(stale_models)}. "
              f"--reembed로 전량 재생성하세요.", file=sys.stderr)
        return 1

    needs_embedding = [doc for doc in documents
                       if args.reembed
                       or doc.id not in existing
                       or existing[doc.id].get("content_sha256") != doc.content_sha256]
    print(f"문서 {len(documents)}건, 임베딩 대상 {len(needs_embedding)}건")

    vectors: dict[str, list[float] | None] = {}
    if needs_embedding:
        computed = embed_texts(openai, model, [doc.body_text for doc in needs_embedding])
        vectors = {doc.id: vector for doc, vector in zip(needs_embedding, computed, strict=True)}

    collected_at = run_started_at.isoformat()
    rows = []
    for doc in documents:
        if doc.id in vectors:
            rows.append(doc.to_row(collected_at=collected_at, embedding=vectors[doc.id],
                                   embedding_model=model if vectors[doc.id] else None))
        else:
            # 본문이 그대로인 문서는 벡터를 건드리지 않는다. 메타데이터만 갱신한다.
            row = doc.to_row(collected_at=collected_at, embedding=None, embedding_model=None)
            row.pop("embedding")
            row.pop("embedding_model")
            rows.append(row)

    for start in range(0, len(rows), UPSERT_CHUNK):
        supabase.table(TABLE).upsert(rows[start:start + UPSERT_CHUNK]).execute()
    print(f"upsert {len(rows)}건")

    for provider, ok in healthy.items():
        if not ok:
            print(f"{provider}: 수집이 불완전하여 prune을 건너뜁니다.", file=sys.stderr)
            continue
        removed = (supabase.table(TABLE).delete()
                   .eq("provider", provider).lt("collected_at", collected_at).execute().data or [])
        print(f"{provider}: prune {len(removed)}건")

    missing = len([row for row in rows if row.get("embedding") is None and "embedding" in row])
    if missing:
        print(f"임베딩 결측 {missing}건 — 다음 회차가 재시도합니다.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: package.json에 스크립트 추가**

`"pipeline:verify"` 줄 바로 아래에 추가:

```json
    "pipeline:policy-index": "backend/.venv/bin/python pipeline/policy/index.py",
```

- [ ] **Step 3: 실행**

Run: `npm run pipeline:policy-index`
Expected: 각 provider의 레코드 수와 `ok=True`, `임베딩 대상 N건`, `upsert N건`, `prune 0건`이 찍히고 exit 0.

**주의:** 이 단계가 첫 실제 임베딩 호출이다. 문서 수가 예상(수백~수천)을 크게 벗어나면 멈추고 원인을 본다.

- [ ] **Step 4: 두 번 돌려 차분이 작동하는지 확인**

Run: `npm run pipeline:policy-index`
Expected: `임베딩 대상 0건` (본문이 그대로이므로 재임베딩 없음). 이게 차분 로직의 유일한 증거다.

- [ ] **Step 5: 커밋**

```bash
git add pipeline/policy/index.py package.json
git commit -m "feat(pipeline): ingest, embed and prune the knowledge index"
```

---

### Task 9: 인덱스 리포트

**Files:**
- Create: `pipeline/policy/verify_index.py`

- [ ] **Step 1: 구현 작성**

`pipeline/policy/verify_index.py`:

```python
"""인덱스 상태를 사람이 읽는 형태로 출력한다. 자동 판정이 아니다.

pipeline/verify/cross_check.py와 같은 성격이다 — 숫자를 보여 주고 판단은 사람이 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from openai import OpenAI
from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent))
from index import TABLE, load_env  # noqa: E402

PROBES = ("서울 소상공인 창업 자금 지원", "청년 창업 임차료 지원", "개인사업자 대출 금리", "카페 창업 시설 자금")


def main() -> int:
    cfg = load_env()
    supabase = create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])

    rows = supabase.table(TABLE).select("id,kind,provider,status,embedding_model,collected_at").execute().data or []
    print(f"문서 {len(rows)}건")
    for key in ("kind", "provider", "status"):
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row.get(key))] = counts.get(str(row.get(key)), 0) + 1
        print(f"  {key}: {counts}")
    print(f"  마지막 수집: {max((r['collected_at'] for r in rows), default='없음')}")

    missing = supabase.table(TABLE).select("id", count="exact").is_("embedding", "null").execute()
    print(f"  임베딩 결측: {missing.count}건")

    model = cfg.get("EMBEDDING_MODEL", "")
    if not (cfg.get("OPENAI_API_KEY") and model):
        print("\nOPENAI_API_KEY / EMBEDDING_MODEL이 없어 질의 확인은 건너뜁니다.")
        return 0

    openai = OpenAI(api_key=cfg["OPENAI_API_KEY"])
    for probe in PROBES:
        vector = openai.embeddings.create(model=model, input=[probe]).data[0].embedding
        hits = supabase.rpc("search_knowledge", {
            "query_embedding": vector, "match_regions": ["서울", "전국"], "match_count": 5,
        }).execute().data or []
        print(f"\n질의: {probe}")
        for hit in hits:
            print(f"  {hit['similarity']:.3f}  [{hit['provider']}] {hit['title'][:60]}")
        if not hits:
            print("  (결과 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 실행하고 결과를 눈으로 확인**

Run: `backend/.venv/bin/python pipeline/policy/verify_index.py`
Expected: 문서 수·분포·결측 수가 찍히고, 네 질의마다 상위 5건이 나온다. **상위 결과가 질의와 무관해 보이면 멈추고 `body_text` 구성을 다시 본다.**

- [ ] **Step 3: 커밋**

```bash
git add pipeline/policy/verify_index.py
git commit -m "feat(pipeline): report index health and probe query relevance"
```

---

### Task 10: 백엔드 설정

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.env.example`

- [ ] **Step 1: 설정 추가**

`backend/app/config.py`의 `ai_daily_request_limit: int = 20` 아래에 추가:

```python
    embedding_model: str = ""
    embedding_dimension: int = 1536
```

`supabase_configured` 프로퍼티 아래에 추가:

```python
    @property
    def retrieval_configured(self) -> bool:
        """검색은 벡터 저장소와 질의 임베딩이 모두 있어야 성립한다."""
        return bool(self.supabase_configured and self.openai_api_key and self.embedding_model)
```

- [ ] **Step 2: .env.example 갱신**

`AI_DAILY_REQUEST_LIMIT=20` 아래에 추가:

```
# 의미 검색. 비워 두면 검색이 비활성화되고 빈 결과 + 안내 문구를 낸다.
# 마이그레이션의 vector(1536)과 차원이 일치해야 한다.
EMBEDDING_MODEL=
EMBEDDING_DIMENSION=1536
```

- [ ] **Step 3: 실제 .env에 값 설정**

`.env`에 `EMBEDDING_MODEL=text-embedding-3-small`을 더한다(Task 8이 이미 이 값을 읽으므로 Task 8 실행 전에 필요하다 — Task 8 Step 3에서 먼저 넣었다면 확인만 한다).

- [ ] **Step 4: 확인**

Run: `backend/.venv/bin/python -c "import sys; sys.path.insert(0,'backend'); from app.config import get_settings; s=get_settings(); print(s.embedding_model, s.embedding_dimension, s.retrieval_configured)"`
Expected: `text-embedding-3-small 1536 True`

- [ ] **Step 5: 커밋**

```bash
git add backend/app/config.py .env.example
git commit -m "feat(api): add the embedding settings and a retrieval_configured flag"
```

---

### Task 11: 검색 응답 계약

**Files:**
- Modify: `backend/app/models.py`

- [ ] **Step 1: 모델 추가**

`backend/app/models.py` 끝에 추가:

```python
class RetrievedDocument(BaseModel):
    id: str
    kind: str
    title: str
    organization: str
    official_url: str
    provider: str
    category: str
    excerpt: str
    similarity: float
    source_as_of: str | None = None
    collected_at: str | None = None
    application_start: str | None = None
    application_end: str | None = None
    # 코드가 구조화 필드를 비교한 결과만 들어간다. 유사도는 여기 오지 않는다.
    matched_conditions: list[str] = Field(default_factory=list)
    unknown_conditions: list[str] = Field(default_factory=list)
    # 불변조건 3. 모든 데이터 표면은 출처를 달고 나간다. ProvenanceBar가 그대로 렌더한다.
    provenance: Provenance


class RetrievalResponse(BaseModel):
    items: list[RetrievedDocument] = Field(default_factory=list)
    status: str
    message: str | None = None
    evidence_grade: str = "C"
```

`Field`가 이미 import되어 있는지 확인하고, 없으면 `from pydantic import BaseModel, Field`로 고친다.

- [ ] **Step 2: 확인**

Run: `npm run api:check`
Expected: 출력 없음, exit 0

- [ ] **Step 3: 커밋**

```bash
git add backend/app/models.py
git commit -m "feat(api): add the retrieval response contract"
```

---

### Task 12: RetrievalService

**Files:**
- Create: `backend/app/retrieval.py`
- Create: `backend/tests/test_retrieval.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_retrieval.py`:

```python
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
    def __init__(self, rows): self.rows = rows
    def execute(self): return type("R", (), {"data": self.rows})()


class FakeClient:
    def __init__(self, rows): self.rows, self.calls = rows, []
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


@pytest.mark.asyncio
async def test_search_without_configuration_returns_integration_pending():
    result = await service([], configured=False).search("청년 창업")
    assert result.status == "integration_pending"
    assert result.items == []
    assert result.message


@pytest.mark.asyncio
async def test_search_returns_documents_with_an_excerpt_and_similarity():
    result = await service([HIT]).search("청년 창업")
    assert result.status == "success"
    assert result.evidence_grade == "C"
    item = result.items[0]
    assert item.id == "kstartup:1"
    assert item.similarity == pytest.approx(0.83)
    assert len(item.excerpt) <= 300
    # 불변조건 3 — 모든 데이터 표면은 출처를 달고 나간다.
    assert item.provenance.source_name == "K-Startup"
    assert item.provenance.confidence == "LOW"
    assert item.provenance.limitations


@pytest.mark.asyncio
async def test_matched_conditions_carry_only_deterministic_comparisons():
    result = await service([HIT]).search("청년 창업", regions=["서울"], today=date(2026, 7, 27))
    item = result.items[0]
    assert any("서울" in line for line in item.matched_conditions)
    assert any("2026-08-31" in line for line in item.matched_conditions)
    # 유사도는 판정이 아니므로 근거 문장에 새어 들어오면 안 된다.
    assert not any("유사" in line or "0.83" in line for line in item.matched_conditions)
    assert item.unknown_conditions


@pytest.mark.asyncio
async def test_a_document_without_a_region_is_reported_as_unknown_not_matched():
    hit = dict(HIT, regions=None)
    result = await service([hit]).search("청년 창업", regions=["서울"], today=date(2026, 7, 27))
    item = result.items[0]
    assert not any("지원지역" in line for line in item.matched_conditions)
    assert any("지역" in line for line in item.unknown_conditions)


@pytest.mark.asyncio
async def test_a_transport_failure_degrades_to_an_empty_result():
    svc = service([HIT])
    def boom(name, params): raise RuntimeError("PostgREST down")
    svc._client.rpc = boom
    result = await svc.search("청년 창업")
    assert result.status == "unavailable"
    assert result.items == []
    assert result.message
```

`pytest-asyncio`가 필요하다. `backend/requirements.txt`에 `pytest-asyncio==1.3.0`을 더하고 `backend/pytest.ini`의 `[pytest]` 아래에 `asyncio_mode = auto`를 넣는다. 이미 있으면 건너뛴다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_retrieval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.retrieval'`

- [ ] **Step 3: 구현 작성**

`backend/app/retrieval.py`:

```python
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
from .models import RetrievalResponse, RetrievedDocument

EXCERPT_LIMIT = 300
NOT_CONFIGURED = "의미 검색이 아직 연결되지 않았습니다. 공고 원문 링크는 계속 확인할 수 있습니다."
UNAVAILABLE = "근거 검색이 지연되고 있습니다. 저장된 공식 원문은 계속 사용할 수 있습니다."

BASE_UNKNOWNS = ("공고 원문의 지역·업종·업력·제외 조건을 직접 확인해야 합니다.",)


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
            industry_scope="전 업종", spatial_unit="전국" if not row_regions else ", ".join(row_regions),
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
```

`retrieval.py`의 import에 `Provenance`를 더한다: `from .models import Provenance, RetrievalResponse, RetrievedDocument`

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_retrieval.py -v`
Expected: 6 passed

- [ ] **Step 5: 전체 백엔드 테스트**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: 96 passed (기존 90 + 신규 6)

- [ ] **Step 6: 커밋**

```bash
git add backend/app/retrieval.py backend/tests/test_retrieval.py backend/requirements.txt backend/pytest.ini
git commit -m "feat(api): add semantic retrieval over the knowledge index"
```

---

### Task 13: 엔드포인트 전환

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api_knowledge.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_knowledge.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def session_cookie() -> dict[str, str]:
    response = client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
    assert response.status_code == 201
    return {name: value for name, value in response.cookies.items()}


def test_status_reports_index_freshness():
    body = client.get("/api/v1/status").json()
    assert "knowledge_index" in body
    index = body["knowledge_index"]
    assert set(index) >= {"documents", "missing_embeddings", "last_collected_at"}


def test_search_requires_a_session():
    assert client.get("/api/v1/knowledge/search", params={"q": "창업"}).status_code == 401


def test_search_returns_a_documented_status_without_keys():
    cookies = session_cookie()
    body = client.get("/api/v1/knowledge/search", params={"q": "창업"}, cookies=cookies).json()
    assert body["status"] in {"success", "integration_pending", "unavailable"}
    assert body["evidence_grade"] == "C"
    assert isinstance(body["items"], list)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_knowledge.py -v`
Expected: FAIL — `knowledge_index` 없음 / 404

- [ ] **Step 3: main.py 수정 — 싱글턴 배선**

`official_sources = OfficialSourceService(settings)` 옆에 추가:

```python
retrieval = RetrievalService(settings)
knowledge = KnowledgeReader(settings)
```

import에 추가:

```python
from .retrieval import RetrievalService
from .knowledge import KnowledgeReader
```

- [ ] **Step 4: 읽기 전용 리더 작성**

`backend/app/knowledge.py`를 새로 만든다. `RetrievalService`가 벡터 검색만 하도록 두고, 목록 조회는 여기가 맡는다.

```python
"""인덱스에서 목록을 읽는다. 벡터를 쓰지 않는 평범한 조회다.

/programs가 요청마다 공공 API를 때리던 경로를 대체한다 — 설계 §1 결정 6.
"""
from __future__ import annotations

import asyncio
from typing import Any

from supabase import Client, create_client

from .config import Settings

TABLE = "knowledge_documents"
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
        except Exception:  # noqa: BLE001
            return []

    def _select(self, kind: str) -> list[dict[str, Any]]:
        """display를 그대로 반환한다. 컬럼을 내보내면 lib/types.ts의 유니온이 깨진다."""
        response = (self._client.table(TABLE).select("display,application_end")
                    .eq("kind", kind).neq("status", "CLOSED")
                    .order("application_end", desc=False).limit(200).execute())
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
```

- [ ] **Step 5: 엔드포인트 교체**

`main.py:262-280`의 세 엔드포인트를 바꾼다.

```python
@app.get("/api/v1/programs")
async def list_programs(case_id: UUID = Query(), session_id: UUID = Depends(current_session)):
    owned_case(session_id, case_id)
    items = await knowledge.programs()
    return {"items": items, "status": "success" if items else "integration_pending",
            "message": None if items else EMPTY_PROGRAMS}


@app.get("/api/v1/programs/catalog")
async def list_program_catalog(session_id: UUID = Depends(current_session)):
    """Case-independent view of the same official notices — the 정책 tab browses them without a case."""
    items = await knowledge.programs()
    return {"items": items, "status": "success" if items else "integration_pending",
            "message": None if items else EMPTY_PROGRAMS}


@app.get("/api/v1/products/kb")
async def list_kb_products(session_id: UUID = Depends(current_session)):
    items = await knowledge.kb_products()
    return {"items": items, "status": "success" if items else "integration_pending",
            "message": None if items else EMPTY_PRODUCTS}
```

import에 `from .knowledge import EMPTY_PRODUCTS, EMPTY_PROGRAMS, KnowledgeReader`를 넣는다.

`/api/v1/products`(PRIVATE 필터)는 `official_sources.programs()`를 쓰고 있었다. 이제 인덱스에는 `PRIVATE` 카테고리 공고가 없으므로 `knowledge.kb_products()`로 바꾼다:

```python
@app.get("/api/v1/products")
async def list_products(case_id: UUID = Query(), session_id: UUID = Depends(current_session)):
    owned_case(session_id, case_id)
    items = await knowledge.kb_products()
    return {"items": items, "status": "success" if items else "integration_pending"}
```

- [ ] **Step 6: 검색 엔드포인트 추가**

`/api/v1/products` 아래에 추가:

```python
@app.get("/api/v1/knowledge/search", response_model=RetrievalResponse)
async def search_knowledge_documents(q: str = Query(min_length=1, max_length=300),
                                     kind: str | None = Query(default=None),
                                     district: str | None = Query(default=None),
                                     limit: int = Query(default=8, ge=1, le=20),
                                     session_id: UUID = Depends(current_session)):
    """의미 검색. 유사도는 순서에만 관여하고 자격 판정은 구조화 필드 비교로만 한다."""
    if kind and kind not in ("PROGRAM", "KB_PRODUCT"):
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "알 수 없는 문서 종류입니다."})
    if district and district not in SEOUL_DISTRICTS:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "서울 25개 자치구만 지원합니다."})
    # 서울 스코프. 전국 공고는 서울 창업자에게도 유효하므로 함께 본다.
    regions = ["서울", "전국"] if district else None
    return await retrieval.search(q, kinds=[kind] if kind else None, regions=regions, limit=limit)
```

import에 `from .models import RetrievalResponse`를 더한다(기존 models import 줄에 추가).

- [ ] **Step 7: /status에 신선도 추가**

`integration_status()`의 반환 dict에 키를 하나 더한다:

```python
@app.get("/api/v1/status")
async def integration_status():
    return {"mode": settings.app_env, "integrations": {
        "supabase": settings.supabase_configured,
        "kakao_map": bool(settings.next_public_kakao_map_js_key),
        "kakao_local": bool(settings.kakao_rest_api_key),
        "openai": bool(settings.openai_api_key and settings.ai_chat_model and settings.ai_explanation_enabled),
        "retrieval": settings.retrieval_configured,
        "seoul_data": bool(settings.seoul_open_data_key and settings.seoul_commercial_api_url),
        "bizinfo": bool(settings.bizinfo_api_key and settings.bizinfo_api_url),
        "kstartup": bool(settings.kstartup_api_key and settings.kstartup_api_url),
        "finlife": bool(settings.finlife_api_key and settings.finlife_api_url),
    }, "feature_flags": {"financial_application": settings.financial_application_enabled, "consultation_transfer": settings.consultation_transfer_enabled, "mydata": settings.mydata_enabled},
        "knowledge_index": await knowledge.freshness(),
        "axes": analysis_axes()}
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_knowledge.py -v`
Expected: 3 passed

Run: `cd backend && .venv/bin/python -m pytest`
Expected: 99 passed

- [ ] **Step 9: 커밋**

```bash
git add backend/app/main.py backend/app/knowledge.py backend/tests/test_api_knowledge.py
git commit -m "feat(api): serve programs and KB products from the index, add semantic search"
```

---

### Task 14: 라이브 조회 경로 제거

`OfficialSourceService.programs()`와 `kb_products()`는 이제 아무도 부르지 않는다. 같은 페이로드를 두 곳에서 파싱하는 상태를 남기지 않는다 — 설계 §1 결정 6.

**Files:**
- Modify: `backend/app/services.py`

- [ ] **Step 1: 호출자가 없는지 확인**

Run: `grep -rn "official_sources\." backend/app/`
Expected: 출력 없음

- [ ] **Step 2: 죽은 코드 제거**

`backend/app/services.py`에서 `OfficialSourceService` 클래스 전체와 `main.py`의 `official_sources = OfficialSourceService(settings)` 배선, 그리고 `OfficialSourceService` import를 지운다.

`analysis_axes()`가 참조하는 `settings.bizinfo_api_key` 등은 그대로 둔다 — 축 가동 여부는 여전히 원천 설정에 달려 있다.

- [ ] **Step 3: 확인**

Run: `npm run api:check && cd backend && .venv/bin/python -m pytest`
Expected: 99 passed

- [ ] **Step 4: 커밋**

```bash
git add backend/app/services.py backend/app/main.py
git commit -m "refactor(api): drop the live provider fetch now that the index owns normalisation"
```

---

### Task 15: 프론트 타입 미러링

**Files:**
- Modify: `lib/types.ts`

- [ ] **Step 1: 타입 추가**

`lib/types.ts` 끝에 추가한다. `backend/app/models.py`의 `RetrievedDocument`·`RetrievalResponse`와 필드 대 필드로 맞춘다.

```typescript
export type RetrievedDocument = {
  id: string;
  kind: "PROGRAM" | "KB_PRODUCT";
  title: string;
  organization: string;
  official_url: string;
  provider: string;
  category: string;
  excerpt: string;
  similarity: number;
  source_as_of: string | null;
  collected_at: string | null;
  application_start: string | null;
  application_end: string | null;
  matched_conditions: string[];
  unknown_conditions: string[];
  provenance: Provenance;
};

export type RetrievalResponse = {
  items: RetrievedDocument[];
  status: "success" | "integration_pending" | "unavailable";
  message: string | null;
  evidence_grade: "C";
};
```

- [ ] **Step 2: 확인**

Run: `npm run typecheck && npm run lint`
Expected: 둘 다 exit 0

- [ ] **Step 3: 커밋**

```bash
git add lib/types.ts
git commit -m "feat(web): mirror the retrieval contract in the live type surface"
```

---

### Task 16: 타이머와 문서

**Files:**
- Create: `deploy/ter-doctor-policy-index.service`
- Create: `deploy/ter-doctor-policy-index.timer`
- Modify: `pipeline/README.md`

- [ ] **Step 1: service unit 작성**

값은 `deploy/ter-doctor-api.service`에서 그대로 가져왔다(`ec2-user`, `/home/ec2-user/ter-doctor`). 그 파일이 바뀌었다면 먼저 확인한다.

`deploy/ter-doctor-policy-index.service`:

```ini
[Unit]
Description=Jarimaegim policy/KB knowledge index refresh
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/ter-doctor
EnvironmentFile=/home/ec2-user/ter-doctor/.env
ExecStart=/home/ec2-user/ter-doctor/backend/.venv/bin/python pipeline/policy/index.py
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
```

- [ ] **Step 2: timer unit 작성**

`deploy/ter-doctor-policy-index.timer`:

```ini
[Unit]
Description=자리매김 인덱스 갱신을 하루 한 번 돌린다

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
```

`Persistent=true`는 서버가 꺼져 있던 회차를 부팅 후 따라잡게 한다. `RandomizedDelaySec`은 공공 API에 정각마다 몰리지 않게 한다.

- [ ] **Step 3: pipeline/README.md에 스테이지 추가**

기존 스테이지 표 아래에 절을 하나 더한다:

```markdown
## 정책공고·KB상품 인덱스

| 단계 | 명령 | 입력 | 출력 |
| --- | --- | --- | --- |
| 수집·임베딩 | `npm run pipeline:policy-index` | 기업마당·K-Startup·finlife API | Supabase `knowledge_documents` |
| 확인 | `backend/.venv/bin/python pipeline/policy/verify_index.py` | Supabase | 표준출력 리포트 |

크롤링은 쓰지 않는다. 임베딩할 본문(`bsnsSumryCn`·`pbanc_ctnt`)이 API 응답에 이미 실려 온다.

테스트: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest`

운영 서버는 `deploy/ter-doctor-policy-index.timer`가 하루 한 번 돌린다.
```

- [ ] **Step 4: 전체 회귀**

```bash
npm run lint && npm run typecheck && npm run api:check
cd backend && .venv/bin/python -m pytest
cd pipeline/policy && ../../backend/.venv/bin/python -m pytest
```
Expected: 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add deploy/ter-doctor-policy-index.service deploy/ter-doctor-policy-index.timer pipeline/README.md
git commit -m "feat(deploy): refresh the knowledge index on a daily timer"
```

---

## 완료 확인

계획이 끝나면 다음이 참이어야 한다.

- [ ] `npm run pipeline:policy-index`를 두 번 연속 돌리면 두 번째는 `임베딩 대상 0건`이다
- [ ] `verify_index.py`의 네 질의가 각각 그럴듯한 상위 결과를 낸다
- [ ] `GET /api/v1/status`의 `knowledge_index.documents`가 0보다 크다
- [ ] `GET /api/v1/knowledge/search?q=청년 창업`이 `evidence_grade: "C"`와 인용 가능한 `excerpt`를 낸다
- [ ] `matched_conditions`에 유사도 수치나 "유사"라는 단어가 없다
- [ ] `GET /api/v1/programs/catalog`의 각 항목이 `lib/types.ts`의 `Program`과 필드가 같고 `status`가 유니온 안의 값이다
- [ ] `GET /api/v1/products/kb`의 각 항목이 `KbProduct`와 필드가 같고, 미공시 금리가 `0`이 아니라 `null`이다
- [ ] `grep -rn "chat_tools\|chat_stream\|mcp_client" backend/app/retrieval.py backend/app/knowledge.py pipeline/policy/`가 빈 결과다
- [ ] `node scripts/flow-check.mjs`가 통과한다 (무키 안전상태 회귀 방지선)

## 범위 밖

- **`ChatToolset`의 `search_policy_documents` 도구** — 챗 브랜치가 머지된 뒤 별도 작업(설계 §12 덩이 2)
- **세션당 질의 상한** — 강제하는 리미터가 아직 없다. 챗과 함께 별도로 만든다(설계 §8)
- **`programs` 레거시 테이블 정리** — 다른 세션이 참조 중일 수 있으므로 별도 마이그레이션
- **`finance.subsidy`의 조달선 상향분 계산** — 이 계획은 검색 계층까지다
