-- 자리매김 production baseline. Browser roles never access domain tables directly.
create extension if not exists pgcrypto;

create type public.owner_kind as enum ('USER','ANONYMOUS');
create type public.evidence_grade as enum ('A','B','C','U');
create type public.message_role as enum ('USER','ASSISTANT','TOOL','SYSTEM');
create type public.job_status as enum ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED');
create type public.privacy_status as enum ('RECEIVED','IDENTITY_PENDING','VERIFIED','IN_PROGRESS','COMPLETED','REJECTED','CANCELLED');

create function public.set_updated_at() returns trigger language plpgsql set search_path=pg_catalog,public as $$
begin new.updated_at=now(); return new; end $$;
revoke all on function public.set_updated_at() from public, anon, authenticated;

create table public.retention_policy (
  policy_key text primary key,
  purpose text not null,
  object_type text not null,
  active_days int not null check(active_days between 0 and 3650),
  backup_rolloff_days int not null check(backup_rolloff_days between 0 and 3650),
  legal_basis text,
  approved_by uuid,
  approved_at timestamptz,
  version int not null check(version>0),
  is_active boolean not null default false,
  unique(object_type,version)
);
insert into public.retention_policy(policy_key,purpose,object_type,active_days,backup_rolloff_days,version,is_active)
values ('ANON_24H','비로그인 분석을 위한 단기 세션','anonymous_session',1,30,1,false),
       ('MESSAGE_USER','사용자가 저장을 선택한 케이스 대화','message',3650,30,1,false),
       ('STREAM_SHORT','SSE 재연결 이벤트','stream_event',1,7,1,false);

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  locale text not null default 'ko-KR',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.anonymous_sessions (
  id uuid primary key default gen_random_uuid(), token_hash text not null unique,
  token_version smallint not null default 1, status text not null check(status in ('ACTIVE','CLAIMED','EXPIRED','DELETING')),
  last_seen_at timestamptz not null, retention_class text not null references public.retention_policy(policy_key) on delete restrict,
  claimed_by uuid references public.profiles(user_id) on delete set null, expires_at timestamptz not null,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  check(expires_at>created_at)
);
create index anonymous_sessions_expiry_idx on public.anonymous_sessions(status,expires_at);

create table public.cases (
  id uuid primary key default gen_random_uuid(), owner_user_id uuid references public.profiles(user_id) on delete cascade,
  anonymous_session_id uuid references public.anonymous_sessions(id) on delete cascade,
  title text not null check(length(title) between 1 and 120), status text not null default 'ACTIVE' check(status in ('ACTIVE','DELETING','DELETED')),
  version bigint not null default 1 check(version>0), created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  check((owner_user_id is not null)::int+(anonymous_session_id is not null)::int=1)
);
create index cases_owner_user_idx on public.cases(owner_user_id) where owner_user_id is not null;
create index cases_owner_anon_idx on public.cases(anonymous_session_id) where anonymous_session_id is not null;
create table public.case_inputs (
  case_id uuid not null references public.cases(id) on delete cascade, field text not null,
  value_json jsonb not null, source text not null check(source in ('USER','FORM','IMPORT')),
  confirmed_at timestamptz not null, confirmed_by_message_id uuid,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(), primary key(case_id,field),
  check(field in ('industry','district','budget_krw','equity_krw','business_stage','startup_type','priority'))
);

