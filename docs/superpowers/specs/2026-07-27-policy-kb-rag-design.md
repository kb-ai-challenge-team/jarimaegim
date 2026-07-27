# 정책공고·KB상품 임베딩 검색(RAG) 설계 스펙

기준일: 2026-07-27
대상: `backend/app/`, `pipeline/policy/`, `supabase/migrations/`
성격: 설계 결정 문서. 부록 A 불변조건 1~6에 종속되며, 충돌 시 부록 A가 이긴다.

---

## 0. 문제

`OfficialSourceService.programs()`와 `kb_products()`는 요청마다 공공 API를 호출해 제목·기관·기간·`official_url`만 남기고 나머지를 버린다. 저장은 없다. 결과적으로:

- 챗봇의 `citations`는 항상 빈 배열이다. 원문을 인용할 수단이 없다.
- `finance.subsidy`가 케이스 조건으로 공고를 좁힐 수 없다. 조달선 상향분 계산의 입력이 없다.
- `programs` 테이블은 스키마에만 있고 어떤 코드도 읽거나 쓰지 않는다.
- 외부 API 장애가 사용자 요청 경로로 그대로 전파된다.

## 1. 확정 결정

| # | 결정 | 근거 |
|---|---|---|
| 1 | 검색 계층은 공고와 KB상품이 **공용**으로 쓴다 | 사용자 결정. 질의 한 번이 두 종류를 함께 훑어야 한다 |
| 2 | 저장소는 **Supabase pgvector** | 공고는 신청기간이 매일 바뀐다. 임베딩을 git에 커밋하면 즉시 stale이 된다 |
| 3 | 자격 판정은 **구조화 필드로 코드만** 한다 | 부록 A 불변조건 4. 유사도는 순서에만 관여한다 |
| 4 | 갱신은 **수동 스크립트 + systemd 타이머** | 실패해도 되는 작업(수집)과 실패하면 안 되는 작업(검색)의 분리 |
| 5 | 쓰기는 파이프라인, 읽기는 백엔드로 **프로세스부터 분리** | 외부 API 불안정성이 사용자 요청 경로로 새지 않게 한다 |
| 6 | `/programs`를 **DB 읽기로 전환**한다 | 같은 페이로드를 두 곳에서 파싱하면 반드시 어긋난다 |

## 2. 실측 근거

2026-07-27 설정된 키로 세 원천을 직접 호출해 확인했다. 아래는 추정이 아니라 관측이다.

| 원천 | 형식 | 본문 필드 | 길이(문서 전체) |
|---|---|---|---|
| 기업마당 | XML(CDATA) | `bsnsSumryCn` (HTML) | 371~792자 (n=20) |
| K-Startup | JSON | `pbanc_ctnt` | 124~947자 (n=20) |
| 금융상품 한눈에 | JSON | 없음 (구조화 필드만) | — |

두 가지가 따라 나온다.

**청킹이 필요 없다.** 문서 전체가 최대 947자다. `text-embedding-3-small`의 한도는 8191토큰이므로 문서 1건 = 임베딩 1개로 충분하다. 청크 테이블·오버랩·재조립이 설계에서 통째로 빠진다.

**크롤링이 필요 없다.** 임베딩할 본문이 이미 API 응답에 실려 온다. `pipeline/README.md`의 크롤링 배제 원칙을 지킨 채로 구현할 수 있다.

KB상품은 본문이 없다. `fin_prdt_nm`·`join_way`·`rpay_type`·금리·한도를 **템플릿으로 문장화한 텍스트**를 임베딩한다. 이때 만들어 내는 것은 문장 구조뿐이고 값은 전부 공시 원문에서 온다.

관측된 부수 사실:

- K-Startup `supt_regin` 값에 `서울`·`전국`·`경기`·`부산`이 실제로 들어온다 → 결정론적 지역 필터가 가능하다.
- K-Startup `totalCount`는 29,566(누적 전체)이다. 저장은 진행 중인 공고로 한정한다.
- 기업마당에는 지역 필드가 없다. `jrsdInsttNm`(소관기관)이 광역지자체명일 때만 지역을 확정한다.
- Supabase는 PostgreSQL 17.6, `vector` 0.8.2 사용 가능(미설치 상태).

