import pytest
from app.chat_tools import ChatToolset, PlaceRegistry, _https
from app.mcp_client import MCPUnavailable


class FakeSession:
    """Records every raw call and replays canned payloads keyed by tool name."""

    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.calls = []

    async def call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if tool_name not in self.payloads:
            raise AssertionError(f"unexpected raw tool call: {tool_name}")
        payload = self.payloads[tool_name]
        if isinstance(payload, Exception):
            raise payload
        return payload


GANGNAM = {"get_address": {"documents": [{"address_name": "서울 강남구 역삼동 1", "road_address_name": "서울 강남구 테헤란로 1",
                                          "place_name": "테스트빌딩", "x": "127.03", "y": "37.50",
                                          "place_url": "https://place.map.kakao.com/1"}]},
           "get_geocode": {"documents": [{"x": "127.03", "y": "37.50", "address_name": "서울 강남구 역삼동 1",
                                          "region_1depth_name": "서울", "region_2depth_name": "강남구",
                                          "b_code": "1168010100"}]},
           "get_region_code": {"bjd_code": "1168010100", "sgg_code": "11680", "applyhome_code": "11680",
                               "sido": "서울특별시", "sigungu": "강남구"}}

SUWON = {**GANGNAM,
         "get_geocode": {"documents": [{"x": "127.02", "y": "37.26", "address_name": "경기 수원시 영통구 1",
                                        "region_1depth_name": "경기", "region_2depth_name": "수원시 영통구",
                                        "b_code": "4111700000"}]},
         "get_region_code": {"bjd_code": "4111700000", "sgg_code": "41117", "applyhome_code": "41117",
                             "sido": "경기도", "sigungu": "수원시 영통구"}}

PRESALE = {**GANGNAM,
           "search_announcement_info": {"items": [
               {"house_nm": "강남OO아파트", "pblanc_url": "https://www.applyhome.co.kr/ai/aia/1",
                "rcrit_pblanc_de": "2026-07-01", "house_manage_no": "2026000123",
                "supply_types": [{"house_ty": "84A", "supply_price_man": 120000}]}]},
           "enrich_complex_info": {"items": [{"house_manage_no": "2026000123", "kapt_code": "A13001",
                                             "kapt_da_cnt": 480, "kapt_usedate": "2029"}]}}

COMPLEX = {**GANGNAM,
           "get_complex_info": {"kapt_code": "A13001", "kapt_name": "강남OO아파트", "kapt_da_cnt": 480,
                                "kapt_usedate": "20290301", "kapt_dong_cnt": 6, "kapt_pcnt_tot": 620,
                                "source_url": "http://www.k-apt.go.kr/kaptinfo/A13001"}}

TRADES = {**GANGNAM,
          "get_complex_trades": {"items": [{"deal_ymd": "202606", "deal_amount_man": 210000,
                                            "exclu_use_ar": 84.97, "floor": 12, "trade_type": "매매"}],
                                 "source_url": "https://rt.molit.go.kr/"}}

# Covers the join's three non-trivial shapes: a match, a manage_no present upstream but absent from
# the enrichment response, and an int-vs-string key mismatch between the two payloads.
PRESALE_JOIN = {**GANGNAM,
                "search_announcement_info": {"items": [
                    {"house_nm": "A아파트", "house_manage_no": 2026000001, "pblanc_url": "https://x/1"},
                    {"house_nm": "B아파트", "house_manage_no": "2026000002", "pblanc_url": "https://x/2"},
                    {"house_nm": "C아파트", "house_manage_no": "2026000003", "pblanc_url": "https://x/3"}]},
                "enrich_complex_info": {"items": [
                    {"house_manage_no": "2026000001", "kapt_code": "A1", "kapt_da_cnt": 100},
                    {"house_manage_no": "2026000003", "kapt_code": "A3", "kapt_da_cnt": 300}]}}

# A malformed enrichment row with no house_manage_no of its own, alongside an announcement that
# also has no house_manage_no -- the exact shape that would collide on the literal key "None" if
# the join didn't filter None on both sides.
PRESALE_NONE_KEY_COLLISION = {**GANGNAM,
                              "search_announcement_info": {"items": [
                                  {"house_nm": "정상아파트", "house_manage_no": "2026000123",
                                   "pblanc_url": "https://x/1"},
                                  {"house_nm": "무번호아파트", "pblanc_url": "https://x/2"}]},
                              "enrich_complex_info": {"items": [
                                  {"house_manage_no": "2026000123", "kapt_code": "A1", "kapt_da_cnt": 480},
                                  {"kapt_code": "WRONG", "kapt_da_cnt": 9999}]}}


def toolset(payloads):
    return ChatToolset(FakeSession(payloads), PlaceRegistry())


async def test_resolving_a_seoul_place_returns_a_place_ref():
    tools = toolset(GANGNAM)
    result = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    assert result["status"] == "ok"
    assert result["district"] == "강남구"
    assert result["place_ref"].startswith("pl_")


async def test_resolving_a_place_outside_seoul_is_refused():
    result = await toolset(SUWON).run("resolve_seoul_place", {"query": "수원시 영통구"})
    assert result["status"] == "out_of_scope"
    assert "서울" in result["message"]


