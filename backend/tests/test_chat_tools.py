import pytest
from app.chat_tools import ChatToolset, PlaceRegistry
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