## 3. 스키마

```sql
create extension if not exists vector with schema extensions;

create table public.knowledge_documents (
  id text primary key,                    -- 'kstartup:178662' | 'bizinfo:PBLN_...' | 'kb-credit_loan-CR0001A'
  kind text not null check (kind in ('PROGRAM','KB_PRODUCT')),
  provider text not null,
  category text not null,
  title text not null,
  organization text not null,
  official_url text not null check (official_url ~ '^https://'),

  body_text text not null,
  content_sha256 bytea not null check (octet_length(content_sha256) = 32),
  embedding extensions.vector(1536),
  embedding_model text,

  regions text[],
  business_age_limit_years int,
  application_start date,
  application_end date,
  status text not null check (status in ('ACTIVE','CLOSED','UNKNOWN')),
  source_as_of date,

  raw jsonb not null,
  collected_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index knowledge_documents_embedding_idx on public.knowledge_documents
  using hnsw (embedding extensions.vector_cosine_ops);
create index knowledge_documents_kind_status_idx on public.knowledge_documents (kind, status);

alter table public.knowledge_documents enable row level security;
create policy knowledge_documents_public_read on public.knowledge_documents
  for select to anon, authenticated using (true);
```

`listings` 테이블과 같은 성격이다 — 세션 스코프가 아닌 공용 참조 데이터이므로 익명 읽기를 허용하고, 쓰기는 RLS를 우회하는 service role만 한다.

### 컬럼 설계의 근거

**`embedding`이 nullable이다.** 임베딩 호출이 실패한 문서도 행은 남기고 검색에서만 뺀다. 임베딩이 없다는 사실을 지우지 않으므로 "몇 건이 인덱싱되지 않았는가"를 항상 셀 수 있고, `/status`에 그 숫자를 그대로 노출한다.

**`body_text`를 저장한다.** 벡터만 두면 인용문이 원문과 일치하는지 사후 확인할 방법이 없다. 임베딩에 들어간 바로 그 문자열을 남겨야 인용이 검증 가능한 주장이 된다.

**`content_sha256`으로 재임베딩을 건너뛴다.** 매일 도는 타이머가 전량 재임베딩하면 비용이 선형으로 늘고 같은 입력에 다른 벡터가 생길 여지도 생긴다. 본문이 그대로면 벡터도 그대로 둔다.

**`regions`가 null을 허용한다.** 원천이 지역을 명시하지 않으면 null이고, 이는 "지역 제한 미상"이다. 해시태그에서 지역을 추측하는 순간 불변조건 1을 어긴다. null인 문서는 지역 필터에서 떨어뜨리지 않는다.

**기존 `programs` 테이블은 건드리지 않는다.** 현재 어떤 코드도 읽거나 쓰지 않는 미사용 테이블이다. 결과적으로 공고를 표현하는 테이블이 둘이 되지만, 정리는 별도 마이그레이션으로 분리한다 — 다른 작업 세션이 참조 중일 수 있다.

## 4. 인제스트 파이프라인

```
pipeline/policy/
  fetch.py         # 공공 API 3종 호출 + 페이지네이션. I/O만.
  normalize.py     # 원시 레코드 → KnowledgeDocument. 순수함수.
  embed.py         # 텍스트 배치 → 벡터. text-embedding-3-small (1536).
  index.py         # 엔트리포인트. fetch → normalize → diff → embed → upsert → prune
  verify_index.py  # 사람이 읽는 인덱스 리포트
  fixtures/        # 키를 지운 실제 응답 스냅샷
  test_normalize.py
```

`pipeline/verify/`가 이미 파이썬이고 `backend/.venv`를 쓴다. 같은 관습을 따르고 `npm run pipeline:policy-index`로 붙인다.

**차분 임베딩.** 회차마다 DB에서 `(id, content_sha256, embedding is null)`을 먼저 읽고, 새 문서·본문이 바뀐 문서·임베딩이 비어 있는 문서에만 임베딩을 호출한다. 메타데이터(신청기간·status·source_as_of)는 매번 무조건 갱신한다. 그쪽은 매일 바뀌는 게 정상이고 임베딩과 무관하다.

