import inspect
import re

from app.chat_tools import REAL_MCP_TOOL_NAMES, TOOL_SCHEMAS, ChatToolset, PlaceRegistry, _https
from app.mcp_client import MCPToolError, MCPUnavailable

import app.chat_tools as chat_tools_module


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


# Fixture shapes below mirror the *real* presale-mcp outputSchemas (and, where none is declared,
# its own source) rather than the Kakao-documents-style shapes the original code assumed --
# captured by listing tools against a live `npx -y presale-mcp@0.1.0` process with placeholder
# credentials and, for the undeclared outputSchemas, reading the package's bundled dist/index.js.

GANGNAM = {
    "get_address": {"query": "역삼동 테스트빌딩", "results": [
        {"name": "테스트빌딩", "lat": 37.50, "lng": 127.03, "address": "서울 강남구 역삼동 1",
         "road_address": "서울 강남구 테헤란로 1", "kakao_place_id": "111", "kakao_category_name": "빌딩"}],
        "summary": {"total_found": 1}, "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}},
    "get_geocode": {"address": "서울 강남구 테헤란로 1", "lat": 37.50, "lng": 127.03,
                    "normalized_address": "서울 강남구 역삼동 1", "address_type": "road", "matched_provider": "naver",
                    "region": {"sido": "서울", "sigungu": "강남구", "eupmyeondong": "역삼동"},
                    "region_code": "1168010100", "confidence": "exact",
                    "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}},
    "get_region_code": {"query": "서울 강남구 역삼동 1", "full_code": "1168010100", "sigungu_code": "11680",
                        "sido_code": "11", "applyhome_code": "11680", "region_name": "강남구",
                        "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}},
}

SUWON = {**GANGNAM,
         "get_geocode": {"address": "경기 수원시 영통구 1", "lat": 37.26, "lng": 127.02,
                         "normalized_address": "경기 수원시 영통구 1", "address_type": "road", "matched_provider": "naver",
                         "region": {"sido": "경기", "sigungu": "수원시 영통구", "eupmyeondong": "영통동"},
                         "region_code": "4111700000", "confidence": "exact",
                         "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}}}

PRESALE = {**GANGNAM,
           "search_presale_announcements": {
               "announcements": [
                   {"announcement_id": "2026-1", "house_manage_no": "2026000123", "type": "apt",
                    "name": "강남OO아파트", "address": "서울 강남구 역삼동 100", "official_url": "http://www.applyhome.co.kr/ai/aia/1",
                    "status": "분양중"}],
               "unlocated_announcements": [],
               "summary": {"total_found": 1, "geocoded": 1, "within_radius": 1, "unlocated": 0, "by_status": {"분양중": 1}},
               "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}}}

COMPLEX = {**GANGNAM,
           "get_complex_info": {"kapt_code": "A13001", "name": "강남OO아파트", "resolved_from": "bjd_code+name",
                                "match": "exact",
                                "basic": {"build_year": 2010, "total_units": 480, "dong_count": 6},
                                "detail": None, "derived": {},
                                "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z",
                                            "data_source": "kapt_basis_info_v4", "sources": [], "note": ""}}}

TRADES = {**GANGNAM,
          "get_complex_trades": {"trade_type": "sale", "region_code": "11680", "year_month": "202606",
                                 "total_count": 1, "filtered_count": 1,
                                 "items": [{"apt_name": "강남OO아파트", "dong": "역삼동", "jibun": "100",
                                           "area_sqm": 84.97, "floor": 12, "trade_date": "2026-06-05",
                                           "price_10k": 210000}],
                                 "summary": {"sample_count": 1},
                                 "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}}}

NEARBY = {**GANGNAM,
          "search_by_nearby_category": {"center": {"lat": 37.50, "lng": 127.03}, "radius_m": 1000,
                                        "results": {"subway": [{"name": "역삼역", "lat": 37.501, "lng": 127.031,
                                                                "distance_m": 320, "distance_label": "320m",
                                                                "address": "서울 강남구", "kakao_place_id": "2",
                                                                "kakao_category_name": "지하철역"}]},
                                        "summary": {"total": 1, "by_category": {"subway": 1}},
                                        "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}},
          "search_by_nearby_keyword": {"center": {"lat": 37.50, "lng": 127.03}, "radius_m": 1000, "query": "카페",
                                       "filter_applied": None, "deduplicate_by": None,
                                       "results": [{"name": "테스트카페", "lat": 37.5001, "lng": 127.0301,
                                                   "distance_m": 80, "distance_label": "80m", "address": "서울 강남구",
                                                   "kakao_place_id": "3", "kakao_category_name": "카페"}],
                                       "summary": {"total_found": 1, "after_filter": 1, "after_dedupe": 1},
                                       "metadata": {"cache_hit": False, "collected_at": "2026-07-27T00:00:00Z"}}}

MAPS = {**GANGNAM,
        "get_static_map": {"marker_count": 1, "maptype": "basic", "warnings": [],
                           "image_base64": "ZmFrZS1wbmctYnl0ZXM=", "image_mime_type": "image/png"}}


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


async def test_resolve_reads_region_code_from_the_get_region_code_response_not_get_geocode():
    # get_region_code's real fields are full_code/sigungu_code/applyhome_code -- a place resolved
    # this way must carry those through to the district-scoped tools (lookup_seoul_complex,
    # lookup_complex_trades) via place.bjd_code/sgg_code/applyhome_code. Deleting the
    # get_region_code call (and falling back only to get_geocode's own region_code) would still
    # populate bjd_code but leave sgg_code/applyhome_code empty -- this test pins that the real
    # get_region_code call actually happened and its values landed on the resolved place.
    session = FakeSession(GANGNAM)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    place = tools.registry.get(resolved["place_ref"])
    assert place.bjd_code == "1168010100"
    assert place.sgg_code == "11680"
    assert place.applyhome_code == "11680"
    region_code_call = next(args for name, args in session.calls if name == "get_region_code")
    assert region_code_call == {"query": "서울 강남구 역삼동 1"}


async def test_every_declared_tool_has_a_schema_and_a_handler():
    tools = toolset(GANGNAM)
    names = {schema["name"] for schema in tools.schemas()}
    assert names == {"resolve_seoul_place", "lookup_seoul_presale", "lookup_seoul_complex",
                     "lookup_complex_trades", "scan_nearby_facilities", "get_location_map_image"}
    for name in names:
        assert tools.has_handler(name), f"{name} 에 핸들러가 없다"


async def test_render_location_map_was_removed_along_with_its_schema_and_handler():
    # Product decision: no embed-URL primitive exists on the real server (only get_static_map,
    # which renders an image) -- render_location_map must be gone, not merely undocumented.
    tools = toolset(GANGNAM)
    assert "render_location_map" not in {schema["name"] for schema in tools.schemas()}
    assert not tools.has_handler("render_location_map")


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


def test_https_upgrades_bare_http_and_protocol_relative_urls():
    assert _https("http://example.com/a", "https://fallback/") == "https://example.com/a"
    assert _https("//example.com/a", "https://fallback/") == "https://example.com/a"
    assert _https("https://example.com/a", "https://fallback/") == "https://example.com/a"
    assert _https("", "https://fallback/") == "https://fallback/"


# --- lookup_seoul_presale --------------------------------------------------------------------

async def test_presale_lookup_calls_the_real_search_tool_with_a_radius_km():
    session = FakeSession(PRESALE)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"], "radius_km": 3})
    call_args = next(args for name, args in session.calls if name == "search_presale_announcements")
    assert call_args == {"center_lat": 37.50, "center_lng": 127.03, "radius_km": 3}


async def test_presale_lookup_reads_the_real_announcements_field_not_items():
    tools = ChatToolset(FakeSession(PRESALE), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "ok"
    assert result["items"][0]["name"] == "강남OO아파트"
    assert any(item["source_name"] == "청약홈" for item in result["citations"])


async def test_presale_lookup_upgrades_a_bare_http_official_url_to_https():
    tools = ChatToolset(FakeSession(PRESALE), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert result["items"][0]["official_url"] == "https://www.applyhome.co.kr/ai/aia/1"


async def test_presale_lookup_reports_an_empty_result_rather_than_inventing_one():
    payloads = {**GANGNAM, "search_presale_announcements": {"announcements": [], "unlocated_announcements": [],
                                                            "summary": {"total_found": 0}, "metadata": {}}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "empty"
    assert result["items"] == []
    assert "찾지 못했습니다" in result["message"]


async def test_presale_lookup_states_the_scope_is_a_real_coordinate_radius_filter():
    # Regression test for the earlier bug: our own scope_note must describe what the server
    # actually did (geocode each announcement and keep only the ones inside radius_km), not claim
    # a filter that never ran.
    tools = ChatToolset(FakeSession(PRESALE), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"], "radius_km": 5})
    assert "반경 5km" in result["scope_note"]
    assert "좌표" in result["scope_note"]


async def test_presale_lookup_clamps_an_out_of_range_radius():
    session = FakeSession(PRESALE)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"], "radius_km": 999})
    call_args = next(args for name, args in session.calls if name == "search_presale_announcements")
    assert call_args["radius_km"] == 20


async def test_presale_lookup_collapses_citations_to_one_per_call():
    payloads = {**GANGNAM, "search_presale_announcements": {
        "announcements": [{"announcement_id": "1", "name": "1단지", "official_url": "https://x/1"},
                          {"announcement_id": "2", "name": "2단지", "official_url": "https://x/2"}],
        "unlocated_announcements": [], "summary": {"total_found": 2}, "metadata": {}}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_presale", {"place_ref": resolved["place_ref"]})
    applyhome_citations = [item for item in result["citations"] if item["source_name"] == "청약홈"]
    assert len(applyhome_citations) == 1


# --- lookup_seoul_complex ---------------------------------------------------------------------

async def test_complex_lookup_sends_bjd_code_and_complex_name_not_latitude_longitude():
    # get_complex_info's real schema has no latitude/longitude properties at all (additionalProperties
    # is not declared false on the input, but sending keys the tool doesn't know about is exactly
    # the class of bug this whole rewrite exists to fix).
    session = FakeSession(COMPLEX)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    call_args = next(args for name, args in session.calls if name == "get_complex_info")
    assert call_args == {"bjd_code": "1168010100", "complex_name": "테스트빌딩"}


async def test_complex_lookup_returns_the_overview_without_touching_trades():
    session = FakeSession(COMPLEX)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "ok"
    assert result["complex"]["basic"]["total_units"] == 480
    assert "get_complex_trades" not in [name for name, _ in session.calls]
    assert any(item["source_name"] == "K-apt" for item in result["citations"])


async def test_complex_not_found_is_reported_via_the_iserror_not_found_convention():
    # presale-mcp marks "no K-apt record" as a tool-level isError whose message embeds
    # "NOT_FOUND" (confirmed by reading its source) -- our mcp_client.call() raises MCPToolError
    # for any isError result, so this handler must specifically catch that and re-map it to
    # status=not_found rather than letting run()'s generic `except MCPUnavailable` report a bare
    # status=error.
    payloads = {**GANGNAM, "get_complex_info": MCPToolError("[NOT_FOUND] 해당 단지의 기본정보가 없음.")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "not_found"
    assert any(item["source_name"] == "K-apt" for item in result["citations"])
    assert result["citations"][0]["official_url"].startswith("https://")


async def test_complex_lookup_treats_a_non_not_found_tool_error_as_a_generic_error():
    payloads = {**GANGNAM, "get_complex_info": MCPToolError("presale-mcp 응답을 해석할 수 없습니다.")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "error"


async def test_a_tool_failure_is_returned_as_an_error_result_not_raised():
    payloads = {**GANGNAM, "get_complex_info": MCPUnavailable("K-apt 조회에 실패했습니다.")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_seoul_complex", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "error"
    assert "실패" in result["message"]


# --- lookup_complex_trades --------------------------------------------------------------------

async def test_trades_lookup_sends_a_single_year_month_via_complex_query_not_region_code():
    # complex_query and region_code are mutually exclusive in the real tool -- presale-mcp only
    # resolves complex_query when region_code is absent (confirmed by reading its source), so
    # sending both would silently discard the complex-level filter.
    session = FakeSession(TRADES)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "year_month": "202606"})
    call_args = next(args for name, args in session.calls if name == "get_complex_trades")
    assert call_args == {"complex_query": "테스트빌딩", "year_month": "202606"}


async def test_trades_lookup_defaults_the_year_month_when_none_is_given():
    session = FakeSession(TRADES)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"]})
    call_args = next(args for name, args in session.calls if name == "get_complex_trades")
    assert re.fullmatch(r"\d{6}", call_args["year_month"])


async def test_trades_lookup_falls_back_to_the_default_on_a_malformed_year_month():
    session = FakeSession(TRADES)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "year_month": "not-a-month"})
    call_args = next(args for name, args in session.calls if name == "get_complex_trades")
    assert re.fullmatch(r"\d{6}", call_args["year_month"])


async def test_trades_lookup_makes_exactly_one_raw_call_per_invocation():
    # Guards the 12-call-per-turn budget: this tool must never fan out to multiple months on its
    # own, however the model phrases its request.
    session = FakeSession(TRADES)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    session.calls.clear()
    await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"]})
    assert len([name for name, _ in session.calls if name == "get_complex_trades"]) == 1


async def test_trades_lookup_cites_molit():
    tools = ChatToolset(FakeSession(TRADES), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "year_month": "202606"})
    assert result["status"] == "ok"
    assert any(item["source_name"] == "국토교통부 실거래가" for item in result["citations"])
    assert result["items"][0]["price_10k"] == 210000


async def test_trades_lookup_reports_an_empty_result_rather_than_inventing_one():
    payloads = {**GANGNAM, "get_complex_trades": {"items": [], "trade_type": "sale"}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "year_month": "202606"})
    assert result["status"] == "empty"
    assert result["items"] == []


async def test_trades_lookup_treats_the_iserror_not_found_convention_as_empty_not_error():
    payloads = {**GANGNAM, "get_complex_trades": MCPToolError("[NOT_FOUND] 해당 지역·기간 실거래 없음.")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("lookup_complex_trades", {"place_ref": resolved["place_ref"], "year_month": "202606"})
    assert result["status"] == "empty"


# --- scan_nearby_facilities ---------------------------------------------------------------------

async def test_nearby_scan_sends_every_category_in_a_single_call():
    # search_by_nearby_category accepts the whole categories array in one call -- unlike
    # search_by_nearby_keyword, which is one query per call. Calling it once per category (as the
    # earlier code did) would waste calls against the 12-per-turn budget.
    session = FakeSession(NEARBY)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"], "categories": ["subway", "school"]})
    category_calls = [args for name, args in session.calls if name == "search_by_nearby_category"]
    assert len(category_calls) == 1
    assert category_calls[0]["categories"] == ["subway", "school"]


async def test_nearby_scan_runs_category_and_keyword_searches():
    session = FakeSession(NEARBY)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"],
                                                        "categories": ["subway"], "keywords": ["카페"]})
    assert result["status"] == "ok"
    called = [name for name, _ in session.calls]
    assert "search_by_nearby_category" in called and "search_by_nearby_keyword" in called
    assert result["by_category"]["subway"][0]["name"] == "역삼역"
    assert result["by_keyword"]["카페"][0]["name"] == "테스트카페"


async def test_nearby_scan_skips_the_search_it_was_not_asked_for():
    session = FakeSession({**GANGNAM, "search_by_nearby_category": NEARBY["search_by_nearby_category"]})
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"], "categories": ["subway"]})
    assert "search_by_nearby_keyword" not in [name for name, _ in session.calls]


async def test_nearby_scan_requires_at_least_one_target():
    tools = ChatToolset(FakeSession(GANGNAM), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "error"
    assert "카테고리" in result["message"] or "키워드" in result["message"]


async def test_nearby_scan_cites_kakao():
    tools = ChatToolset(FakeSession(NEARBY), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"], "keywords": ["카페"]})
    assert any(item["source_name"] == "카카오 로컬" and item["tool"] == "scan_nearby_facilities"
               for item in result["citations"])


async def test_nearby_scan_surfaces_an_unresolved_category_alias_rather_than_a_silent_zero():
    # resolveCategory (server-side) drops any alias it doesn't recognize and records a
    # "Unknown category: X" warning in metadata.warnings instead of erroring -- if we don't
    # surface that, "school_bogus" would look identical to a category that was checked and found
    # nothing.
    payloads = {**GANGNAM, "search_by_nearby_category": {
        "center": {"lat": 37.50, "lng": 127.03}, "radius_m": 1000, "results": {},
        "summary": {"total": 0, "by_category": {}},
        "metadata": {"cache_hit": False, "collected_at": "x", "warnings": ["Unknown category: school_bogus"]}}}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"], "categories": ["school_bogus"]})
    assert "school_bogus" in result["unresolved_categories_note"]


async def test_nearby_scan_reports_a_partial_failure_rather_than_a_clean_answer():
    payloads = {**NEARBY, "search_by_nearby_keyword": MCPUnavailable("카카오 로컬 조회 실패")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"],
                                                        "categories": ["subway"], "keywords": ["카페"]})
    # The category search succeeded, so this is still a real answer -- but the keyword search's
    # failure must be visible, not silently swallowed as "no cafes found nearby".
    assert result["status"] == "ok"
    assert result["by_category"]["subway"][0]["name"] == "역삼역"
    assert result["by_keyword"]["카페"] == []
    assert result["failed_targets"] == ["카페"]
    assert "failure_note" in result and "카페" in result["failure_note"]


async def test_nearby_scan_reports_total_failure_as_error_not_as_a_confident_empty():
    payloads = {**GANGNAM, "search_by_nearby_category": MCPUnavailable("카카오 로컬 조회 실패")}
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"], "categories": ["subway"]})
    assert result["status"] == "error"
    assert result["failed_targets"] == ["subway"]


async def test_nearby_scan_clamps_an_excessive_radius():
    session = FakeSession(NEARBY)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"],
                                                        "categories": ["subway"], "radius_m": 999999})
    assert result["radius_m"] == 20000
    call_args = next(args for name, args in session.calls if name == "search_by_nearby_category")
    assert call_args["radius_m"] == 20000


async def test_nearby_scan_clamps_a_non_positive_radius():
    tools = ChatToolset(FakeSession(NEARBY), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("scan_nearby_facilities", {"place_ref": resolved["place_ref"],
                                                        "categories": ["subway"], "radius_m": -5})
    assert result["radius_m"] == 1


async def test_scan_nearby_schema_uses_the_real_alias_vocabulary_not_kakao_raw_codes():
    schema = next(schema for schema in TOOL_SCHEMAS if schema["name"] == "scan_nearby_facilities")
    description = schema["description"]
    # These nine ids are confirmed against presale-mcp's own bundled alias table (dist/index.js'
    # embedded categories_default YAML), not invented. A raw Kakao category-group code like "SW8"
    # or "MT1" is exactly what the earlier, wrong description told the model to send.
    for alias in ("school_elementary", "school_middle", "school_high", "school", "subway",
                 "mart_large", "hospital", "pharmacy", "park"):
        assert alias in description
    assert "SW8" not in description
    assert "MT1" not in description


# --- get_location_map_image --------------------------------------------------------------------

async def test_map_image_tool_sends_a_marker_not_latitude_longitude():
    session = FakeSession(MAPS)
    tools = ChatToolset(session, PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    await tools.run("get_location_map_image", {"place_ref": resolved["place_ref"]})
    call_args = next(args for name, args in session.calls if name == "get_static_map")
    assert call_args["markers"] == [{"lat": 37.50, "lng": 127.03}]
    assert "latitude" not in call_args and "longitude" not in call_args


async def test_map_image_tool_builds_a_data_url_from_the_returned_image_content():
    # get_static_map has no url/image_url field anywhere in its declared outputSchema -- the image
    # arrives as a separate base64 MCP ImageContent block (confirmed by reading presale-mcp's own
    # source), which mcp_client._unwrap folds into image_base64/image_mime_type. This handler must
    # build the image_url from those two fields, not read a url key that does not exist upstream.
    tools = ChatToolset(FakeSession(MAPS), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("get_location_map_image", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "ok"
    assert result["image_url"] == "data:image/png;base64,ZmFrZS1wbmctYnl0ZXM="


async def test_map_image_tool_reports_a_missing_image_rather_than_fabricating_one():
    tools = ChatToolset(FakeSession({**GANGNAM, "get_static_map": {"marker_count": 0, "maptype": "basic",
                                                                   "warnings": ["no image"]}}), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    result = await tools.run("get_location_map_image", {"place_ref": resolved["place_ref"]})
    assert result["status"] == "empty"
    assert "image_url" not in result
    # Product rule: every data surface carries provenance, even an empty branch.
    assert result["citations"]
    assert result["citations"][0]["source_name"] == "네이버 지도"


async def test_map_tool_schema_never_lets_the_model_supply_a_coordinate():
    # Product rule 2: the model must never supply a coordinate. A `markers`/`center` (or bare
    # latitude/longitude) parameter on get_location_map_image's or scan_nearby_facilities'
    # *schema* would be exactly that -- so its absence here is a safety property, not an
    # incidental gap.
    for schema in TOOL_SCHEMAS:
        if schema["name"] in ("get_location_map_image", "scan_nearby_facilities"):
            props = schema["parameters"]["properties"]
            assert "markers" not in props and "center" not in props
            assert "latitude" not in props and "longitude" not in props


# --- the contract test: every raw tool name we call must exist on the real server ---------------

def test_every_raw_tool_call_targets_a_name_the_server_actually_has():
    """Pins the class of bug this whole rewrite was written to fix: chat_tools.py was calling raw
    tool names (search_announcement_info, enrich_complex_info, get_map_embed_url) that do not
    exist on presale-mcp at all, and others (get_region_code, get_complex_trades, ...) with wrong
    parameter names -- caught only by a live check against real credentials, not by the 191 tests
    that existed at the time (they all used a fake MCP session that accepted whatever name and
    shape was asked of it).

    This can't reach the network, so it can't confirm parameter *shapes* -- but it can pin the
    *tool names* chat_tools.py's source actually calls against REAL_MCP_TOOL_NAMES (see that
    constant's docstring for how it was captured and how to regenerate it). A rename or typo on
    either side changes the extracted set and fails this test immediately, instead of failing
    silently in production against real credentials the way this bug originally did.
    """
    source = inspect.getsource(chat_tools_module)
    called = set(re.findall(r'self\.session\.call\(\s*"([a-zA-Z_]+)"', source))
    assert called, "no self.session.call(...) call sites were found -- did the pattern or the code move?"
    unknown = called - REAL_MCP_TOOL_NAMES
    assert not unknown, f"chat_tools.py calls raw tool name(s) presale-mcp does not expose: {unknown}"


# --- 업스트림이 실패를 성공으로 포장하는 경우 -------------------------------------------------
# presale-mcp 는 청약홈이 401 을 돌려줘도 도구 호출 자체는 성공으로 처리하고, 빈 목록과 함께
# metadata.warnings 에만 실패를 남긴다. 실측으로 확인한 형태 그대로를 픽스처로 쓴다.

# warnings[0] is the fixed best-effort advisory presale-mcp prepends to EVERY coordinate/radius
# search (dist/index.js bestEffortRadius) -- the only call shape lookup_seoul_presale uses. The
# real failure message comes after it. An earlier version of this fixture listed only the failure,
# which let a bug through: _provider_failure returned warnings[0] and the user got the
# permanently-true disclaimer instead of the 401.
BEST_EFFORT_ADVISORY = ("Coordinate/radius ApplyHome search is best-effort because ApplyHome does "
                        "not support radius search; boundary legal-dong omissions are possible.")

FAILED_PRESALE = {**GANGNAM, "search_presale_announcements": {
    "announcements": [], "unlocated_announcements": [], "summary": {"total_found": 0},
    "metadata": {"provider_query_count": 1, "provider_query_failed_count": 1,
                 "provider_query_timeout_count": 0,
                 "warnings": [BEST_EFFORT_ADVISORY, "ApplyHome APT API failed: HTTP 401"]}}}

TRUNCATED_NEARBY = {**GANGNAM, "search_by_nearby_keyword": {
    "results": [{"place_name": f"카페{i}"} for i in range(45)],
    "metadata": {"warnings": ["Kakao Local API returned the maximum 45 results for at least one "
                              "query; additional farther results may have been truncated."]}}}


async def _resolved(payloads):
    tools = ChatToolset(FakeSession(payloads), PlaceRegistry())
    resolved = await tools.run("resolve_seoul_place", {"query": "역삼동 테스트빌딩"})
    return tools, resolved["place_ref"]


async def test_a_failed_presale_query_is_an_error_not_an_empty_result():
    """Reading only `announcements` would report "no announcements here" for a query that never
    reached ApplyHome. Deleting the _provider_failure check makes this fail with status=empty --
    which is the fabrication this test exists to prevent."""
    tools, ref = await _resolved(FAILED_PRESALE)
    result = await tools.run("lookup_seoul_presale", {"place_ref": ref})
    assert result["status"] == "error"
    # The real reason must survive, not just the advisory that precedes it in warnings.
    assert "401" in result["message"]
    assert "확인하지 못했다" in result["message"]
    assert result["citations"]


async def test_a_genuinely_empty_presale_query_is_still_empty():
    """The failure check must not swallow a real zero-row answer."""
    clean = {**GANGNAM, "search_presale_announcements": {
        "announcements": [], "summary": {"total_found": 0},
        "metadata": {"provider_query_count": 1, "provider_query_failed_count": 0, "warnings": []}}}
    tools, ref = await _resolved(clean)
    result = await tools.run("lookup_seoul_presale", {"place_ref": ref})
    assert result["status"] == "empty"


async def test_a_truncated_nearby_search_says_the_list_may_be_incomplete():
    tools, ref = await _resolved(TRUNCATED_NEARBY)
    result = await tools.run("scan_nearby_facilities", {"place_ref": ref, "keywords": ["카페"]})
    assert result["status"] == "ok"
    assert len(result["by_keyword"]["카페"]) == 45
    assert "truncated" in result["completeness_note"]


async def test_an_untruncated_nearby_search_has_no_completeness_note():
    tools, ref = await _resolved(NEARBY)
    result = await tools.run("scan_nearby_facilities", {"place_ref": ref, "keywords": ["카페"]})
    assert "completeness_note" not in result


async def test_a_string_serialized_count_is_still_read_as_a_failure():
    """A count that arrives as "1" rather than 1 must still be understood. This exercises the
    coercion path only -- int("1") parses fine, so it does NOT prove the fail-closed branch."""
    drifted = {**GANGNAM, "search_presale_announcements": {
        "announcements": [], "summary": {"total_found": 0},
        "metadata": {"provider_query_failed_count": "1", "warnings": ["ApplyHome APT API failed: HTTP 401"]}}}
    tools, ref = await _resolved(drifted)
    result = await tools.run("lookup_seoul_presale", {"place_ref": ref})
    assert result["status"] == "error"


async def test_an_unreadable_count_fails_closed():
    """The fail-closed branch: a count int() cannot parse at all must be treated as a possible
    failure, not waved through as a clean zero. Flipping _positive_count's except to return False
    makes this fail -- reporting `empty`, i.e. claiming there are no announcements when the code
    could not tell whether the query even ran."""
    unreadable = {**GANGNAM, "search_presale_announcements": {
        "announcements": [], "summary": {"total_found": 0},
        "metadata": {"provider_query_failed_count": {"unexpected": "shape"}, "warnings": []}}}
    tools, ref = await _resolved(unreadable)
    result = await tools.run("lookup_seoul_presale", {"place_ref": ref})
    assert result["status"] == "error"
    assert "확인하지 못했다" in result["message"]
