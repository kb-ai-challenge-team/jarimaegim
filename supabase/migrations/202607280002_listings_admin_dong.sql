-- 매물에 행정동을 붙인다. 서울시 우리마을가게 상권분석서비스와 조인하기 위한 키다.
--
-- 임대 조건은 시연용 생성 데이터지만 이 열은 실측이다 — Kakao Local 역지오코딩이
-- 좌표에서 확인한 행정동이고, 코드는 상권분석서비스의 ADSTRD_CD 와 같은 8자리 체계다.
-- 두 데이터셋이 이 열 하나로만 만나므로 값이 없으면 상권 축이 꺼진 채 매물만 표시된다.
alter table public.listings
  add column if not exists admin_dong text,
  add column if not exists admin_dong_code text;

comment on column public.listings.admin_dong_code is
  '서울시 상권분석서비스 ADSTRD_CD 와 동일한 8자리 행정동 코드. Kakao coord2regioncode 의 10자리 H 코드 앞 8자리와 일치한다.';

-- 상권 조회는 항상 행정동 코드로 들어온다.
create index if not exists listings_admin_dong_code_idx on public.listings(admin_dong_code);