**status는 추론하지 않고 계산한다.** `application_end < 오늘`이면 `CLOSED`다. 원천이 준 날짜의 산술이지 판단이 아니다. 날짜가 없으면 `UNKNOWN`으로 남는다.

**prune은 provider 단위로, 성공했을 때만 한다.** 이번 회차에 관측되지 않은 문서는 삭제한다. 원천이 목록에서 내렸다는 것 말고는 아는 게 없으므로 "종료된 공고"라고 주장하지 않고 인덱스에서 뺀다. 단 **해당 provider의 수집이 완전히 성공한 경우에만** 그 provider의 문서를 지운다. 한 원천이 5xx를 뱉은 회차에 다른 원천의 결과로 전체를 정리하면, 외부 장애가 우리 인덱스를 비우는 사고가 된다.

**수집 범위.** K-Startup은 진행 중인 공고만 저장한다(`rcrt_prgs_yn='Y'` 또는 접수마감일이 오늘 이후). 지역은 저장 단계에서 거르지 않고 `regions`에 그대로 담는다 — 서울 스코프는 조회 시점의 필터여야 범위를 넓힐 때 재수집이 필요 없다.

**비용.** 전량 재생성해도 수천 건 × 250토큰 수준으로 회당 1달러 미만이고, 차분 방식에서 일상 회차는 0에 수렴한다.

## 5. 검색 계약

검색 진입점은 함수 하나다. 챗과 `finance.subsidy`가 같은 함수를 쓰고 소비 방식만 다르다.

```python
# backend/app/retrieval.py
async def search(self, query: str, *, kinds: list[str] | None = None,
                 regions: list[str] | None = None, only_open: bool = True,
                 limit: int = 8) -> RetrievalResult
```

질의를 임베딩 1회로 벡터화하고 `.rpc("search_knowledge", ...)`로 넘긴다. `supabase` 파이썬 클라이언트를 그대로 쓰므로 새 의존성이 없다.

```sql
create function public.search_knowledge(
  query_embedding extensions.vector(1536),
  match_kinds     text[]  default null,
  match_regions   text[]  default null,
  only_open       boolean default true,
  match_count     int     default 8,
  min_similarity  float   default 0.2
) returns table (id text, kind text, title text, organization text, official_url text,
                 body_text text, provider text, source_as_of date,
                 application_end date, collected_at timestamptz, similarity float)
language sql stable as $$
  select d.id, d.kind, d.title, d.organization, d.official_url, d.body_text,
         d.provider, d.source_as_of, d.application_end, d.collected_at,
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
```

## 6. 가드레일

**유사도는 순서에만 관여한다.** `min_similarity`는 무관한 문서를 화면에서 빼는 하한선이지 자격 판정이 아니다. 통과·탈락은 `regions`·`application_end`·`business_age_limit_years`처럼 원천이 준 값의 결정론적 비교로만 정해지고, 그 비교 결과만 `matched_conditions`에 문장으로 남는다. 예: "지원지역에 서울이 포함됨", "접수마감 2026-08-12로 오늘 기준 진행 중". 나머지는 전부 기존대로 `unknown_conditions`다.

**챗은 `ChatToolset`의 도구로 소비한다.** `chat_tools.py`에 `search_policy_documents` 도구를 더하고, 핸들러가 `RetrievalService.search()`를 부른다. 반환 dict의 `citations`에 문서 id·제목·URL·`similarity`를 담으면 `chat_stream.py`가 이미 하고 있는 수집·중복제거 경로를 그대로 탄다.

사전 검색(LLM 호출 전 무조건 검색)도 검토했으나 버린다. 도구 레지스트리가 이미 있는데 별도 경로를 만들면 챗이 두 갈래가 되고, `ChatStreamer`의 라운드·호출 상한(4라운드·12콜)과 SSE 이벤트 계약 바깥에서 도는 코드가 생긴다. "LLM이 검색을 건너뛰고 아는 척한다"는 위험은 아래 프롬프트 가드레일과 `ChatToolset.run()`의 총괄 격리(핸들러는 예외 대신 status dict를 반환한다)로 막는다.

