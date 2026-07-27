-- 시연용 매물. 세션 스코프가 아닌 공용 참조 데이터이므로 익명 읽기를 허용한다.
create table public.listings (
  id text primary key,
  district text not null,
  name text not null,
  address text not null,
  latitude double precision not null,
  longitude double precision not null,
  listing_kind text not null default 'DEMO_SYNTHETIC',
  deposit_krw bigint not null check(deposit_krw >= 0),
  monthly_rent_krw bigint not null check(monthly_rent_krw > 0),
  maintenance_fee_krw bigint check(maintenance_fee_krw >= 0),
  area_m2 double precision not null check(area_m2 > 0),
  floor int not null,
  created_at timestamptz not null default now(),
  -- 라벨을 DB 층에서도 강제한다. 실제 매물이 생기면 이 제약을 넓힌다.
  constraint listings_kind_is_demo check (listing_kind = 'DEMO_SYNTHETIC')
);

create index listings_district_rent_idx on public.listings(district, monthly_rent_krw);

alter table public.listings enable row level security;

-- 읽기는 공개, 쓰기는 service role만. service role은 RLS를 우회하므로 정책을 따로 두지 않는다.
create policy listings_public_read on public.listings for select to anon, authenticated using (true);
