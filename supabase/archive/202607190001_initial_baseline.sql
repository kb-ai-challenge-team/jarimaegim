-- 터닥터 initial Supabase baseline. Browser roles have no direct table or Storage access.
begin;

create extension if not exists pgcrypto with schema extensions;
create extension if not exists vector with schema extensions;

create type public.owner_kind as enum ('USER','ANONYMOUS');
create type public.evidence_grade as enum ('A','B','C','U');
create type public.message_role as enum ('USER','ASSISTANT','TOOL','SYSTEM');
create type public.job_status as enum ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED');
create type public.privacy_status as enum ('RECEIVED','IDENTITY_PENDING','VERIFIED','IN_PROGRESS','COMPLETED','REJECTED','CANCELLED');

create function public.set_updated_at()
returns trigger language plpgsql
set search_path = pg_catalog, public as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create table public.retention_policy (
  policy_key text primary key,
  purpose text not null,
  object_type text not null,
  active_days int not null check (active_days between 0 and 3650),
  backup_rolloff_days int not null check (backup_rolloff_days between 0 and 3650),
  legal_basis text,
  approved_by uuid,
  approved_at timestamptz,
  version int not null check (version > 0),
  is_active boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (object_type, version)
);

insert into public.retention_policy
  (policy_key,purpose,object_type,active_days,backup_rolloff_days,version,is_active)
values
  ('ANON_24H','익명 세션 임시 저장','anonymous_session',1,30,1,true),
  ('USER_UNTIL_DELETE','사용자가 저장한 업무 데이터(최대 기간 내 사용자 삭제 우선)','user_content',3650,30,1,true),
  ('STREAM_24H','SSE 재연결 이벤트','stream_event',1,30,1,true),
  ('AUDIT_365D','보안 및 변경 감사','audit_event',365,30,1,true);

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text check (display_name is null or length(display_name) <= 120),
  locale text not null default 'ko-KR',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.anonymous_sessions (
  id uuid primary key default gen_random_uuid(),
  token_hash bytea not null unique check (octet_length(token_hash) = 32),
  token_version smallint not null default 1 check (token_version > 0),
  status text not null check (status in ('ACTIVE','CLAIMED','EXPIRED','DELETING')),
  last_seen_at timestamptz not null,
  retention_class text not null references public.retention_policy(policy_key) on delete restrict,
  claimed_by uuid references public.profiles(user_id) on delete set null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (expires_at > created_at),
  check (expires_at <= created_at + interval '24 hours 5 minutes')
);

create table public.cases (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid references public.profiles(user_id) on delete cascade,
  anonymous_session_id uuid references public.anonymous_sessions(id) on delete cascade,
  title text not null check (length(title) between 1 and 120),
  status text not null default 'ACTIVE' check (status in ('ACTIVE','DELETING','DELETED')),
  version bigint not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((owner_user_id is not null)::int + (anonymous_session_id is not null)::int = 1)
);
create index cases_owner_user_idx on public.cases(owner_user_id) where owner_user_id is not null;
create index cases_anon_session_idx on public.cases(anonymous_session_id) where anonymous_session_id is not null;
create index cases_status_updated_idx on public.cases(status,updated_at);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null unique references public.cases(id) on delete cascade,
  status text not null default 'ACTIVE' check (status in ('ACTIVE','CLOSED')),
  last_sequence bigint not null default 0 check (last_sequence >= 0),
  retention_class text not null references public.retention_policy(policy_key) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  client_message_id uuid,
  role public.message_role not null,
  content_redacted text,
  content_sha256 bytea check (content_sha256 is null or octet_length(content_sha256)=32),
  confirmed_case_patch jsonb,
  proposed_case_patch jsonb,
  tool_call_id uuid,
  tool_name text,
  tool_result_redacted jsonb,
  model_version text,
  prompt_version text,
  tool_version text,
  finish_reason text,
  retention_class text not null references public.retention_policy(policy_key) on delete restrict,
  sequence bigint not null check (sequence > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (conversation_id,sequence),
  check (confirmed_case_patch is null or role = 'USER'),
  check ((role = 'TOOL') = (tool_name is not null and tool_result_redacted is not null)),
  check (role <> 'ASSISTANT' or (model_version is not null and prompt_version is not null)),
  check ((role in ('USER','ASSISTANT','SYSTEM') and content_redacted is not null) or (role='TOOL' and tool_result_redacted is not null))
);
create unique index messages_client_id_uq on public.messages(conversation_id,client_message_id) where client_message_id is not null;
create index messages_conversation_created_idx on public.messages(conversation_id,created_at);