기존 프롬프트 가드레일에 두 줄을 더한다.

> 아래 발췌는 공식 공고·공시 원문입니다. 발췌에 없는 조건·금액·자격을 만들어 내지 마세요.
> 신청 자격이 있는지 판단하지 말고, 원문에 무엇이 적혀 있는지만 전하세요.

**`finance.subsidy`는 같은 함수를 코드에서 직접 부른다.** LLM을 거치지 않으므로 조달선 상향분 계산의 입력은 여전히 순수함수다.

**등급과 출처.** 검색 결과는 맥락 신호이므로 근거 등급 `C`로 표기하고 문서마다 `Provenance`를 붙인다(provider, `source_as_of`, `collected_at`, 공간단위, 한계="공고 원문의 세부 자격은 확인 필요"). `ProvenanceBar`가 그대로 렌더한다.

**키가 없을 때.** Supabase 미설정이면 검색은 `integration_pending`으로 빈 결과와 안내 문구를 낸다. OpenAI 키가 없으면 질의를 벡터화할 수 없으므로 같은 처리다. `flow-check.mjs`의 무키 안전상태 검증이 그대로 통과한다.

**신선도 노출.** `GET /api/v1/status`에 문서 수·임베딩 결측 수·마지막 `collected_at`을 더한다. 타이머가 멈춘 것을 사용자가 알 수 있어야 한다.

## 7. 테스트

`pipeline/policy/test_normalize.py`가 무게중심이다. 실제 응답을 키를 지운 채 `fixtures/`에 저장하고, 그 페이로드가 어떤 `KnowledgeDocument`가 되는지를 고정한다. 검증 대상: 기업마당 HTML 태그 제거, `reqstBeginEndDe`의 `2026-07-22 ~ 2026-08-18` 파싱, `jrsdInsttNm`이 광역지자체명일 때만 `regions`가 채워지는 것, `biz_enyy`의 `7년미만,10년미만`에서 상한 추출, KB상품 템플릿 문장화. 전부 순수함수라 네트워크 없이 돈다. 원천이 모양을 바꾸면 여기서 먼저 깨진다.

`backend/tests/test_retrieval.py`는 가짜 Supabase 클라이언트와 가짜 임베딩 함수로 `RetrievalService`를 검증한다. 확인할 것은 세 가지다 — 키가 없으면 예외가 아니라 `integration_pending` 빈 결과가 나오는가, `matched_conditions`에 코드가 비교한 항목만 들어가는가, 유사도가 판정에 새어 들어가지 않는가.

SQL 함수는 단위 테스트가 어렵다. 대신 `pipeline/policy/verify_index.py`가 실제 DB에 붙어 문서 수·임베딩 결측 수·알려진 질의의 상위 결과를 출력한다. 자동 판정이 아니라 사람이 읽는 리포트다.

`flow-check.mjs`의 무키 안전상태 검증이 회귀 방지선이다.

## 8. 실패 모드

| 상황 | 동작 |
|---|---|
| 공공 API 한 곳이 5xx·타임아웃 | 그 provider만 이번 회차 건너뛰고 prune하지 않음. stderr 경고 + 요약 리포트에 기록. 전부 실패하면 exit 1 |
| 임베딩 호출 실패 | 그 배치는 `embedding = null`로 upsert. 메타데이터는 갱신되고 검색에서만 빠짐. 다음 회차가 `embedding is null`로 자동 재시도 |
| Supabase 쓰기 실패 | 배치 단위 실패. upsert가 멱등이므로 재실행이 곧 복구 |
| 임베딩 모델 변경 | `embedding_model`이 다른 문서가 섞이면 유사도가 의미를 잃는다. 불일치를 감지하면 **멈추고** `--reembed`를 명시적으로 요구한다. 자동으로 섞지 않는다 |
| 검색 중 Supabase 장애 | 챗은 답을 못 하면 안 되므로 `citations` 없이 기존 응답으로 폴백하고 "근거 검색이 지연되어 원문 인용 없이 답했습니다"를 명시 |
| 타이머가 한 번도 안 돎 | `/programs`가 빈 상태. `/status`의 신선도로 원인이 드러남 |
| 질의 남용 | 질의 임베딩은 유료 호출이므로 기존 `AI_DAILY_REQUEST_LIMIT`과 같은 결의 세션당 일일 상한을 적용 |

