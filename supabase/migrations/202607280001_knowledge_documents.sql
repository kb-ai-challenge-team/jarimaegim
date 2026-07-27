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
