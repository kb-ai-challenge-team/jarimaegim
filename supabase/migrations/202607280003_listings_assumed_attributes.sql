-- 시연용 매물의 부가 속성. **전부 가정값이며 실측 출처가 없다.**
--
-- 개별 상가의 권리금·전용면적·준공년도·주차·전면 폭을 공개하는 원천은 존재하지 않는다.
-- 보증금·관리비·층과 같은 취급이다 — 생성 규칙은 pipeline/lib/attribute-constants.mjs 한
-- 곳에 있고, 화면과 provenance 가 '가정값'이라고 밝힌다.
--
-- 이 열들은 근거등급을 올리지 않는다. 등급 B는 서울시 상권분석서비스의 실측 집계
-- (data/trade-area.seoul.json) 에서만 나온다. 여기 값은 매물 카드와 필요자금 계산에만 쓰인다.
alter table public.listings
  add column if not exists key_money_krw bigint check(key_money_krw >= 0),
  add column if not exists exclusive_area_m2 double precision check(exclusive_area_m2 > 0),
  add column if not exists built_year int check(built_year between 1900 and 2100),
  add column if not exists parking_slots int check(parking_slots >= 0),
  add column if not exists corner boolean,
  add column if not exists elevator boolean,
  add column if not exists floors_total int check(floors_total >= 1),
  add column if not exists frontage_m double precision check(frontage_m > 0),
  add column if not exists available_from date;

comment on column public.listings.key_money_krw is
  '가정값. 실측 출처 없음. 월세 배수로 생성하며 일부는 무권리(0). 필요자금 계산에 합산된다.';
comment on column public.listings.exclusive_area_m2 is
  '가정값. 계약면적 대비 전용률을 가정해 생성. area_m2 를 넘을 수 없다.';

-- 전용면적이 계약면적을 넘거나 층이 총층수를 넘는 행은 생성기 버그다. DB 층에서도 막는다.
alter table public.listings
  drop constraint if exists listings_exclusive_area_within_contract;
alter table public.listings
  add constraint listings_exclusive_area_within_contract
  check (exclusive_area_m2 is null or exclusive_area_m2 <= area_m2);

alter table public.listings
  drop constraint if exists listings_floor_within_building;
alter table public.listings
  add constraint listings_floor_within_building
  check (floors_total is null or floor <= floors_total);