## 9. 설정

추가는 둘뿐이다. 나머지는 이미 있는 키를 쓴다.

| 키 | 기본값 | 의미 |
|---|---|---|
| `EMBEDDING_MODEL` | `""` | 비어 있으면 검색 비활성 |
| `EMBEDDING_DIMENSION` | `1536` | 마이그레이션의 `vector(1536)`과 일치해야 함 |

`.env.example`에 두 줄을 더하고 기존 관습대로 값은 비워 둔다.

## 10. 변경 범위

```
신규  supabase/migrations/2026072800xx_knowledge_documents.sql
      backend/app/retrieval.py
      backend/tests/test_retrieval.py
      pipeline/policy/{fetch,normalize,embed,index,verify_index}.py
      pipeline/policy/fixtures/ + test_normalize.py
      deploy/ 타이머 unit

수정  backend/app/main.py      /programs·/programs/catalog를 DB 읽기로, /status 신선도, 검색 엔드포인트
      backend/app/services.py  OfficialSourceService의 라이브 조회 경로 제거
      backend/app/models.py    검색 응답 계약
      lib/types.ts             동일 계약 미러링 (snake_case, 필드 대 필드)
      backend/app/config.py    EMBEDDING_MODEL·EMBEDDING_DIMENSION
      .env.example             위 두 키
      package.json             pipeline:policy-index

후속  backend/app/chat_tools.py  search_policy_documents 도구 (§12 참조)
```

`lib/domain.ts`는 stale이므로 건드리지 않는다.

## 12. 병행 작업과의 경계

2026-07-27 기준 세 갈래가 동시에 움직인다.

| 갈래 | 상태 | 이 스펙과의 관계 |
|---|---|---|
| `origin/main` (9b22b78) | 이 작업의 base | — |
| `feat/landing-listing-overview` | 메인 체크아웃. 랜딩·매물 지도 | 겹치지 않음 |
| `worktree-ipzitalk-mcp-chat` | `mcp_client.py`·`chat_tools.py`·`chat_stream.py` (미머지) | **§6의 챗 도구가 여기에 의존한다** |

따라서 구현을 두 덩이로 나눈다.

**덩이 1 — 지금 한다.** 마이그레이션, `pipeline/policy/`, `RetrievalService`, `/programs`의 DB 전환, `/status` 신선도, 계약 미러링. 챗 코드에 전혀 의존하지 않는다.

**덩이 2 — 챗 브랜치가 머지된 뒤에 한다.** `ChatToolset`에 `search_policy_documents`를 더하는 작업. `RetrievalService.search()`가 챗을 모르는 평범한 async 함수이므로, 덩이 1을 다시 건드리지 않고 도구 핸들러만 얹으면 된다.

이 경계가 지켜지는지는 한 가지로 확인한다 — 덩이 1의 어떤 파일도 `chat_tools`·`chat_stream`·`mcp_client`를 import하지 않는다.

## 11. 부록 A 대조

| 불변조건 | 이행 |
|---|---|
| 1. 날조 금지 | 키·URL 미설정이면 빈 결과 + 안내. 지역은 원천이 명시할 때만 확정. 임베딩 결측을 숨기지 않고 센다 |
| 2. 등급 A/B/C/U | 검색 결과는 `C`. 개별 생존확률은 어디에도 나오지 않는다 |
| 3. 출처 표시 | 문서마다 `Provenance`. `collected_at`으로 신선도까지 노출 |
| 4. AI는 설명, 코드는 계산 | 자격 판정은 구조화 필드의 결정론적 비교만. 유사도는 순서에만 관여. 프롬프트에 판정 금지 문구 추가 |
| 5. 게이트된 기능 | 변경 없음. 실제 신청·마이데이터는 여전히 미구현 |
| 6. 서울 25개 자치구 | 저장은 전국, 조회 시 `['서울','전국']` 필터. 지역 미상 문서는 떨어뜨리지 않고 미상으로 표시 |
