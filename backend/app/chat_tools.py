from __future__ import annotations
import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from .mcp_client import MCPToolError, MCPUnavailable

logger = logging.getLogger(__name__)

SEOUL_DISTRICTS = {"종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구",
                   "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구",
                   "관악구", "서초구", "강남구", "송파구", "강동구"}

OUT_OF_SCOPE_MESSAGE = "자리매김은 서울 25개 자치구만 다룹니다. 이 지역은 분석 범위 밖입니다."

# The ten raw tool names presale-mcp@0.1.0 actually exposes -- captured by opening a real MCP
# ClientSession against `npx -y presale-mcp@0.1.0` and reading session.list_tools(). Fake
# placeholder values for KAKAO_REST_API_KEY / NAVER_MAPS_CLIENT_ID / NAVER_MAPS_CLIENT_SECRET /
# DATA_GO_KR_SERVICE_KEY are enough for the handshake and tools/list -- no real credentials
# needed. See test_every_raw_tool_call_targets_a_name_the_server_actually_has below: this is the
# regression test this project's post-mortem asked for, pinning the contract so a future rename
# on either side is caught here instead of failing silently against production credentials.
#
# To regenerate: spawn the same subprocess with `mcp.client.stdio.stdio_client` +
# `mcp.ClientSession`, await `session.initialize()` then `session.list_tools()`, and diff the
# returned tool names against this set.
REAL_MCP_TOOL_NAMES = frozenset({
    "get_address", "get_geocode", "get_region_code",
    "search_by_nearby_category", "search_by_nearby_keyword",
    "search_presale_announcements", "get_announcement_detail",
    "get_complex_info", "get_complex_trades", "get_static_map",
})

# Status vocabulary every handler's result dict draws from. chat_stream.py's function-calling
# loop and the model both read this field, so it's a contract -- declared once here rather than
# letting each new handler re-derive it from scattered return statements.
#
#   ok               -- the lookup succeeded and produced the data asked for.
#   out_of_scope     -- resolved to a real place, but outside Seoul's 25 자치구; refused by policy,
#                        not a data failure.
#   invalid_place_ref -- the model passed a place_ref this turn's registry never issued (wrong
#                        turn, typo, or it skipped resolve_seoul_place).
#   not_found        -- a *single-entity* lookup succeeded and that entity genuinely doesn't exist
#                        (e.g. resolve_seoul_place found no address at all for the query).
#   empty            -- a *list-returning* lookup succeeded and legitimately returned zero rows
#                        (e.g. scan_nearby_facilities with nothing nearby). Deliberately kept
#                        distinct from not_found: "this search matched nothing" and "this single
#                        thing doesn't exist" are different facts, and collapsing them would force
#                        the model (and whoever reads the message) to guess which one happened.
#   error            -- we could not get an answer at all: MCP transport/timeout failure, a
#                        malformed upstream payload, or an unexpected internal exception.
#   unknown_tool     -- the model asked for a tool name ChatToolset doesn't register.
#   not_implemented  -- reserved; must not appear from a shipped handler.
TOOL_STATUSES = frozenset({"ok", "out_of_scope", "invalid_place_ref", "not_found", "empty",
                           "error", "unknown_tool", "not_implemented"})


class Place:
    """A coordinate the model is never allowed to see or invent."""

    def __init__(self, ref: str, name: str, address: str, latitude: float, longitude: float,
                 district: str, bjd_code: str, sgg_code: str, applyhome_code: str):
        self.ref, self.name, self.address = ref, name, address
        self.latitude, self.longitude, self.district = latitude, longitude, district
        self.bjd_code, self.sgg_code, self.applyhome_code = bjd_code, sgg_code, applyhome_code