async def test_an_out_of_scope_place_stops_before_the_region_code_call():
    session = FakeSession(SUWON)
    await ChatToolset(session, PlaceRegistry()).run("resolve_seoul_place", {"query": "수원시 영통구"})
    assert [name for name, _ in session.calls] == ["get_address", "get_geocode"]


async def test_an_out_of_scope_place_issues_no_place_ref():
    result = await toolset(SUWON).run("resolve_seoul_place", {"query": "수원시 영통구"})
    assert "place_ref" not in result


async def test_tools_reject_an_unknown_place_ref():
    result = await toolset(GANGNAM).run("lookup_seoul_complex", {"place_ref": "pl_nope"})
    assert result["status"] == "invalid_place_ref"
    assert "resolve_seoul_place" in result["message"]


async def test_a_registry_is_scoped_to_one_turn():
    shared = FakeSession(GANGNAM)
    first = ChatToolset(shared, PlaceRegistry())
    resolved = await first.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    second = ChatToolset(shared, PlaceRegistry())
    result = await second.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "invalid_place_ref"


async def test_resolve_produces_a_kakao_citation():
    result = await toolset(GANGNAM).run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    citation = result["citations"][0]
    assert citation["source_name"] == "카카오 로컬"
    assert citation["official_url"].startswith("https://")
    assert citation["tool"] == "resolve_seoul_place"
    assert citation["collected_at"].endswith("+00:00") or citation["collected_at"].endswith("Z")


@pytest.mark.xfail(reason="도구 6종은 Task 5-6 에서 추가된다", strict=True)
async def test_every_declared_tool_has_a_schema_and_a_handler():
    tools = toolset(GANGNAM)
    names = {schema["name"] for schema in tools.schemas()}
    assert names == {"resolve_seoul_place", "lookup_seoul_presale", "lookup_seoul_complex",
                     "lookup_complex_trades", "scan_nearby_facilities", "render_location_map",
                     "get_location_map_image"}
    for name in names:
        assert tools.has_handler(name), f"{name} 에 핸들러가 없다"


async def test_an_unknown_tool_name_is_reported_not_raised():
    result = await toolset(GANGNAM).run("delete_everything", {})
    assert result["status"] == "unknown_tool"


async def test_an_mcp_failure_becomes_an_error_result_not_an_exception():
    payloads = {**GANGNAM, "get_address": MCPUnavailable("조회에 실패했습니다.")}
    result = await toolset(payloads).run("resolve_seoul_place", {"query": "역삼동"})
    assert result["status"] == "error"
    assert "실패" in result["message"]


async def test_a_non_dict_argument_payload_is_normalized_not_raised():
    result = await toolset(GANGNAM).run("resolve_seoul_place", ["not", "a", "dict"])
    assert result["status"] == "error"


async def test_an_unexpected_handler_exception_becomes_an_error_result_not_a_crash():
    tools = toolset(GANGNAM)

    async def boom(arguments):
        raise ValueError("something the handler author never anticipated")

    tools._handlers["boom"] = boom
    result = await tools.run("boom", {})
    assert result["status"] == "error"


async def test_presale_lookup_uses_the_region_code_from_the_place_ref():
    session = FakeSession(PRESALE)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    announcement_call = next(args for name, args in session.calls if name == "search_announcement_info")
    assert announcement_call["region_code"] == "11680"
    # resolve already fetched the region code; looking it up again would be a wasted round trip.
    assert [name for name, _ in session.calls].count("get_region_code") == 1