create table public.conversations (
  id uuid primary key default gen_random_uuid(), case_id uuid not null unique references public.cases(id) on delete cascade,
  status text not null default 'ACTIVE' check(status in ('ACTIVE','CLOSED')), last_sequence bigint not null default 0 check(last_sequence>=0),
  retention_class text not null references public.retention_policy(policy_key) on delete restrict,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.messages (
  id uuid primary key default gen_random_uuid(), conversation_id uuid not null references public.conversations(id) on delete cascade,
  client_message_id uuid, role public.message_role not null, content_redacted text, content_sha256 bytea,
  confirmed_case_patch jsonb, proposed_case_patch jsonb, tool_call_id uuid, tool_name text, tool_result_redacted jsonb,
  model_version text, prompt_version text, tool_version text, finish_reason text,
  retention_class text not null references public.retention_policy(policy_key) on delete restrict,
  sequence bigint not null check(sequence>0), created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(conversation_id,sequence)
);
create unique index messages_client_id_idx on public.messages(conversation_id,client_message_id) where client_message_id is not null;

create table public.source_documents (
  id uuid primary key default gen_random_uuid(), source_key text not null unique, official_url text not null check(official_url~'^https://'),
  publisher text not null, title text not null, status text not null check(status in ('ACTIVE','RETIRED')),
  license_status text not null default 'UNVERIFIED', observation_unit text not null, industry_scope text not null, spatial_unit text not null,
  verified_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.source_snapshots (
  id uuid primary key default gen_random_uuid(), source_document_id uuid not null references public.source_documents(id) on delete restrict,
  version int not null check(version>0), content_sha256 bytea not null check(octet_length(content_sha256)=32),
  source_as_of date, published_at timestamptz, fetched_at timestamptz not null, raw_object_key text not null,
  mime_type text not null, status text not null check(status in ('VALIDATING','PUBLISHED','REJECTED','SUPERSEDED')),
  created_at timestamptz not null default now(), unique(source_document_id,version), unique(source_document_id,content_sha256)
);

create table public.location_candidates (
  id uuid primary key default gen_random_uuid(), case_id uuid not null references public.cases(id) on delete cascade,
  external_source text not null, external_id text not null, name text not null, address text not null,
  latitude numeric(10,7) not null check(latitude between 33 and 39), longitude numeric(10,7) not null check(longitude between 124 and 132),
  evidence_grade public.evidence_grade not null, provenance jsonb not null,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(case_id,external_source,external_id)
);
create table public.analysis_results (
  id uuid primary key default gen_random_uuid(), case_id uuid not null references public.cases(id) on delete cascade,
  candidate_id uuid references public.location_candidates(id) on delete set null, evidence_grade public.evidence_grade not null,
  survival_grade char(1), context_risk_grade text, probability_lower numeric(5,2), probability_upper numeric(5,2),
  probability_unit text, horizon_months smallint, confidence text not null check(confidence in ('HIGH','MEDIUM','LOW','INSUFFICIENT')),
  sample_n bigint, event_n bigint, context_signals jsonb, blocked_reason text, required_actions jsonb not null default '[]',
  limitations jsonb not null default '[]', model_version text not null, provenance jsonb not null,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  constraint analysis_result_by_evidence_ck check(case evidence_grade
    when 'A' then survival_grade in ('A','B','C','D','E') and context_risk_grade is null and probability_lower between 0 and 100 and probability_upper between probability_lower and 100 and probability_unit='PERCENT_0_100' and horizon_months>0 and sample_n>0 and event_n>=0 and blocked_reason is null
    when 'B' then survival_grade is null and context_risk_grade in ('LOW','MEDIUM','HIGH') and probability_lower is null and probability_upper is null and probability_unit is null and horizon_months is null and sample_n>0 and (event_n is null or event_n>=0) and blocked_reason is null
    when 'C' then survival_grade is null and context_risk_grade is null and probability_lower is null and probability_upper is null and probability_unit is null and horizon_months is null and (sample_n is null or sample_n>0) and event_n is null and jsonb_typeof(context_signals)='array' and blocked_reason is null
    when 'U' then survival_grade is null and context_risk_grade is null and probability_lower is null and probability_upper is null and probability_unit is null and horizon_months is null and sample_n is null and event_n is null and length(blocked_reason)>0
    else false end)
);
create table public.analysis_result_sources (
  analysis_result_id uuid not null references public.analysis_results(id) on delete cascade,
  source_snapshot_id uuid not null references public.source_snapshots(id) on delete restrict,
  ordinal smallint not null check(ordinal>0), created_at timestamptz not null default now(), primary key(analysis_result_id,source_snapshot_id), unique(analysis_result_id,ordinal)
);

create table public.cost_plans (
  id uuid primary key default gen_random_uuid(), case_id uuid not null references public.cases(id) on delete cascade,
  items jsonb not null check(jsonb_typeof(items)='array'), total_min_krw bigint not null check(total_min_krw>=0), total_max_krw bigint not null check(total_max_krw>=total_min_krw),
  equity_krw bigint not null check(equity_krw>=0), gap_min_krw bigint not null check(gap_min_krw>=0), gap_max_krw bigint not null check(gap_max_krw>=gap_min_krw),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.programs (
  id uuid primary key default gen_random_uuid(), source_document_id uuid not null references public.source_documents(id) on delete restrict,
  external_id text not null, category text not null check(category in ('GOVERNMENT','POLICY_FUND','GUARANTEE','PRIVATE')),
  title text not null, organization text not null, official_url text not null check(official_url~'^https://'),
  application_start date, application_end date, status text not null check(status in ('ACTIVE','CLOSED','UNKNOWN')),
  source_as_of date, published_at timestamptz, collected_at timestamptz not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(source_document_id,external_id)
);
create table public.documents (
  id uuid primary key default gen_random_uuid(), case_id uuid not null references public.cases(id) on delete cascade,
  owner_user_id uuid not null references public.profiles(user_id) on delete cascade, template text not null,
  object_key text, content_sha256 bytea, status public.job_status not null default 'QUEUED',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.notifications (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(user_id) on delete cascade,
  kind text not null, payload_redacted jsonb not null, dedupe_key text not null, read_at timestamptz,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(user_id,dedupe_key)
);
create table public.notification_settings (
  user_id uuid primary key references public.profiles(user_id) on delete cascade, settings jsonb not null,
  version bigint not null default 1 check(version>0), created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.privacy_requests (
  id uuid primary key default gen_random_uuid(), requester_user_id uuid references public.profiles(user_id) on delete set null,
  anonymous_session_id uuid references public.anonymous_sessions(id) on delete set null,
  request_type text not null check(request_type in ('ACCESS','RECTIFY','ERASE','RESTRICT','WITHDRAW_CONSENT')),
  status public.privacy_status not null, verification_method text not null check(verification_method in ('ACCOUNT_REAUTH','ANON_COOKIE','EMAIL_CHALLENGE')),
  verified_at timestamptz, due_at timestamptz, completed_at timestamptz, result_manifest jsonb not null default '{}',
  idempotency_key uuid not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  check((requester_user_id is not null)::int+(anonymous_session_id is not null)::int=1)
);
create table public.jobs (
  id uuid primary key default gen_random_uuid(), kind text not null, aggregate_id uuid, status public.job_status not null default 'QUEUED',
  dedupe_key text not null unique, attempt_count int not null default 0 check(attempt_count>=0), next_attempt_at timestamptz not null default now(),
  lease_until timestamptz, error_redacted text, payload_redacted jsonb not null default '{}',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.audit_events (
  id bigserial primary key, actor_hash bytea, actor_type text not null, action text not null,
  target_type text not null, target_id uuid, before_hash bytea, after_hash bytea, reason text,
  request_id uuid not null, created_at timestamptz not null default now()
);

-- Keep mutable timestamps consistent.
do $$ declare t text; begin foreach t in array array['profiles','anonymous_sessions','cases','case_inputs','conversations','messages','source_documents','location_candidates','analysis_results','cost_plans','programs','documents','notifications','notification_settings','privacy_requests','jobs'] loop execute format('create trigger %I_updated before update on public.%I for each row execute function public.set_updated_at()',t,t); end loop; end $$;

-- FastAPI service role is the only domain-data caller. Browser roles have no table or sequence access.
do $$ declare t text; begin foreach t in array array['profiles','anonymous_sessions','cases','case_inputs','conversations','messages','source_documents','source_snapshots','location_candidates','analysis_results','analysis_result_sources','cost_plans','programs','documents','notifications','notification_settings','privacy_requests','jobs','audit_events','retention_policy'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('revoke all privileges on table public.%I from anon, authenticated',t);
end loop; end $$;
revoke all privileges on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;

-- Service-only ownership predicate helper. Caller identities are verified by FastAPI before invocation.
create function public.api_case_owned(p_case uuid,p_user uuid,p_session uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
  select exists(select 1 from public.cases c where c.id=p_case and c.status='ACTIVE' and
    ((p_user is not null and p_session is null and c.owner_user_id=p_user) or
     (p_user is null and p_session is not null and c.anonymous_session_id=p_session)))
$$;
revoke all on function public.api_case_owned(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.api_case_owned(uuid,uuid,uuid) to service_role;

-- Private object stores. No browser policy is created; FastAPI issues owner-checked signed URLs.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('private-documents','private-documents',false,52428800,array['application/pdf']),
       ('source-raw','source-raw',false,524288000,null),
       ('model-artifacts','model-artifacts',false,524288000,null)
on conflict(id) do update set public=false;