class PlaceRegistry:
    """Scoped to a single turn. A ref from another turn resolves to nothing by construction.

    Refs are a monotonic counter, not random tokens: the security property this registry relies
    on is membership (`get()` only ever returns a Place that *this instance's* `issue()` created),
    not unguessability of the ref string -- a fresh registry per turn already makes a ref from any
    other turn resolve to nothing, guessed or not. A counter is simpler and gives deterministic
    refs in tests and logs for no loss of safety.
    """

    def __init__(self):
        self._places: dict[str, Place] = {}
        self._next_id = 1

    def issue(self, **fields) -> Place:
        ref = f"pl_{self._next_id}"
        self._next_id += 1
        place = Place(ref=ref, **fields)
        self._places[ref] = place
        return place

    def get(self, ref: str | None) -> Place | None:
        return self._places.get(ref) if ref else None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def citation(title: str, official_url: str, source_name: str, tool: str) -> dict[str, str]:
    return {"title": title, "official_url": official_url, "source_name": source_name,
            "collected_at": _now(), "tool": tool}


def _https(url: str, fallback: str) -> str:
    """Upgrades an insecure absolute URL -- bare `http://...` or protocol-relative `//...` -- to
    https. Returns `fallback` when `url` is empty, and otherwise passes anything else through
    unchanged: already-`https://` URLs, and a schemeless string like `www.host/path` that this
    function can't reliably tell apart from a relative path, so it doesn't guess."""
    if not url:
        return fallback
    if url.startswith("http://"):
        return "https://" + url.removeprefix("http://")
    if url.startswith("//"):
        return "https:" + url
    return url


def _list_field(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Every real list-returning tool uses a *different* field name for its rows --
    `results` (get_address, search_by_nearby_keyword), `items` (get_complex_trades),
    `announcements` (search_presale_announcements). There is no single `documents`/`items`
    convention shared across presale-mcp's tools; that was an assumption the original
    (README-driven, not schema-verified) code made and it does not hold. Confirmed by reading
    each tool's declared outputSchema (or, where none is declared, presale-mcp's own source)."""
    value = payload.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _first_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    """get_address's real outputSchema returns `{"results": [...]}`, never a Kakao-style
    `{"documents": [...]}` envelope, despite both wire APIs it wraps historically using
    `documents`. Confirmed against the live server's tools/list, not assumed from the README."""
    results = _list_field(payload, "results")
    return results[0] if results else None


def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _default_year_month() -> str:
    """get_complex_trades is strictly per-month (a required YYYYMM, not a window) and
    chat_stream.py caps a turn at 12 raw MCP calls total -- fetching even a modest multi-month
    history in one tool invocation would burn most or all of that budget on a single tool. Rather
    than silently making several calls internally, this tool makes exactly one call per
    invocation and lets the model ask again for another month if it wants a trend (each such call
    is then charged normally against the per-turn budget, like any other tool call). The default
    month, when the model doesn't name one, is two months before the current one: MOLIT trade
    reporting lags real transactions by roughly a month, so "last calendar month" is often still
    sparsely populated."""
    now = datetime.now(UTC)
    month = now.month - 2
    year = now.year
    if month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}{month:02d}"


class PlaceRefError(Exception):
    """The model passed a place_ref this turn's registry never issued."""