async def test_presale_lookup_cites_applyhome():
    tools = ChatToolset(FakeSession(PRESALE), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "ok"
    assert any(item["source_name"] == "청약홈" for item in result["citations"])
    assert result["items"][0]["house_nm"] == "강남OO아파트"


async def test_presale_lookup_reports_an_empty_result_rather_than_inventing_one():
    payloads = {**GANGNAM, "search_announcement_info": {"items": []}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "empty"
    assert result["items"] == []
    assert "확인" in result["message"]


async def test_presale_lookup_states_the_scope_is_the_whole_district():
    tools = ChatToolset(FakeSession(PRESALE), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert "강남구" in result["scope_note"]
    assert "전체" in result["scope_note"]
    # No distance filter is actually applied -- the note must say so, not claim one happened.
    assert "좁혀진 결과가 아닙니다" in result["scope_note"]


async def test_complex_lookup_returns_the_overview_without_touching_trades():
    session = FakeSession(COMPLEX)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "ok"
    assert result["complex"]["kapt_da_cnt"] == 480
    assert "get_complex_trades" not in [name for name, _ in session.calls]
    assert any(item["source_name"] == "K-apt" for item in result["citations"])


async def test_complex_not_found_still_cites_kapt():
    payloads = {**GANGNAM, "get_complex_info": {}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "not_found"
    assert any(item["source_name"] == "K-apt" for item in result["citations"])
    assert result["citations"][0]["official_url"].startswith("https://")


async def test_complex_citation_urls_are_upgraded_to_https():
    tools = ChatToolset(FakeSession(COMPLEX), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    for item in result["citations"]:
        assert item["official_url"].startswith("https://")


async def test_trades_lookup_cites_molit():
    tools = ChatToolset(FakeSession(TRADES), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "months": 12})
    assert result["status"] == "ok"
    assert any(item["source_name"] == "국토교통부 실거래가" for item in result["citations"])
    assert result["items"][0]["deal_amount_man"] == 210000


async def test_a_tool_failure_is_returned_as_an_error_result_not_raised():
    payloads = {**GANGNAM, "get_complex_info": MCPUnavailable("K-apt 조회에 실패했습니다.")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "error"
    assert "실패" in result["message"]


async def test_presale_enrichment_joins_by_manage_no_across_int_and_string_keys():
    tools = ChatToolset(FakeSession(PRESALE_JOIN), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    items_by_name = {item["house_nm"]: item for item in result["items"]}
    assert items_by_name["A아파트"]["complex_info"]["kapt_da_cnt"] == 100  # int upstream, str downstream
    assert items_by_name["C아파트"]["complex_info"]["kapt_da_cnt"] == 300
    assert "complex_info" not in items_by_name["B아파트"]  # present upstream, absent from enrichment


async def test_presale_enrichment_does_not_attach_an_unrelated_complex_to_an_id_less_announcement():
    # Regression test for the None-key collision: without filtering rows/items whose
    # house_manage_no is None, str(None) == "None" would let the malformed "WRONG" row match
    # 무번호아파트 even though they have nothing to do with each other.
    tools = ChatToolset(FakeSession(PRESALE_NONE_KEY_COLLISION), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    items_by_name = {item["house_nm"]: item for item in result["items"]}
    assert items_by_name["정상아파트"]["complex_info"]["kapt_da_cnt"] == 480
    assert "complex_info" not in items_by_name["무번호아파트"]


async def test_presale_enrichment_request_dedupes_a_repeated_manage_no():
    payloads = {**GANGNAM, "search_announcement_info": {"items": [
        {"house_nm": "중복1", "house_manage_no": "2026000999", "pblanc_url": "https://x/a"},
        {"house_nm": "중복2", "house_manage_no": "2026000999", "pblanc_url": "https://x/b"}]},
        "enrich_complex_info": {"items": [{"house_manage_no": "2026000999", "kapt_code": "AX", "kapt_da_cnt": 10}]}}
    session = FakeSession(payloads)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    enrich_call = next(args for name, args in session.calls if name == "enrich_complex_info")
    assert enrich_call["house_manage_nos"] == ["2026000999"]


async def test_presale_lookup_survives_an_enrichment_failure_and_keeps_the_announcements():
    payloads = {**PRESALE, "enrich_complex_info": MCPUnavailable("K-apt 보강 실패")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "ok"
    assert result["items"][0]["house_nm"] == "강남OO아파트"
    assert "complex_info" not in result["items"][0]
    assert "실패" in result["enrichment_note"]
    assert not any(item["source_name"] == "K-apt" for item in result["citations"])


async def test_presale_lookup_skips_enrichment_when_no_item_has_a_manage_no():
    payloads = {**GANGNAM, "search_announcement_info": {"items": [
        {"house_nm": "번호없음", "pblanc_url": "https://x/9"}]}}
    session = FakeSession(payloads)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "ok"
    assert "enrich_complex_info" not in [name for name, _ in session.calls]
    assert "생략" in result["enrichment_note"]


async def test_presale_lookup_collapses_citations_to_one_per_district_not_one_per_announcement():
    payloads = {**GANGNAM, "search_announcement_info": {"items": [
        {"house_nm": "1단지", "house_manage_no": "2026000001", "pblanc_url": "https://x/1"},
        {"house_nm": "2단지", "house_manage_no": "2026000002", "pblanc_url": "https://x/2"}]},
        "enrich_complex_info": {"items": []}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    applyhome_citations = [item for item in result["citations"] if item["source_name"] == "청약홈"]
    assert len(applyhome_citations) == 1


async def test_trades_lookup_reports_an_empty_result_rather_than_inventing_one():
    payloads = {**GANGNAM, "get_complex_trades": {"items": [], "source_url": "https://rt.molit.go.kr/"}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "empty"
    assert result["items"] == []
    assert any(item["source_name"] == "국토교통부 실거래가" for item in result["citations"])


async def test_trades_lookup_clamps_an_excessive_months_value():
    session = FakeSession(TRADES)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "months": 999})
    assert result["months"] == 36
    call_args = next(args for name, args in session.calls if name == "get_complex_trades")
    assert call_args["months"] == 36


async def test_trades_lookup_clamps_a_non_positive_months_value():
    tools = ChatToolset(FakeSession(TRADES), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "months": -5})
    assert result["months"] == 1


def test_https_upgrades_bare_http_and_protocol_relative_urls():
    assert _https("http://example.com/a", "https://fallback/") == "https://example.com/a"
    assert _https("//example.com/a", "https://fallback/") == "https://example.com/a"
    assert _https("https://example.com/a", "https://fallback/") == "https://example.com/a"
    assert _https("", "https://fallback/") == "https://fallback/"