create table public.case_inputs (
  case_id uuid not null references public.cases(id) on delete cascade,
  field text not null check (field in ('industry_id','district_code','budget_krw','equity_krw','business_stage','startup_type')),
  value_json jsonb not null,
  source text not null check (source in ('USER','FORM','IMPORT')),
  confirmed_at timestamptz not null,
  confirmed_by_message_id uuid references public.messages(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (case_id,field),
  check (field not in ('budget_krw','equity_krw') or (jsonb_typeof(value_json)='number' and (value_json::text)::numeric >= 0))
);

create table public.source_documents (
  id uuid primary key default gen_random_uuid(),
  source_key text not null unique,
  official_url text not null check (official_url ~ '^https://[^[:space:]]+$'),
  publisher text not null,
  title text not null,
  status text not null check (status in ('ACTIVE','RETIRED')),
  retention_class text not null references public.retention_policy(policy_key) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.source_snapshots (
  id uuid primary key default gen_random_uuid(),
  source_document_id uuid not null references public.source_documents(id) on delete restrict,
  version int not null check (version > 0),
  content_sha256 bytea not null check (octet_length(content_sha256)=32),
  fetched_at timestamptz not null,
  published_at timestamptz,
  source_as_of date,
  raw_object_key text not null,
  mime_type text not null,
  status text not null check (status in ('VALIDATING','PUBLISHED','REJECTED','SUPERSEDED')),
  created_at timestamptz not null default now(),
  unique (source_document_id,version),
  unique (source_document_id,content_sha256),
  unique (id,source_document_id)
);
create index source_snapshots_published_idx on public.source_snapshots(source_document_id,published_at desc) where status='PUBLISHED';

create table public.message_citations (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null references public.messages(id) on delete cascade,
  source_document_id uuid not null references public.source_documents(id) on delete restrict,
  source_snapshot_id uuid not null,
  official_url text not null check (official_url ~ '^https://'),
  title text not null,
  page int check (page > 0),
  section text,
  quote_redacted text,
  source_hash bytea not null check (octet_length(source_hash)=32),
  created_at timestamptz not null default now(),
  check (page is not null or section is not null),
  unique (message_id,source_snapshot_id,page,section),
  foreign key (source_snapshot_id,source_document_id) references public.source_snapshots(id,source_document_id) on delete restrict
);

create table public.message_stream_events (
  message_id uuid not null references public.messages(id) on delete cascade,
  sequence bigint not null check (sequence > 0),
  event_type text not null check (event_type in ('message.accepted','case.patch.confirmed','assistant.delta','tool.started','tool.result','citation','message.completed','error','heartbeat')),
  payload_redacted jsonb not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  primary key (message_id,sequence),
  check (expires_at > created_at)
);
create index stream_events_expiry_idx on public.message_stream_events(expires_at);

create table public.analysis_results (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.cases(id) on delete cascade,
  status text not null default 'completed' check (status in ('completed','blocked')),
  evidence_grade public.evidence_grade not null,
  survival_grade char(1),
  context_risk_grade text,
  probability_lower numeric(5,2),
  probability_upper numeric(5,2),
  probability_unit text,
  horizon_months smallint,
  confidence text not null check (confidence in ('HIGH','MEDIUM','LOW','INSUFFICIENT')),
  sample_n bigint,
  event_n bigint,
  context_signals jsonb not null default '[]'::jsonb,
  blocked_reason text,
  required_actions jsonb not null default '[]'::jsonb check (jsonb_typeof(required_actions)='array'),
  provenance jsonb not null default '{}'::jsonb,
  limitations jsonb not null default '[]'::jsonb check (jsonb_typeof(limitations)='array'),
  model_version text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint analysis_result_by_evidence_ck check (
    case evidence_grade
      when 'A' then
        survival_grade is not null and survival_grade in ('A','B','C','D','E')
        and context_risk_grade is null
        and probability_lower is not null and probability_lower between 0 and 100
        and probability_upper is not null and probability_upper between probability_lower and 100
        and probability_unit = 'PERCENT_0_100'
        and horizon_months is not null and horizon_months > 0
        and sample_n is not null and sample_n > 0
        and event_n is not null and event_n >= 0
        and blocked_reason is null
      when 'B' then
        survival_grade is null
        and context_risk_grade in ('LOW','MEDIUM','HIGH')
        and probability_lower is null and probability_upper is null
        and probability_unit is null and horizon_months is null
        and sample_n is not null and sample_n > 0
        and (event_n is null or event_n >= 0)
        and blocked_reason is null
      when 'C' then
        survival_grade is null and context_risk_grade is null
        and probability_lower is null and probability_upper is null
        and probability_unit is null and horizon_months is null
        and (sample_n is null or sample_n > 0) and event_n is null
        and context_signals is not null and jsonb_typeof(context_signals)='array'
        and blocked_reason is null
      when 'U' then
        survival_grade is null and context_risk_grade is null
        and probability_lower is null and probability_upper is null
        and probability_unit is null and horizon_months is null
        and sample_n is null and event_n is null
        and blocked_reason is not null and length(blocked_reason)>0
      else false
    end
  )
);
create index analysis_results_case_created_idx on public.analysis_results(case_id,created_at desc);

create table public.analysis_result_sources (
  analysis_result_id uuid not null references public.analysis_results(id) on delete cascade,
  source_snapshot_id uuid not null references public.source_snapshots(id) on delete restrict,
  ordinal smallint not null check (ordinal > 0),
  created_at timestamptz not null default now(),
  primary key (analysis_result_id,source_snapshot_id),
  unique (analysis_result_id,ordinal)
);

create table public.cost_plans (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.cases(id) on delete cascade,
  items jsonb not null check (jsonb_typeof(items)='array'),
  total_minimum_krw bigint not null check (total_minimum_krw >= 0),
  total_maximum_krw bigint not null check (total_maximum_krw >= total_minimum_krw),
  equity_krw bigint not null check (equity_krw >= 0),
  funding_gap_minimum_krw bigint not null check (funding_gap_minimum_krw >= 0),
  funding_gap_maximum_krw bigint not null check (funding_gap_maximum_krw >= funding_gap_minimum_krw),
  calculation_version text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index cost_plans_case_idx on public.cost_plans(case_id,created_at desc);

create table public.program_records (
  id uuid primary key,
  provider text not null check (provider in ('SEOUL','BIZINFO','KSTARTUP','FINLIFE')),
  source_record_id text not null,
  title text not null,
  official_url text not null check (official_url ~ '^https://'),
  published_at timestamptz,
  application_start date,
  application_end date,
  source_snapshot_id uuid references public.source_snapshots(id) on delete restrict,
  structured_criteria jsonb not null default '{}'::jsonb,
  collected_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider,source_record_id),
  check (application_end is null or application_start is null or application_end >= application_start)
);
create index program_records_period_idx on public.program_records(application_end,published_at desc);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.cases(id) on delete cascade,
  status text not null check (status in ('QUEUED','RUNNING','SUCCEEDED','FAILED','CLAIMING','DELETING')),
  template text not null check (template in ('LOCATION_ANALYSIS','STARTUP_COST','FUNDING_PLAN','BUSINESS_PLAN_DRAFT','APPLICATION_CHECKLIST')),
  object_path text,
  manifest jsonb not null default '{}'::jsonb,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((status='SUCCEEDED') = (object_path is not null and completed_at is not null))
);
create index documents_case_created_idx on public.documents(case_id,created_at desc);

create table public.consent_records (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  type text not null,
  scope jsonb not null,
  recipient text,
  policy_version text not null,
  status text not null check (status in ('GRANTED','WITHDRAWN','EXPIRED')),
  granted_at timestamptz not null,
  withdrawn_at timestamptz,
  expires_at timestamptz,
  idempotency_key uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id,type,idempotency_key),
  check (status <> 'WITHDRAWN' or withdrawn_at is not null)
);

create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  kind text not null,
  payload_redacted jsonb not null,
  dedupe_key text not null,
  read_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id,dedupe_key)
);
create index notifications_user_unread_idx on public.notifications(user_id,created_at desc) where read_at is null;

create table public.notification_settings (
  user_id uuid primary key references public.profiles(user_id) on delete cascade,
  settings jsonb not null default '{"in_app":true,"email_program_deadline":false,"email_document_status":false,"email_data_updates":false}'::jsonb,
  version bigint not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (coalesce((settings->>'in_app')::boolean,true)=true)
);