class ChatToolset:
    """Wraps presale-mcp's raw tools into the six product tools the model is allowed to see.

    `render_location_map` (an embed-URL tool) was removed: presale-mcp has no embed-URL
    primitive -- only `get_static_map`, which renders a static image, backs `get_location_map_image`.
    """

    def __init__(self, session, registry: PlaceRegistry):
        self.session = session
        self.registry = registry
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            "resolve_seoul_place": self._resolve_seoul_place,
            "lookup_seoul_presale": self._lookup_seoul_presale,
            "lookup_seoul_complex": self._lookup_seoul_complex,
            "lookup_complex_trades": self._lookup_complex_trades,
            "scan_nearby_facilities": self._scan_nearby_facilities,
            "get_location_map_image": self._get_location_map_image,
        }

    def has_handler(self, name: str) -> bool:
        return name in self._handlers

    def schemas(self) -> list[dict[str, Any]]:
        return list(TOOL_SCHEMAS)

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(name)
        if handler is None:
            return {"status": "unknown_tool", "message": f"{name} 은(는) 사용할 수 없는 도구입니다."}
        # Tool arguments originate from JSON the model emitted -- normalize by type, not
        # truthiness. A truthy non-dict (e.g. a list) would otherwise sail past this check and
        # blow up on the first `.get()` a handler calls.
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            return await handler(arguments)
        except PlaceRefError as exc:
            return {"status": "invalid_place_ref", "message": str(exc)}
        except MCPUnavailable as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            # Containment boundary of last resort: an argument shape none of the handlers
            # anticipated, or a bug in one of them, must not escape into the function-calling
            # loop as a raw exception. Log the tool name and exception type only, never
            # `arguments`, which can carry user-entered text. Deliberately `Exception`, not
            # `BaseException`: a genuine CancelledError must still propagate.
            logger.warning("chat tool 처리 실패: tool=%s error=%s", name, type(exc).__name__)
            return {"status": "error", "message": f"{name} 처리 중 오류가 발생했습니다."}

    def _require_place(self, arguments: dict[str, Any]) -> Place:
        """Raises PlaceRefError rather than returning a (place, error) pair -- that shape let a
        handler use `place` while it was still None if it forgot the check. Raising makes the
        mistake impossible: a handler either gets a real Place back or never reaches its own body."""
        place = self.registry.get(arguments.get("place_ref"))
        if place is None:
            raise PlaceRefError("먼저 resolve_seoul_place 로 위치를 확인한 뒤 그 place_ref 를 사용하세요.")
        return place

    async def _resolve_seoul_place(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = (arguments.get("query") or "").strip()
        if not query:
            return {"status": "error", "message": "찾을 지명이나 주소가 비어 있습니다."}

        address_payload = await self.session.call("get_address", {"query": query})
        candidate = _first_result(address_payload)
        if candidate is None:
            return {"status": "not_found", "message": f"'{query}' 에 해당하는 공식 주소를 찾지 못했습니다."}

        address_for_geocode = candidate.get("road_address") or candidate.get("address") or query
        geo_payload = await self.session.call("get_geocode", {"address": address_for_geocode})
        # get_geocode's real outputSchema is a single flat object -- {address, lat, lng,
        # normalized_address, region: {...}, region_code, ...} -- never a documents/results list,
        # so there is no "first item" to pick here; the payload itself is the one answer.
        latitude, longitude = geo_payload.get("lat"), geo_payload.get("lng")
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            return {"status": "not_found", "message": f"'{address_for_geocode}' 의 좌표를 확인하지 못했습니다."}

        region = geo_payload.get("region")
        region = region if isinstance(region, dict) else {}
        district = (region.get("sigungu") or "").strip()
        # Assumes get_geocode's region.sigungu is always the bare 자치구 name (e.g. "강남구"),
        # never prefixed with 시/도. If that assumption ever drifts, the value simply won't match
        # anything in SEOUL_DISTRICTS and the guard fails closed (out_of_scope), never open.
        # Refuse before spending a get_region_code call on a place we will not serve.
        if district not in SEOUL_DISTRICTS:
            return {"status": "out_of_scope", "message": OUT_OF_SCOPE_MESSAGE,
                    "detected_region": district or "확인 불가"}

        region_query = geo_payload.get("normalized_address") or geo_payload.get("address") or address_for_geocode
        region_payload = await self.session.call("get_region_code", {"query": region_query})
        place = self.registry.issue(
            name=candidate.get("name") or address_for_geocode,
            address=geo_payload.get("normalized_address") or geo_payload.get("address") or address_for_geocode,
            latitude=float(latitude), longitude=float(longitude), district=district,
            # get_region_code's real response fields are full_code/sigungu_code, not
            # bjd_code/sgg_code -- kept under these attribute names on Place because that's still
            # what they *are* (법정동코드/시군구코드); only presale-mcp's wire field names differ.
            # get_geocode's own `region_code` is the documented fallback source for bjd_code per
            # get_complex_info's own schema description ("get_geocode의 region_code에서 얻을 수 있음").
            bjd_code=str(region_payload.get("full_code") or geo_payload.get("region_code") or ""),
            sgg_code=str(region_payload.get("sigungu_code") or ""),
            applyhome_code=str(region_payload.get("applyhome_code") or ""))
        return {"status": "ok", "place_ref": place.ref, "name": place.name, "address": place.address,
                "district": place.district,
                # get_address's real result items carry no place_url/deep-link field at all
                # (confirmed against its outputSchema) -- unlike the raw Kakao Local API this tool
                # wraps, so the citation points at the general Kakao Local map, not a specific
                # listing page.
                "citations": [citation(f"카카오 로컬 장소 — {place.name}", "https://map.kakao.com/",
                                       "카카오 로컬", "resolve_seoul_place")]}

    async def _lookup_seoul_presale(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        radius_km = _clamp_int(arguments.get("radius_km"), default=5, low=1, high=20)
        payload = await self.session.call("search_presale_announcements",
                                          {"center_lat": place.latitude, "center_lng": place.longitude,
                                           "radius_km": radius_km})
        # search_presale_announcements' real outputSchema key is `announcements`, not `items` --
        # ApplyHome has no native radius search, so presale-mcp samples nearby legal-dong
        # addresses, geocodes each announcement's own address with Naver, and keeps only the ones
        # within radius_km -- a real, working distance filter (confirmed by reading presale-mcp's
        # own source, src/tools/presale-announcements.ts's geocodeAndFilterByRadius), unlike an
        # earlier version of this tool whose radius_m parameter was removed because it claimed to
        # filter and did not.
        announcements = _list_field(payload, "announcements")
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        unlocated = summary.get("unlocated") or 0
        scope_note = (f"{place.name} 반경 {radius_km}km, 최근 24개월 청약홈 분양공고입니다. 각 공고 주소를 좌표로 "
                      f"환산해 반경 안에 든 것만 남긴 결과이며(ApplyHome 자체는 반경 검색을 지원하지 않아 이 필터링은 "
                      f"presale-mcp가 수행합니다), 주소를 좌표로 바꾸지 못한 공고는 제외됩니다"
                      + (f" ({unlocated}건 제외)." if unlocated else "."))
        applyhome_citation = citation(f"청약홈 분양공고 — {place.name} 반경 {radius_km}km",
                                      "https://www.applyhome.co.kr/", "청약홈", "lookup_seoul_presale")
        if not announcements:
            return {"status": "empty", "items": [], "scope_note": scope_note,
                    "message": f"{place.name} 반경 {radius_km}km 안에서 분양공고를 찾지 못했습니다. 청약홈에서 직접 확인해 주세요.",
                    "citations": [applyhome_citation]}

        # Build new dicts rather than mutating the announcement in place: this dict came straight
        # out of the MCP payload, and nothing guarantees that payload is a private, freshly
        # allocated object nothing else holds a reference to.
        items = [{**item, "official_url": _https(item["official_url"], item["official_url"])}
                 if item.get("official_url") else item for item in announcements]
        return {"status": "ok", "items": items, "scope_note": scope_note, "citations": [applyhome_citation]}

    async def _lookup_seoul_complex(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        not_found_result = {"status": "not_found", "complex": None,
                             "message": f"{place.name} 의 K-apt 단지 정보를 찾지 못했습니다. 아파트 단지가 아닐 수 있습니다.",
                             "citations": [citation("K-apt 단지 검색", "https://www.k-apt.go.kr/",
                                                    "K-apt", "lookup_seoul_complex")]}
        try:
            payload = await self.session.call("get_complex_info",
                                              {"bjd_code": place.bjd_code, "complex_name": place.name})
        except MCPToolError as exc:
            # presale-mcp marks "no K-apt record for this complex" as a tool-level isError whose
            # message embeds "NOT_FOUND" (confirmed by reading its source: get_complex_info's
            # registration wraps every result, success or not, in
            # `jsonToolResult(result, "error" in result)`) rather than returning a normal payload
            # with an empty complex -- so this is the only place that specific condition is
            # observable, and it must be reported as `not_found` (a real, checked absence), not the
            # generic `error` that run()'s blanket `except MCPUnavailable` would otherwise produce.
            if "NOT_FOUND" in str(exc):
                return not_found_result
            raise
        if not payload or not payload.get("kapt_code"):
            return not_found_result
        # get_complex_info's real outputSchema has no source_url (or any URL) field at all --
        # unlike the earlier, README-driven assumption -- so the citation always points at the
        # fixed K-apt site rather than a per-complex deep link that doesn't exist.
        return {"status": "ok", "complex": payload,
                "citations": [citation(f"K-apt 단지 정보 — {payload.get('name') or place.name}",
                                       "https://www.k-apt.go.kr/", "K-apt", "lookup_seoul_complex")]}

    async def _lookup_complex_trades(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        year_month = arguments.get("year_month")
        if not (isinstance(year_month, str) and len(year_month) == 6 and year_month.isdigit()):
            year_month = _default_year_month()
        empty_result = {"status": "empty", "items": [], "year_month": year_month,
                        "message": f"{place.name} 의 {year_month} 실거래 신고 내역을 찾지 못했습니다.",
                        "citations": [citation("국토교통부 실거래가", "https://rt.molit.go.kr/",
                                               "국토교통부 실거래가", "lookup_complex_trades")]}
        try:
            # complex_query lets presale-mcp resolve this specific complex's 법정동/지번 internally
            # and filter to just its rows; passing region_code alongside it would make the server
            # skip that resolution entirely and use region_code as a district-wide query instead
            # (confirmed by reading getComplexTrades' source: it only resolves complex_query when
            # region_code is absent) -- so region_code is deliberately omitted here.
            payload = await self.session.call("get_complex_trades",
                                              {"complex_query": place.name, "year_month": year_month})
        except MCPToolError as exc:
            # Same isError-marks-NOT_FOUND convention as get_complex_info (get_complex_trades'
            # registration uses the identical `jsonToolResult(result, "error" in result)` wrapper).
            # This is a list-returning lookup, so an absence is `empty`, not `not_found`.
            if "NOT_FOUND" in str(exc):
                return empty_result
            raise
        items = _list_field(payload, "items")
        if not items:
            return empty_result
        return {"status": "ok", "items": items, "year_month": year_month,
                "note": "최근 1~2개월은 신고 지연으로 실제보다 적게 보일 수 있습니다.",
                "citations": [citation(f"국토교통부 실거래가 — {place.name} {year_month}",
                                       "https://rt.molit.go.kr/", "국토교통부 실거래가", "lookup_complex_trades")]}

    async def _scan_nearby_facilities(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        categories = [str(item) for item in (arguments.get("categories") or []) if item]
        keywords = [str(item) for item in (arguments.get("keywords") or []) if item]
        if not categories and not keywords:
            return {"status": "error", "message": "찾을 카테고리나 키워드를 하나 이상 지정해야 합니다."}
        radius_m = _clamp_int(arguments.get("radius_m"), default=2000, low=1, high=20000)
        base = {"center_lat": place.latitude, "center_lng": place.longitude, "radius_m": radius_m}

        # search_by_nearby_category takes every requested category alias in a *single* call
        # (unlike search_by_nearby_keyword, which is one query per call) -- so this is at most one
        # category call plus one call per keyword, not one call per category.
        calls: list[tuple[str, str, Awaitable[dict[str, Any]]]] = []
        if categories:
            calls.append(("category", ",".join(categories),
                          self.session.call("search_by_nearby_category", {**base, "categories": categories})))
        for word in keywords:
            calls.append(("keyword", word, self.session.call("search_by_nearby_keyword", {**base, "query": word})))
        results = await asyncio.gather(*(entry[2] for entry in calls), return_exceptions=True)

        by_category: dict[str, list[dict[str, Any]]] = {}
        by_keyword: dict[str, list[dict[str, Any]]] = {}
        failures: list[str] = []
        unresolved_categories: list[str] = []
        for (kind, label, _), payload in zip(calls, results):
            if kind == "category":
                if isinstance(payload, Exception):
                    # One failed call covers every requested category; none of them were
                    # confirmed, so all of them count as failed targets.
                    failures.extend(categories)
                    continue
                raw_results = payload.get("results")
                raw_results = raw_results if isinstance(raw_results, dict) else {}
                for key, rows in raw_results.items():
                    by_category[key] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
                metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                unresolved_categories.extend(
                    warning.removeprefix("Unknown category: ") for warning in (metadata.get("warnings") or [])
                    if warning.startswith("Unknown category: "))
            else:
                if isinstance(payload, Exception):
                    failures.append(label)
                    by_keyword[label] = []
                    continue
                rows = payload.get("results")
                by_keyword[label] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

        found = sum(len(rows) for rows in list(by_category.values()) + list(by_keyword.values()))
        total_targets = len(categories) + len(keywords)
        # A failed search and a search that genuinely found nothing are different facts (see
        # TOOL_STATUSES' `empty` vs `error`). If every target failed we have no idea whether
        # anything is actually nearby, so this must not be reported with the same confidence as a
        # clean zero-row result.
        if failures and len(failures) == total_targets:
            status = "error"
            message = f"카카오 로컬 주변 검색에 실패했습니다: {', '.join(failures)}"
        elif found:
            status = "ok"
            message = None
        else:
            status = "empty"
            message = f"{place.name} 반경 {radius_m}m 안에서 해당 시설을 찾지 못했습니다."

        result: dict[str, Any] = {"status": status, "radius_m": radius_m,
                                   "by_category": by_category, "by_keyword": by_keyword,
                                   "failed_targets": failures, "message": message,
                                   "citations": [citation(f"카카오 로컬 주변 검색 — {place.name} 반경 {radius_m}m",
                                                          "https://map.kakao.com/", "카카오 로컬",
                                                          "scan_nearby_facilities")]}
        if failures:
            result["failure_note"] = f"다음 대상은 조회에 실패해 결과에서 빠졌습니다: {', '.join(failures)}"
        if unresolved_categories:
            result["unresolved_categories_note"] = (
                f"다음 카테고리는 알려진 별칭이 아니어서 조회되지 않았습니다: {', '.join(unresolved_categories)}")
        return result

    def _map_image_arguments(self, place: Place, arguments: dict[str, Any]) -> dict[str, Any]:
        # No `markers`/`center` input taken from `arguments`: a marker is a coordinate, and the
        # model must never supply one (product rule 2). The single marker is always the resolved
        # place itself. radius_m only steers get_static_map's zoom level (confirmed by its real
        # schema: "결정에만 사용(원은 그려지지 않음)" -- used to decide the level only, no circle is
        # drawn) -- it must not be described as drawing anything.
        return {"markers": [{"lat": place.latitude, "lng": place.longitude}],
                "radius_m": _clamp_int(arguments.get("radius_m"), default=1000, low=1, high=20000),
                # Modest, well inside the schema's 1024x1024 cap. The image comes back as an
                # inline base64 content block (see below), so every pixel here is text tokens in
                # the chat transcript -- smaller keeps that bounded without making the preview
                # illegible.
                "width": 480, "height": 360}

    async def _get_location_map_image(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        payload = await self.session.call("get_static_map", self._map_image_arguments(place, arguments))
        # ASSUMPTION -- not confirmed against a real successful call (only fake credentials were
        # available, so every live call fails before Naver is actually reached). What IS confirmed
        # by reading presale-mcp's own source (src/tool-result.ts's imageToolResult,
        # src/index.ts's get_static_map registration): get_static_map's declared outputSchema is
        # structuredContent-only ({marker_count, maptype, warnings}) -- there is no url/image_url
        # field anywhere in it. The actual image travels as a separate MCP ImageContent content
        # block (type="image", data=<base64>, mimeType=<string>) alongside that structuredContent.
        # mcp_client._unwrap folds that block's data/mimeType into this dict as image_base64/
        # image_mime_type specifically so this handler can read them. A real call against live
        # Naver Maps credentials would confirm the mimeType actually returned (assumed image/png
        # below when absent) and the true size of a 480x360 response.
        image_base64 = payload.get("image_base64")
        if not image_base64:
            return {"status": "empty", "message": "지도 이미지를 생성하지 못했습니다.",
                    "citations": [citation(f"네이버 정적 지도 조회 시도 — {place.name}", "https://map.naver.com/",
                                           "네이버 지도", "get_location_map_image")]}
        mime_type = payload.get("image_mime_type") or "image/png"
        return {"status": "ok", "image_url": f"data:{mime_type};base64,{image_base64}",
                "citations": [citation(f"네이버 정적 지도 — {place.name}", "https://map.naver.com/",
                                       "네이버 지도", "get_location_map_image")]}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"name": "resolve_seoul_place",
     "description": ("지명·아파트 단지명·주소를 공식 좌표와 자치구로 해석하고 place_ref 를 발급한다. "
                     "다른 모든 도구는 좌표가 아니라 이 place_ref 를 받는다. 반드시 이 도구를 먼저 호출하라. "
                     "서울 25개 자치구 밖이면 status=out_of_scope 를 돌려준다."),
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"query": {"type": "string", "description": "지명, 아파트 단지명, 또는 주소"}},
                    "required": ["query"]}},
    {"name": "lookup_seoul_presale",
     "description": ("place_ref 주변 radius_km 안의 청약홈 분양공고와 주택형·분양가를 조회한다(최근 24개월). "
                     "ApplyHome 자체는 반경 검색을 지원하지 않아 각 공고 주소를 좌표로 환산해 반경으로 걸러내며, "
                     "이 사실과 좌표 변환에 실패해 제외된 공고 수를 scope_note 그대로 사용자에게 전하라."),
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"},
                                   "radius_km": {"type": "integer",
                                                "description": "선택. 반경(킬로미터). 기본 5, 1~20 범위를 벗어나면 자동 보정된다"}},
                    "required": ["place_ref"]}},
    {"name": "lookup_seoul_complex",
     "description": "place_ref 가 가리키는 아파트 단지의 K-apt 개요(세대수·연식·동수·주차대수)를 조회한다. 실거래는 포함하지 않는다.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"}},
                    "required": ["place_ref"]}},
    {"name": "lookup_complex_trades",
     "description": ("place_ref 가 가리키는 단지의 국토교통부 실거래(매매)를 특정 한 달(year_month) 기준으로 조회한다. "
                     "이 도구는 한 번 호출할 때마다 정확히 한 달치만 확인한다 -- 여러 달 추세가 필요하면 다른 "
                     "year_month 로 이 도구를 다시 호출하라. 반환된 금액을 그대로 인용하라. "
                     "평당가·증감률을 직접 계산하지 마라."),
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"},
                                   "year_month": {"type": "string",
                                                  "description": "선택. YYYYMM 형식의 계약년월. 생략하면 약 2개월 전 "
                                                                 "달을 기본값으로 사용한다(신고 지연 감안)"}},
                    "required": ["place_ref"]}},
    {"name": "scan_nearby_facilities",
     "description": ("place_ref 반경 안의 시설을 카카오 로컬에서 찾는다. categories 는 카카오 원시 코드가 아니라 "
                     "다음 별칭만 받는다: school_elementary(초등학교), school_middle(중학교), school_high(고등학교), "
                     "school(학교 전체), subway(지하철역), mart_large(대형마트), hospital(병원), pharmacy(약국), "
                     "park(공원). keywords 는 자유 검색어를 받는다. 둘 중 하나는 반드시 지정해야 한다. "
                     "알 수 없는 카테고리는 unresolved_categories_note 에, 조회 자체가 실패한 대상은 "
                     "failed_targets/failure_note 에 담기며 -- 이때는 그 대상에 아무것도 없다고 말하지 말고 "
                     "조회 자체가 실패했다고 전하라."),
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"},
                                   "categories": {"type": "array", "items": {"type": "string"},
                                                  "description": "카테고리 별칭 목록. 예: school, subway, mart_large"},
                                   "keywords": {"type": "array", "items": {"type": "string"},
                                                "description": "자유 검색어 목록"},
                                   "radius_m": {"type": "integer",
                                                "description": "선택. 반경(미터). 기본 2000, 1~20000 범위를 벗어나면 자동 보정된다"}},
                    "required": ["place_ref"]}},
    {"name": "get_location_map_image",
     "description": "place_ref 위치를 표시한 네이버 정적 지도 이미지를 만든다. radius_m 은 확대 수준만 정할 뿐 반경 원을 그리지 않는다.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"},
                                   "radius_m": {"type": "integer",
                                                "description": "선택. 확대 수준을 정하는 반경(미터) 힌트. 기본 1000, 1~20000 범위를 벗어나면 자동 보정된다"}},
                    "required": ["place_ref"]}},
]
