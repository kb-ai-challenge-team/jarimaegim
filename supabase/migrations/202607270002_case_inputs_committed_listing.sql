-- 확정한 시연 매물 ID를 케이스 입력값으로 저장해 PDF 초안이 매물 라벨을 함께 실어 나를 수 있게 한다.
alter table public.case_inputs drop constraint case_inputs_field_check;
alter table public.case_inputs add constraint case_inputs_field_check
  check(field in ('industry','district','budget_krw','equity_krw','business_stage','startup_type','priority','committed_listing_id'));