create table public.outbox_events (
  id uuid primary key default gen_random_uuid(),
  topic text not null,
  aggregate_type text not null,
  aggregate_id uuid not null,
  payload_redacted jsonb not null,
  status text not null check (status in ('PENDING','LEASED','SENT','FAILED','CANCELLED')),
  dedupe_key text not null unique,
  attempt_count int not null default 0 check (attempt_count >= 0),
  available_at timestamptz not null default now(),
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index outbox_lease_idx on public.outbox_events(status,available_at) where status in ('PENDING','FAILED');

create table public.notification_suppressions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  channel text not null check (channel='EMAIL'),
  destination_hash bytea not null check (octet_length(destination_hash)=32),
  reason text not null check (reason in ('BOUNCE','COMPLAINT','USER_OPT_OUT')),
  provider_event_id text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index notification_suppressions_active_uq on public.notification_suppressions(channel,destination_hash) where active;

create table public.notification_deliveries (
  id uuid primary key default gen_random_uuid(),
  notification_id uuid not null references public.notifications(id) on delete cascade,
  outbox_event_id uuid not null references public.outbox_events(id) on delete restrict,
  suppression_id uuid references public.notification_suppressions(id) on delete set null,
  channel text not null check (channel='EMAIL'),
  status text not null check (status in ('QUEUED','SENDING','DELIVERED','BOUNCED','COMPLAINED','SUPPRESSED','FAILED')),
  attempt_count int not null default 0 check (attempt_count >= 0),
  dedupe_key text not null unique,
  provider_message_id text,
  provider_event_id text,
  error_redacted text,
  next_attempt_at timestamptz,
  sent_at timestamptz,
  delivered_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (notification_id,channel),
  check (status not in ('BOUNCED','COMPLAINED','SUPPRESSED') or suppression_id is not null)
);
create unique index notification_provider_event_uq on public.notification_deliveries(provider_event_id) where provider_event_id is not null;

create table public.privacy_requests (
  id uuid primary key default gen_random_uuid(),
  requester_user_id uuid references public.profiles(user_id) on delete set null,
  anonymous_session_id uuid references public.anonymous_sessions(id) on delete set null,
  request_type text not null check (request_type in ('ACCESS','RECTIFY','ERASE','RESTRICT','WITHDRAW_CONSENT')),
  status public.privacy_status not null,
  verification_method text not null check (verification_method in ('ACCOUNT_REAUTH','ANON_COOKIE','EMAIL_CHALLENGE')),
  verification_hash bytea,
  verified_at timestamptz,
  due_at timestamptz,
  completed_at timestamptz,
  result_manifest jsonb not null default '{}'::jsonb,
  rejection_code text,
  idempotency_key uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((requester_user_id is not null)::int + (anonymous_session_id is not null)::int = 1)
);
create unique index privacy_user_idempotency_uq on public.privacy_requests(requester_user_id,idempotency_key) where requester_user_id is not null;
create unique index privacy_anon_idempotency_uq on public.privacy_requests(anonymous_session_id,idempotency_key) where anonymous_session_id is not null;

create table public.app_roles (
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  role text not null check (role in ('ADMIN','PRIVACY_OPERATOR','DATA_PUBLISHER')),
  valid_from timestamptz not null,
  valid_to timestamptz,
  granted_by uuid not null references public.profiles(user_id) on delete restrict,
  reason text not null,
  created_at timestamptz not null default now(),
  primary key (user_id,role),
  check (valid_to is null or valid_to > valid_from)
);

create table public.vendor_limits (
  vendor text not null,
  limit_key text not null,
  environment text not null,
  value_numeric numeric,
  value_text text,
  unit text not null,
  source_url text not null check (source_url ~ '^https://'),
  verified_at timestamptz not null,
  expires_at timestamptz not null,
  version int not null check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((value_numeric is null) <> (value_text is null)),
  check (expires_at > verified_at),
  primary key (vendor,limit_key,environment,version)
);

create table public.idempotency_keys (
  actor_hash bytea not null check (octet_length(actor_hash)=32),
  route text not null,
  key uuid not null,
  request_hash bytea not null check (octet_length(request_hash)=32),
  status_code int check (status_code between 100 and 599),
  response_redacted jsonb,
  resource_id uuid,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (actor_hash,route,key),
  check (expires_at <= created_at + interval '24 hours 5 minutes')
);
create index idempotency_expiry_idx on public.idempotency_keys(expires_at);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  case_id uuid references public.cases(id) on delete cascade,
  job_type text not null,
  status public.job_status not null default 'QUEUED',
  dedupe_key text not null unique,
  attempt_count int not null default 0 check (attempt_count >= 0),
  next_attempt_at timestamptz not null default now(),
  lease_until timestamptz,
  error_redacted text,
  payload_redacted jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index jobs_lease_idx on public.jobs(status,next_attempt_at) where status in ('QUEUED','FAILED');

create table public.deletion_jobs (
  id uuid primary key default gen_random_uuid(),
  requester_user_id uuid references public.profiles(user_id) on delete set null,
  anonymous_session_id uuid references public.anonymous_sessions(id) on delete set null,
  case_id uuid references public.cases(id) on delete set null,
  scope jsonb not null,
  status public.job_status not null default 'QUEUED',
  dedupe_key text not null unique,
  attempt_count int not null default 0 check (attempt_count >= 0),
  next_attempt_at timestamptz not null default now(),
  lease_until timestamptz,
  backup_rolloff_at timestamptz not null,
  result_manifest jsonb not null default '{}'::jsonb,
  error_redacted text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (backup_rolloff_at > created_at)
);

create table public.audit_events (
  id bigserial primary key,
  actor_pseudonym bytea,
  actor_type public.owner_kind,
  action text not null,
  target_type text not null,
  target_id uuid,
  before_hash bytea check (before_hash is null or octet_length(before_hash)=32),
  after_hash bytea check (after_hash is null or octet_length(after_hash)=32),
  reason text,
  request_id uuid not null,
  created_at timestamptz not null default now()
);
create index audit_events_target_idx on public.audit_events(target_type,target_id,created_at desc);

create table public.kill_switches (
  name text primary key check (name in ('ai_explanation','individual_probability','financial_application','consultation_transfer')),
  enabled boolean not null default false,
  reason text not null,
  expires_at timestamptz,
  version bigint not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
insert into public.kill_switches(name,enabled,reason) values
  ('ai_explanation',false,'환경 설정 및 운영 승인이 우선'),
  ('individual_probability',false,'검증된 active 모델 승인 전 차단'),
  ('financial_application',false,'제휴·법무·보안 게이트 미완료'),
  ('consultation_transfer',false,'제휴·별도 동의 게이트 미완료');

create table public.source_datasets (
  id uuid primary key default gen_random_uuid(),
  dataset_key text not null unique,
  provider text not null,
  official_url text not null check (official_url ~ '^https://[^[:space:]]+$'),
  license_status text not null check (license_status in ('VERIFIED','UNVERIFIED','RESTRICTED')),
  observation_unit text not null,
  industry_scope text not null,
  spatial_unit text not null,
  update_cadence text not null,
  auth_type text not null,
  quota_status text not null check (quota_status in ('VERIFIED','UNVERIFIED')),
  redistribution_status text not null check (redistribution_status in ('ALLOWED','UNVERIFIED','PROHIBITED')),
  availability_2025 text not null,
  known_limitations jsonb not null default '[]'::jsonb check (jsonb_typeof(known_limitations)='array'),
  verified_at timestamptz,
  state text not null default 'DRAFT' check (state in ('DRAFT','PUBLISHED','SUPERSEDED')),
  version bigint not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.dq_contracts (
  id uuid primary key default gen_random_uuid(),
  source_dataset_id uuid not null references public.source_datasets(id) on delete restrict,
  revision bigint not null check (revision > 0),
  state text not null check (state in ('DRAFT','PUBLISHED','SUPERSEDED')),
  config jsonb not null check (jsonb_typeof(config)='object'),
  config_hash bytea not null check (octet_length(config_hash)=32),
  created_by uuid references public.profiles(user_id) on delete set null,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  unique (source_dataset_id,revision)
);
create unique index dq_contracts_published_uq on public.dq_contracts(source_dataset_id) where state='PUBLISHED';

create table public.industry_taxonomy (
  id uuid primary key default gen_random_uuid(),
  taxonomy_version text not null,
  industry_id text not null,
  major_name text not null,
  middle_name text,
  minor_name text,
  valid_from date not null,
  valid_to date,
  state text not null check (state in ('DRAFT','PUBLISHED','SUPERSEDED')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (taxonomy_version,industry_id),
  check (valid_to is null or valid_to >= valid_from)
);

create table public.industry_mappings (
  id uuid primary key default gen_random_uuid(),
  taxonomy_id uuid not null references public.industry_taxonomy(id) on delete restrict,
  external_system text not null check (external_system in ('KSIC','SEMAS','SEOUL','LOCALDATA')),
  external_code text not null,
  mapping_type text not null check (mapping_type in ('EXACT','BROADER','NARROWER','MANUAL','UNMAPPED')),
  review_status text not null check (review_status in ('PENDING','APPROVED','REJECTED')),
  valid_from date not null,
  valid_to date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (taxonomy_id,external_system,external_code,valid_from),
  check (valid_to is null or valid_to >= valid_from)
);

create table public.spatial_boundaries (
  id uuid primary key default gen_random_uuid(),
  boundary_version text not null,
  boundary_type text not null check (boundary_type in ('DISTRICT','ADMIN_DONG','LEGAL_DONG','COMMERCIAL_AREA')),
  official_code text not null,
  source_snapshot_id uuid not null references public.source_snapshots(id) on delete restrict,
  source_crs text not null,
  service_crs text not null default 'EPSG:4326',
  geometry_object_key text not null,
  geometry_hash bytea not null check (octet_length(geometry_hash)=32),
  state text not null check (state in ('VALIDATING','PUBLISHED','SUPERSEDED')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (boundary_version,boundary_type,official_code)
);

create table public.store_history (
  id uuid primary key default gen_random_uuid(),
  store_hash_id bytea not null check (octet_length(store_hash_id)=32),
  source_snapshot_id uuid not null references public.source_snapshots(id) on delete restrict,
  industry_mapping_id uuid references public.industry_mappings(id) on delete restrict,
  district_code char(5),
  boundary_version text,
  licensed_at date,
  event_at date,
  event_type text check (event_type is null or event_type in ('CLOSED','CANCELLED','REVOKED','RELOCATED','TRANSFERRED','REOPENED')),
  observation_start date not null,
  observation_end date,
  left_truncated boolean not null default false,
  right_censored boolean not null default true,
  interval_censored boolean not null default false,
  source_modified_at timestamptz,
  created_at timestamptz not null default now(),
  unique (store_hash_id,source_snapshot_id),
  check (observation_end is null or observation_end >= observation_start)
);
create index store_history_scope_idx on public.store_history(district_code,industry_mapping_id,observation_start);

create table public.store_periods (
  store_history_id uuid not null references public.store_history(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  feature_snapshot_ids uuid[] not null,
  features jsonb not null check (jsonb_typeof(features)='object'),
  available_at timestamptz not null,
  parser_version text not null,
  mapping_version text not null,
  created_at timestamptz not null default now(),
  primary key (store_history_id,period_start),
  check (period_end >= period_start)
);

create table public.model_registry (
  id uuid primary key default gen_random_uuid(),
  model_key text not null,
  model_version text not null,
  evidence_grade public.evidence_grade not null,
  industry_scope jsonb not null check (jsonb_typeof(industry_scope)='array'),
  artifact_object_key text not null,
  artifact_hash bytea not null check (octet_length(artifact_hash)=32),
  training_manifest jsonb not null check (jsonb_typeof(training_manifest)='object'),
  model_card jsonb not null check (jsonb_typeof(model_card)='object'),
  state text not null check (state in ('CANDIDATE','VALIDATED','SHADOW','ACTIVE','RETIRED')),
  created_by uuid references public.profiles(user_id) on delete set null,
  approved_by uuid references public.profiles(user_id) on delete set null,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (model_key,model_version),
  check (evidence_grade <> 'A' or state in ('CANDIDATE','VALIDATED') or (approved_by is not null and approved_at is not null and state in ('SHADOW','ACTIVE','RETIRED')))
);
create unique index model_registry_active_uq on public.model_registry(model_key) where state='ACTIVE';

create table public.model_release_gates (
  id uuid primary key default gen_random_uuid(),
  model_id uuid not null references public.model_registry(id) on delete cascade,
  gate_key text not null,
  result text not null check (result in ('PASS','FAIL','UNVERIFIED')),
  metric_value numeric,
  approved_threshold numeric,
  evidence_manifest jsonb not null default '{}'::jsonb,
  checked_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (model_id,gate_key)
);

create table public.rag_chunks (
  id uuid primary key default gen_random_uuid(),
  source_snapshot_id uuid not null references public.source_snapshots(id) on delete restrict,
  page int check (page is null or page > 0),
  section text,
  content_redacted text not null,
  content_hash bytea not null check (octet_length(content_hash)=32),
  valid_from timestamptz,
  valid_to timestamptz,
  region_codes text[] not null default '{}',
  industry_ids text[] not null default '{}',
  embedding_model text not null,
  embedding_dimension int not null check (embedding_dimension > 0),
  embedding extensions.vector,
  parser_version text not null,
  created_at timestamptz not null default now(),
  unique (source_snapshot_id,content_hash),
  check (page is not null or section is not null),
  check (valid_to is null or valid_from is null or valid_to >= valid_from)
);
create index rag_chunks_snapshot_idx on public.rag_chunks(source_snapshot_id);

create table public.eligibility_decisions (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references public.cases(id) on delete cascade,
  program_record_id uuid not null references public.program_records(id) on delete restrict,
  status text not null check (status in ('ELIGIBLE_PRECHECK','CONDITIONAL','MANUAL_CHECK','CLOSED','UNKNOWN')),
  matched_rules jsonb not null default '[]'::jsonb,
  unknown_fields jsonb not null default '[]'::jsonb,
  rule_version text not null,
  source_snapshot_id uuid references public.source_snapshots(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index eligibility_decisions_case_idx on public.eligibility_decisions(case_id,created_at desc);

create table public.consultation_previews (
  id uuid primary key default gen_random_uuid(),
  consent_id uuid not null references public.consent_records(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade,
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  recipient text not null,
  selected_fields jsonb not null check (jsonb_typeof(selected_fields)='array'),
  payload_redacted jsonb not null check (jsonb_typeof(payload_redacted)='object'),
  status text not null default 'PREVIEW_ONLY' check (status in ('PREVIEW_ONLY','CANCELLED','EXPIRED')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (expires_at > created_at)
);
create index consultation_previews_user_idx on public.consultation_previews(user_id,created_at desc);

create table public.analytics_events (
  id bigint generated always as identity primary key,
  actor_pseudonym bytea check (actor_pseudonym is null or octet_length(actor_pseudonym)=32),
  event_name text not null check (event_name in ('page_view','stage_started','stage_completed','analysis_completed','analysis_blocked','document_completed','official_link_clicked','error')),
  route_name text,
  status_code int,
  latency_bucket text,
  cost_bucket text,
  properties_redacted jsonb not null default '{}'::jsonb,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  check (expires_at <= created_at + interval '365 days')
);
create index analytics_events_expiry_idx on public.analytics_events(expires_at);

create table public.document_download_audit (
  id bigint generated always as identity primary key,
  document_id uuid references public.documents(id) on delete set null,
  actor_pseudonym bytea not null check (octet_length(actor_pseudonym)=32),
  request_id uuid not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  check (expires_at <= created_at + interval '365 days')
);

create table public.admin_resource_revisions (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('SOURCE','RULE','MODEL','PROGRAM')),
  resource_key text not null check (length(resource_key) between 1 and 160),
  revision bigint not null check (revision > 0),
  state text not null check (state in ('DRAFT','PUBLISHED','SUPERSEDED')),
  payload jsonb not null check (jsonb_typeof(payload)='object'),
  payload_hash bytea not null check (octet_length(payload_hash)=32),
  reason text not null check (length(reason) between 5 and 500),
  created_by uuid not null references public.profiles(user_id) on delete restrict,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  unique (kind,resource_key,revision)
);
create unique index admin_resource_published_uq on public.admin_resource_revisions(kind,resource_key) where state='PUBLISHED';

-- Keep mutable timestamps consistent.
do $triggers$
declare t text;
begin
  foreach t in array array[
    'retention_policy','profiles','anonymous_sessions','cases','case_inputs','conversations','messages',
    'source_documents','analysis_results','cost_plans','program_records','documents','consent_records',
    'notifications','notification_settings','outbox_events','notification_suppressions','notification_deliveries',
    'privacy_requests','vendor_limits','idempotency_keys','jobs','deletion_jobs','kill_switches',
    'source_datasets','industry_taxonomy','industry_mappings','spatial_boundaries','model_registry',
    'consultation_previews'
  ] loop
    execute format('create trigger %I before update on public.%I for each row execute function public.set_updated_at()', t || '_set_updated_at', t);
  end loop;
end;
$triggers$;

-- Owner check used only by service-side repositories; browser execution is revoked below.
create function public.api_case_owned(p_case uuid, p_user uuid, p_session uuid)
returns boolean language sql stable security definer
set search_path = pg_catalog, public as $$
  select exists (
    select 1 from public.cases k
    where k.id=p_case and k.status='ACTIVE'
      and ((p_user is not null and p_session is null and k.owner_user_id=p_user)
        or (p_user is null and p_session is not null and k.anonymous_session_id=p_session))
  );
$$;

-- Atomic anonymous case claim. The API validates the raw HMAC token before invoking this service-only function.
create function public.claim_anonymous_case(p_case uuid, p_session uuid, p_user uuid)
returns boolean language plpgsql security definer
set search_path = pg_catalog, public as $$
declare claimed boolean := false;
begin
  if p_case is null or p_session is null or p_user is null then
    raise exception 'required argument missing';
  end if;
  perform 1 from public.anonymous_sessions
   where id=p_session and status='ACTIVE' and expires_at>now() for update;
  if not found then return false; end if;
  perform 1 from public.profiles where user_id=p_user;
  if not found then return false; end if;
  update public.cases
     set owner_user_id=p_user, anonymous_session_id=null, version=version+1
   where id=p_case and anonymous_session_id=p_session and owner_user_id is null and status='ACTIVE';
  claimed := found;
  if claimed then
    update public.anonymous_sessions
       set status='CLAIMED', claimed_by=p_user, token_version=token_version+1
     where id=p_session;
  end if;
  return claimed;
end;
$$;

create function public.append_message(
  p_case uuid, p_user uuid, p_session uuid, p_client_message_id uuid,
  p_content_redacted text, p_base_version bigint, p_confirmed_patch jsonb
) returns jsonb language plpgsql security definer
set search_path = pg_catalog, public as $$
declare v_conversation uuid; v_message uuid := gen_random_uuid(); v_sequence bigint; v_version bigint;
begin
  if length(coalesce(p_content_redacted,'')) not between 1 and 4000 then raise exception 'invalid content'; end if;
  if not public.api_case_owned(p_case,p_user,p_session) then return null; end if;
  select version into v_version from public.cases where id=p_case and status='ACTIVE' for update;
  if v_version <> p_base_version then raise exception 'version conflict' using errcode='40001'; end if;
  insert into public.conversations(case_id,status,retention_class)
    values(p_case,'ACTIVE','USER_UNTIL_DELETE')
    on conflict(case_id) do update set updated_at=now()
    returning id,last_sequence+1 into v_conversation,v_sequence;
  update public.conversations set last_sequence=v_sequence where id=v_conversation;
  insert into public.messages(id,conversation_id,client_message_id,role,content_redacted,content_sha256,confirmed_case_patch,retention_class,sequence)
    values(v_message,v_conversation,p_client_message_id,'USER',p_content_redacted,extensions.digest(p_content_redacted,'sha256'),p_confirmed_patch,'USER_UNTIL_DELETE',v_sequence);
  return jsonb_build_object('message_id',v_message,'conversation_id',v_conversation,'sequence',v_sequence,'case_version',v_version);
end;
$$;

create function public.create_case_with_inputs(p_case uuid,p_user uuid,p_session uuid,p_title text,p_inputs jsonb)
returns boolean language plpgsql security definer
set search_path = pg_catalog, public as $$
declare v_field text; v_value jsonb;
begin
  if ((p_user is not null)::int + (p_session is not null)::int) <> 1 or length(trim(coalesce(p_title,''))) not between 1 and 120 then raise exception 'invalid case'; end if;
  if p_user is not null and not exists(select 1 from public.profiles where user_id=p_user) then raise exception 'profile not found'; end if;
  if p_session is not null and not exists(select 1 from public.anonymous_sessions where id=p_session and status='ACTIVE' and expires_at>now()) then raise exception 'session not found'; end if;
  if jsonb_typeof(p_inputs)<>'object' or (select count(*) from jsonb_object_keys(p_inputs))<>6
     or p_inputs->>'district_code' !~ '^[0-9]{5}$'
     or (p_inputs->>'budget_krw')::bigint<0 or (p_inputs->>'equity_krw')::bigint<0
     or (p_inputs->>'equity_krw')::bigint>(p_inputs->>'budget_krw')::bigint
     or p_inputs->>'business_stage' not in ('PREPARING','OPERATING','RELOCATING','EXPANDING')
     or p_inputs->>'startup_type' not in ('NEW','ACQUISITION','FRANCHISE','INDEPENDENT') then raise exception 'invalid inputs'; end if;
  insert into public.cases(id,owner_user_id,anonymous_session_id,title,status,version) values(p_case,p_user,p_session,p_title,'ACTIVE',1);
  for v_field,v_value in select key,value from jsonb_each(p_inputs) loop
    if v_field not in ('industry_id','district_code','budget_krw','equity_krw','business_stage','startup_type') then raise exception 'invalid field'; end if;
    insert into public.case_inputs(case_id,field,value_json,source,confirmed_at) values(p_case,v_field,v_value,'FORM',now());
  end loop;
  return true;
end;
$$;

create function public.patch_case_with_inputs(p_case uuid,p_user uuid,p_session uuid,p_expected_version bigint,p_title text,p_inputs jsonb)
returns bigint language plpgsql security definer
set search_path = pg_catalog, public as $$
declare v_version bigint; v_field text; v_value jsonb;
begin
  if not public.api_case_owned(p_case,p_user,p_session) then return null; end if;
  select version into v_version from public.cases where id=p_case and status='ACTIVE' for update;
  if v_version<>p_expected_version then raise exception 'version conflict' using errcode='40001'; end if;
  if p_title is not null and length(trim(p_title)) not between 1 and 120 then raise exception 'invalid title'; end if;
  if p_inputs is not null then
    if jsonb_typeof(p_inputs)<>'object' or (select count(*) from jsonb_object_keys(p_inputs))<>6
       or p_inputs->>'district_code' !~ '^[0-9]{5}$'
       or (p_inputs->>'budget_krw')::bigint<0 or (p_inputs->>'equity_krw')::bigint<0
       or (p_inputs->>'equity_krw')::bigint>(p_inputs->>'budget_krw')::bigint then raise exception 'invalid inputs'; end if;
    for v_field,v_value in select key,value from jsonb_each(p_inputs) loop
      if v_field not in ('industry_id','district_code','budget_krw','equity_krw','business_stage','startup_type') then raise exception 'invalid field'; end if;
      insert into public.case_inputs(case_id,field,value_json,source,confirmed_at) values(p_case,v_field,v_value,'FORM',now())
      on conflict(case_id,field) do update set value_json=excluded.value_json,source='FORM',confirmed_at=excluded.confirmed_at;
    end loop;
  end if;
  update public.cases set title=coalesce(p_title,title),version=version+1 where id=p_case returning version into v_version;
  return v_version;
end;
$$;

create function public.mark_case_deleting(p_case uuid,p_user uuid,p_session uuid,p_expected_version bigint)
returns bigint language plpgsql security definer
set search_path = pg_catalog, public as $$
declare v_version bigint; v_job uuid:=gen_random_uuid();
begin
  if not public.api_case_owned(p_case,p_user,p_session) then return null; end if;
  select version into v_version from public.cases where id=p_case and status='ACTIVE' for update;
  if v_version<>p_expected_version then raise exception 'version conflict' using errcode='40001'; end if;
  update public.cases set status='DELETING',version=version+1 where id=p_case returning version into v_version;
  insert into public.deletion_jobs(id,requester_user_id,anonymous_session_id,case_id,scope,status,dedupe_key,backup_rolloff_at)
  values(v_job,p_user,p_session,p_case,jsonb_build_object('case',true,'storage',true,'vector',true,'cache',true),'QUEUED','case:'||p_case::text,now()+interval '30 days');
  insert into public.outbox_events(topic,aggregate_type,aggregate_id,payload_redacted,status,dedupe_key)
  values('CASE_DELETE','deletion_job',v_job,jsonb_build_object('deletion_job_id',v_job),'PENDING','case-delete:'||v_job::text);
  return v_version;
end;
$$;

create function public.append_message_v2(
  p_case uuid, p_user uuid, p_session uuid, p_client_message_id uuid,
  p_content_redacted text, p_base_version bigint, p_confirmed_patch jsonb, p_confirmed_inputs jsonb
) returns jsonb language plpgsql security definer
set search_path = pg_catalog, public, extensions as $$
declare v_conversation uuid; v_message uuid := gen_random_uuid(); v_sequence bigint; v_version bigint; v_field text; v_value jsonb; v_event_seq bigint := 1;
begin
  if length(coalesce(p_content_redacted,'')) not between 1 and 4000 or p_client_message_id is null then raise exception 'invalid message'; end if;
  if jsonb_typeof(coalesce(p_confirmed_patch,'[]'::jsonb)) <> 'array' or jsonb_array_length(coalesce(p_confirmed_patch,'[]'::jsonb)) > 6 then raise exception 'invalid patch'; end if;
  if jsonb_typeof(p_confirmed_inputs) <> 'object' or (select count(*) from jsonb_object_keys(p_confirmed_inputs)) <> 6 then raise exception 'invalid confirmed inputs'; end if;
  if not public.api_case_owned(p_case,p_user,p_session) then return null; end if;
  select version into v_version from public.cases where id=p_case and status='ACTIVE' for update;
  if v_version <> p_base_version then raise exception 'version conflict' using errcode='40001'; end if;
  if exists (
    select 1 from jsonb_array_elements(coalesce(p_confirmed_patch,'[]'::jsonb)) op
    where op->>'op' <> 'replace' or op->>'path' not in ('/industry_id','/district_code','/budget_krw','/equity_krw','/business_stage','/startup_type') or not (op ? 'value')
  ) then raise exception 'invalid patch operation'; end if;
  if p_confirmed_inputs->>'district_code' !~ '^[0-9]{5}$'
     or (p_confirmed_inputs->>'budget_krw')::bigint < 0
     or (p_confirmed_inputs->>'equity_krw')::bigint < 0
     or (p_confirmed_inputs->>'equity_krw')::bigint > (p_confirmed_inputs->>'budget_krw')::bigint
     or p_confirmed_inputs->>'business_stage' not in ('PREPARING','OPERATING','RELOCATING','EXPANDING')
     or p_confirmed_inputs->>'startup_type' not in ('NEW','ACQUISITION','FRANCHISE','INDEPENDENT') then
    raise exception 'invalid confirmed inputs';
  end if;
  insert into public.conversations(case_id,status,retention_class)
    values(p_case,'ACTIVE','USER_UNTIL_DELETE')
    on conflict(case_id) do update set updated_at=now()
    returning id,last_sequence+1 into v_conversation,v_sequence;
  if exists(select 1 from public.messages where conversation_id=v_conversation and client_message_id=p_client_message_id) then
    raise exception 'client message conflict' using errcode='23505';
  end if;
  if jsonb_array_length(coalesce(p_confirmed_patch,'[]'::jsonb)) > 0 then
    for v_field,v_value in select key,value from jsonb_each(p_confirmed_inputs) loop
      insert into public.case_inputs(case_id,field,value_json,source,confirmed_at)
      values(p_case,v_field,v_value,'USER',now())
      on conflict(case_id,field) do update set value_json=excluded.value_json,source='USER',confirmed_at=excluded.confirmed_at;
    end loop;
    update public.cases set version=version+1 where id=p_case returning version into v_version;
  end if;
  update public.conversations set last_sequence=v_sequence where id=v_conversation;
  insert into public.messages(id,conversation_id,client_message_id,role,content_redacted,content_sha256,confirmed_case_patch,retention_class,sequence)
    values(v_message,v_conversation,p_client_message_id,'USER',p_content_redacted,extensions.digest(p_content_redacted,'sha256'),nullif(p_confirmed_patch,'[]'::jsonb),'USER_UNTIL_DELETE',v_sequence);
  insert into public.message_stream_events(message_id,sequence,event_type,payload_redacted,expires_at)
    values(v_message,v_event_seq,'message.accepted',jsonb_build_object('conversation_id',v_conversation,'user_message_id',v_message,'case_version',v_version),now()+interval '24 hours');
  if jsonb_array_length(coalesce(p_confirmed_patch,'[]'::jsonb)) > 0 then
    v_event_seq := v_event_seq + 1;
    insert into public.message_stream_events(message_id,sequence,event_type,payload_redacted,expires_at)
      values(v_message,v_event_seq,'case.patch.confirmed',jsonb_build_object('patch',p_confirmed_patch,'case_version',v_version),now()+interval '24 hours');
  end if;
  insert into public.outbox_events(topic,aggregate_type,aggregate_id,payload_redacted,status,dedupe_key)
    values('MESSAGE_ACCEPTED','message',v_message,jsonb_build_object('case_id',p_case,'message_id',v_message),'PENDING','message:'||v_message::text);
  return jsonb_build_object('message_id',v_message,'conversation_id',v_conversation,'case_version',v_version);
end;
$$;

create function public.complete_message(
  p_case uuid, p_user uuid, p_session uuid, p_user_message uuid, p_assistant_message uuid,
  p_content_redacted text, p_model_version text, p_prompt_version text, p_generated_by text
) returns boolean language plpgsql security definer
set search_path = pg_catalog, public as $$
declare v_conversation uuid; v_message_sequence bigint; v_event_sequence bigint;
begin
  if not public.api_case_owned(p_case,p_user,p_session) then return false; end if;
  if length(coalesce(p_content_redacted,'')) not between 1 and 8000 or length(coalesce(p_model_version,'')) < 1 or length(coalesce(p_prompt_version,'')) < 1 then raise exception 'invalid completion'; end if;
  select m.conversation_id into v_conversation from public.messages m join public.conversations c on c.id=m.conversation_id
    where m.id=p_user_message and m.role='USER' and c.case_id=p_case for update of c;
  if not found then return false; end if;
  update public.conversations set last_sequence=last_sequence+1 where id=v_conversation returning last_sequence into v_message_sequence;
  insert into public.messages(id,conversation_id,role,content_redacted,content_sha256,model_version,prompt_version,finish_reason,retention_class,sequence)
    values(p_assistant_message,v_conversation,'ASSISTANT',p_content_redacted,extensions.digest(p_content_redacted,'sha256'),p_model_version,p_prompt_version,'stop','USER_UNTIL_DELETE',v_message_sequence);
  select coalesce(max(sequence),0)+1 into v_event_sequence from public.message_stream_events where message_id=p_user_message;
  insert into public.message_stream_events(message_id,sequence,event_type,payload_redacted,expires_at) values
    (p_user_message,v_event_sequence,'assistant.delta',jsonb_build_object('message_id',p_assistant_message,'delta',p_content_redacted,'generated_by',p_generated_by),now()+interval '24 hours'),
    (p_user_message,v_event_sequence+1,'message.completed',jsonb_build_object('assistant_message_id',p_assistant_message,'finish_reason','stop','usage_bucket','unavailable','model',nullif(p_model_version,'safe-fallback')),now()+interval '24 hours');
  update public.outbox_events set status='SENT' where dedupe_key='message:'||p_user_message::text and status='PENDING';
  return true;
end;
$$;

create function public.withdraw_consultation_consent(p_consent uuid,p_user uuid)
returns boolean language plpgsql security definer
set search_path = pg_catalog, public as $$
begin
  update public.consent_records set status='WITHDRAWN',withdrawn_at=coalesce(withdrawn_at,now())
   where id=p_consent and user_id=p_user and type='CONSULTATION_PREVIEW' and status in ('GRANTED','WITHDRAWN');
  if not found then return false; end if;
  update public.consultation_previews set status='CANCELLED' where consent_id=p_consent and status='PREVIEW_ONLY';
  update public.outbox_events set status='CANCELLED',payload_redacted='{}'::jsonb
   where aggregate_id=p_consent and topic like 'CONSULTATION_%' and status in ('PENDING','LEASED','FAILED');
  return true;
end;
$$;

create function public.request_anonymous_session_deletion(p_session uuid)
returns uuid language plpgsql security definer
set search_path = pg_catalog, public as $$
declare v_job uuid;
begin
  perform 1 from public.anonymous_sessions where id=p_session and status='ACTIVE' and expires_at>now() for update;
  if not found then return null; end if;
  select id into v_job from public.deletion_jobs where anonymous_session_id=p_session and status in ('QUEUED','RUNNING') limit 1;
  if found then return v_job; end if;
  v_job:=gen_random_uuid();
  update public.anonymous_sessions set status='DELETING',token_version=token_version+1 where id=p_session;
  insert into public.deletion_jobs(id,anonymous_session_id,scope,status,dedupe_key,backup_rolloff_at)
  values(v_job,p_session,jsonb_build_object('anonymous_session',true,'db',true,'storage',true,'vector',true,'cache',true),'QUEUED','anonymous:'||p_session::text,now()+interval '30 days');
  insert into public.outbox_events(topic,aggregate_type,aggregate_id,payload_redacted,status,dedupe_key)
  values('ANONYMOUS_DELETE','deletion_job',v_job,jsonb_build_object('deletion_job_id',v_job),'PENDING','anonymous-delete:'||v_job::text);
  return v_job;
end;
$$;

create function public.request_account_deletion(p_user uuid)
returns public.deletion_jobs language plpgsql security definer
set search_path = pg_catalog, public as $$
declare v_job public.deletion_jobs;
begin
  perform 1 from public.profiles where user_id=p_user for update;
  if not found then raise exception 'profile not found'; end if;
  select * into v_job from public.deletion_jobs where requester_user_id=p_user and status in ('QUEUED','RUNNING') order by created_at desc limit 1;
  if found then return v_job; end if;
  insert into public.deletion_jobs(requester_user_id,scope,status,dedupe_key,backup_rolloff_at)
  values(p_user,jsonb_build_object('account',true,'db',true,'storage',true,'vector',true,'cache',true,'notifications',true,'outbox',true),'QUEUED','account:'||p_user::text,now()+interval '30 days')
  returning * into v_job;
  insert into public.outbox_events(topic,aggregate_type,aggregate_id,payload_redacted,status,dedupe_key)
  values('ACCOUNT_DELETE','deletion_job',v_job.id,jsonb_build_object('deletion_job_id',v_job.id),'PENDING','account-delete:'||v_job.id::text);
  return v_job;
end;
$$;

create function public.admin_create_draft(p_actor uuid,p_kind text,p_resource_key text,p_payload jsonb,p_reason text)
returns public.admin_resource_revisions language plpgsql security definer
set search_path = pg_catalog, public, extensions as $$
declare v_row public.admin_resource_revisions; v_revision bigint;
begin
  if p_kind not in ('SOURCE','RULE','MODEL','PROGRAM') or length(p_resource_key) not between 1 and 160 or jsonb_typeof(p_payload)<>'object' or length(trim(p_reason))<5 then raise exception 'invalid draft'; end if;
  perform 1 from public.app_roles where user_id=p_actor and role='ADMIN' and valid_from<=now() and (valid_to is null or valid_to>now());
  if not found then raise exception 'forbidden' using errcode='42501'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_kind||':'||p_resource_key,0));
  select coalesce(max(revision),0)+1 into v_revision from public.admin_resource_revisions where kind=p_kind and resource_key=p_resource_key;
  insert into public.admin_resource_revisions(kind,resource_key,revision,state,payload,payload_hash,reason,created_by)
  values(p_kind,p_resource_key,v_revision,'DRAFT',p_payload,extensions.digest(p_payload::text,'sha256'),p_reason,p_actor) returning * into v_row;
  return v_row;
end;
$$;

create function public.admin_publish_resource(p_actor uuid,p_kind text,p_resource uuid,p_expected_hash bytea,p_reason text,p_request_id uuid)
returns public.admin_resource_revisions language plpgsql security definer
set search_path = pg_catalog, public, extensions as $$
declare v_row public.admin_resource_revisions; v_old public.admin_resource_revisions;
begin
  perform 1 from public.app_roles where user_id=p_actor and role='ADMIN' and valid_from<=now() and (valid_to is null or valid_to>now());
  if not found then raise exception 'forbidden' using errcode='42501'; end if;
  select * into v_row from public.admin_resource_revisions where id=p_resource and kind=p_kind for update;
  if not found then raise exception 'not found'; end if;
  if v_row.state<>'DRAFT' or v_row.payload_hash<>p_expected_hash then raise exception 'version conflict' using errcode='40001'; end if;
  select * into v_old from public.admin_resource_revisions where kind=v_row.kind and resource_key=v_row.resource_key and state='PUBLISHED' for update;
  if found then update public.admin_resource_revisions set state='SUPERSEDED' where id=v_old.id; end if;
  update public.admin_resource_revisions set state='PUBLISHED',published_at=now(),reason=p_reason where id=v_row.id returning * into v_row;
  insert into public.audit_events(actor_pseudonym,actor_type,action,target_type,target_id,before_hash,after_hash,reason,request_id)
  values(extensions.digest(p_actor::text,'sha256'),'USER','ADMIN_PUBLISH',lower(p_kind),p_resource,case when v_old.id is null then null else v_old.payload_hash end,v_row.payload_hash,p_reason,p_request_id);
  return v_row;
end;
$$;

create function public.admin_rollback_resource(p_actor uuid,p_kind text,p_resource uuid,p_target_revision bigint,p_reason text,p_request_id uuid)
returns public.admin_resource_revisions language plpgsql security definer
set search_path = pg_catalog, public, extensions as $$
declare v_current public.admin_resource_revisions; v_target public.admin_resource_revisions; v_new public.admin_resource_revisions; v_revision bigint;
begin
  perform 1 from public.app_roles where user_id=p_actor and role='ADMIN' and valid_from<=now() and (valid_to is null or valid_to>now());
  if not found then raise exception 'forbidden' using errcode='42501'; end if;
  select * into v_current from public.admin_resource_revisions where id=p_resource and kind=p_kind for update;
  if not found then raise exception 'not found'; end if;
  select * into v_target from public.admin_resource_revisions where kind=p_kind and resource_key=v_current.resource_key and revision=p_target_revision;
  if not found then raise exception 'target not found'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_kind||':'||v_current.resource_key,0));
  select coalesce(max(revision),0)+1 into v_revision from public.admin_resource_revisions where kind=p_kind and resource_key=v_current.resource_key;
  update public.admin_resource_revisions set state='SUPERSEDED' where kind=p_kind and resource_key=v_current.resource_key and state='PUBLISHED';
  insert into public.admin_resource_revisions(kind,resource_key,revision,state,payload,payload_hash,reason,created_by,published_at)
  values(p_kind,v_current.resource_key,v_revision,'PUBLISHED',v_target.payload,v_target.payload_hash,p_reason,p_actor,now()) returning * into v_new;
  insert into public.audit_events(actor_pseudonym,actor_type,action,target_type,target_id,before_hash,after_hash,reason,request_id)
  values(extensions.digest(p_actor::text,'sha256'),'USER','ADMIN_ROLLBACK',lower(p_kind),v_new.id,v_current.payload_hash,v_new.payload_hash,p_reason,p_request_id);
  return v_new;
end;
$$;

create function public.set_kill_switch_v2(p_actor uuid,p_name text,p_enabled boolean,p_expected_version bigint,p_reason text,p_expires_at timestamptz,p_request_id uuid)
returns public.kill_switches language plpgsql security definer
set search_path = pg_catalog, public, extensions as $$
declare v_old public.kill_switches; v_new public.kill_switches;
begin
  perform 1 from public.app_roles where user_id=p_actor and role='ADMIN' and valid_from<=now() and (valid_to is null or valid_to>now());
  if not found then raise exception 'forbidden' using errcode='42501'; end if;
  if p_name not in ('ai_explanation','individual_probability','financial_application','consultation_transfer') or length(trim(coalesce(p_reason,'')))<5 or (p_expires_at is not null and p_expires_at<=now()) then raise exception 'invalid kill switch request'; end if;
  select * into v_old from public.kill_switches where name=p_name and version=p_expected_version for update;
  if not found then raise exception 'version conflict' using errcode='40001'; end if;
  update public.kill_switches set enabled=p_enabled,reason=p_reason,expires_at=p_expires_at,version=version+1 where name=p_name returning * into v_new;
  insert into public.audit_events(actor_pseudonym,actor_type,action,target_type,before_hash,after_hash,reason,request_id)
  values(extensions.digest(p_actor::text,'sha256'),'USER','KILL_SWITCH_CHANGED','kill_switch',extensions.digest(v_old::text,'sha256'),extensions.digest(v_new::text,'sha256'),p_reason,p_request_id);
  return v_new;
end;
$$;

-- Every business table is closed to browser DB roles. FastAPI uses service_role and owner predicates.
do $rls$
declare t text;
begin
  foreach t in array array[
    'profiles','anonymous_sessions','cases','case_inputs','conversations','messages','message_citations',
    'message_stream_events','analysis_results','analysis_result_sources','source_documents','source_snapshots',
    'cost_plans','program_records','documents','consent_records','notifications','notification_settings',
    'notification_deliveries','notification_suppressions','privacy_requests','app_roles','retention_policy',
    'vendor_limits','idempotency_keys','jobs','deletion_jobs','outbox_events','audit_events','kill_switches',
    'source_datasets','dq_contracts','industry_taxonomy','industry_mappings','spatial_boundaries',
    'store_history','store_periods','model_registry','model_release_gates','rag_chunks',
    'eligibility_decisions','consultation_previews','analytics_events','document_download_audit','admin_resource_revisions'
  ] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all privileges on table public.%I from anon, authenticated',t);
  end loop;
end;
$rls$;

revoke all privileges on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;

revoke all on function public.set_updated_at() from public, anon, authenticated;
revoke all on function public.api_case_owned(uuid,uuid,uuid) from public, anon, authenticated;
revoke all on function public.claim_anonymous_case(uuid,uuid,uuid) from public, anon, authenticated;
revoke all on function public.append_message(uuid,uuid,uuid,uuid,text,bigint,jsonb) from public, anon, authenticated;
revoke all on function public.append_message_v2(uuid,uuid,uuid,uuid,text,bigint,jsonb,jsonb) from public, anon, authenticated;
revoke all on function public.create_case_with_inputs(uuid,uuid,uuid,text,jsonb) from public, anon, authenticated;
revoke all on function public.patch_case_with_inputs(uuid,uuid,uuid,bigint,text,jsonb) from public, anon, authenticated;
revoke all on function public.mark_case_deleting(uuid,uuid,uuid,bigint) from public, anon, authenticated;
revoke all on function public.complete_message(uuid,uuid,uuid,uuid,uuid,text,text,text,text) from public, anon, authenticated;
revoke all on function public.withdraw_consultation_consent(uuid,uuid) from public, anon, authenticated;
revoke all on function public.request_account_deletion(uuid) from public, anon, authenticated;
revoke all on function public.request_anonymous_session_deletion(uuid) from public, anon, authenticated;
revoke all on function public.admin_create_draft(uuid,text,text,jsonb,text) from public, anon, authenticated;
revoke all on function public.admin_publish_resource(uuid,text,uuid,bytea,text,uuid) from public, anon, authenticated;
revoke all on function public.admin_rollback_resource(uuid,text,uuid,bigint,text,uuid) from public, anon, authenticated;
revoke all on function public.set_kill_switch_v2(uuid,text,boolean,bigint,text,timestamptz,uuid) from public, anon, authenticated;
grant execute on function public.api_case_owned(uuid,uuid,uuid) to service_role;
grant execute on function public.claim_anonymous_case(uuid,uuid,uuid) to service_role;
grant execute on function public.append_message(uuid,uuid,uuid,uuid,text,bigint,jsonb) to service_role;
grant execute on function public.append_message_v2(uuid,uuid,uuid,uuid,text,bigint,jsonb,jsonb) to service_role;
grant execute on function public.create_case_with_inputs(uuid,uuid,uuid,text,jsonb) to service_role;
grant execute on function public.patch_case_with_inputs(uuid,uuid,uuid,bigint,text,jsonb) to service_role;
grant execute on function public.mark_case_deleting(uuid,uuid,uuid,bigint) to service_role;
grant execute on function public.complete_message(uuid,uuid,uuid,uuid,uuid,text,text,text,text) to service_role;
grant execute on function public.withdraw_consultation_consent(uuid,uuid) to service_role;
grant execute on function public.request_account_deletion(uuid) to service_role;
grant execute on function public.request_anonymous_session_deletion(uuid) to service_role;
grant execute on function public.admin_create_draft(uuid,text,text,jsonb,text) to service_role;
grant execute on function public.admin_publish_resource(uuid,text,uuid,bytea,text,uuid) to service_role;
grant execute on function public.admin_rollback_resource(uuid,text,uuid,bigint,text,uuid) to service_role;
grant execute on function public.set_kill_switch_v2(uuid,text,boolean,bigint,text,timestamptz,uuid) to service_role;

-- Private Storage. No browser list/read/write policy is created.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values
  ('private-documents','private-documents',false,20971520,array['application/pdf']),
  ('source-raw','source-raw',false,104857600,null),
  ('model-artifacts','model-artifacts',false,104857600,null),
  ('public-assets','public-assets',true,10485760,array['image/png','image/jpeg','image/webp','image/svg+xml','text/css'])
on conflict(id) do update set public=excluded.public,file_size_limit=excluded.file_size_limit,allowed_mime_types=excluded.allowed_mime_types;

alter table storage.objects enable row level security;
revoke all privileges on table storage.objects from anon, authenticated;
revoke all privileges on table storage.buckets from anon, authenticated;

create policy "service role manages private documents"
on storage.objects for all to service_role
using (bucket_id='private-documents')
with check (bucket_id='private-documents' and name ~ '^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}[.]pdf$');

create policy "service role manages immutable source raw"
on storage.objects for all to service_role
using (bucket_id='source-raw')
with check (bucket_id='source-raw');

create policy "service role manages model artifacts"
on storage.objects for all to service_role
using (bucket_id='model-artifacts')
with check (bucket_id='model-artifacts');

create policy "service role manages versioned public assets"
on storage.objects for all to service_role
using (bucket_id='public-assets')
with check (bucket_id='public-assets' and name ~ '^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+$' and name !~ '(^|/)[.][.]?(/|$)');

commit;
