from __future__ import annotations
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from .mcp_client import MCPUnavailable

logger = logging.getLogger(__name__)

SEOUL_DISTRICTS = {"종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구",
                   "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구",
                   "관악구", "서초구", "강남구", "송파구", "강동구"}

OUT_OF_SCOPE_MESSAGE = "자리매김은 서울 25개 자치구만 다룹니다. 이 지역은 분석 범위 밖입니다."

# Status vocabulary every handler's result dict draws from. Task 7's function-calling loop and
# the model both read this field, so it's a contract -- declared once here rather than letting
# each new handler in Tasks 5-6 re-derive it from scattered return statements.
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
#   not_implemented  -- handler is registered but its real body hasn't been written yet (a Task
#                        5-6 stub only; must not appear once those tasks land).
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


def _first_document(payload: dict[str, Any]) -> dict[str, Any] | None:
    documents = payload.get("documents")
    if isinstance(documents, list) and documents and isinstance(documents[0], dict):
        return documents[0]
    return None


def _https(url: str, fallback: str) -> str:
    """Upgrades an insecure absolute URL -- bare `http://...` or protocol-relative `//...` -- to
    https. Returns `fallback` when `url` is empty, and otherwise passes anything else through
    unchanged: already-`https://` URLs, and a schemeless string like `www.host/path` that this
    function can't reliably tell apart from a relative path, so it doesn't guess. k-apt still
    serves some `http://` links; that's the concrete case this exists to fix."""
    if not url:
        return fallback
    if url.startswith("http://"):
        return "https://" + url.removeprefix("http://")
    if url.startswith("//"):
        return "https:" + url
    return url


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("items")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class PlaceRefError(Exception):
    """The model passed a place_ref this turn's registry never issued."""


class ChatToolset:
    """Wraps presale-mcp's 11 primitives into the seven tools the model is allowed to see."""

    def __init__(self, session, registry: PlaceRegistry):
        self.session = session
        self.registry = registry
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            "resolve_seoul_place": self._resolve_seoul_place,
            "lookup_seoul_presale": self._lookup_seoul_presale,
            "lookup_seoul_complex": self._lookup_seoul_complex,
            "lookup_complex_trades": self._lookup_complex_trades,
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
            # anticipated, or a bug in one of them, must not escape into Task 7's function-calling
            # loop as a raw exception -- that is exactly what this method exists to prevent. Log
            # the tool name and exception type only, never `arguments`, which can carry
            # user-entered text. Deliberately `Exception`, not `BaseException`: a genuine
            # CancelledError must still propagate untouched.
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

    async def _lookup_seoul_presale(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        payload = await self.session.call("search_announcement_info",
                                          {"region_code": place.applyhome_code or place.sgg_code})
        items = _items(payload)
        # 청약홈 has no per-announcement coordinate to filter by (search_announcement_info returns
        # house_nm/pblanc_url/rcrit_pblanc_de/house_manage_no/supply_types, nothing spatial), so this
        # is always the whole 자치구's list -- never narrowed to place.name or any radius. Say so
        # plainly rather than implying a filter this handler doesn't perform.
        scope_note = (f"청약홈은 자치구(구 단위) 지역코드로만 조회됩니다. {place.district} 전체 분양공고이며, "
                      f"특정 지점이나 반경으로 좁혀진 결과가 아닙니다.")
        # District-level, not per-announcement: a 40-listing district would otherwise emit 40
        # near-identical citations into the SSE done event and chat panel. Each item already
        # carries its own pblanc_url, so nothing is lost by collapsing this to one.
        applyhome_citation = citation(f"청약홈 분양공고 — {place.district}",
                                      "https://www.applyhome.co.kr/", "청약홈", "lookup_seoul_presale")
        if not items:
            return {"status": "empty", "items": [], "scope_note": scope_note,
                    "message": f"{place.district}에 등록된 분양공고를 찾지 못했습니다. 청약홈에서 직접 확인해 주세요.",
                    "citations": [applyhome_citation]}

        # Dedupe before the enrichment request: a re-announced complex can appear twice in the
        # announcement list, and sending the same id twice would be a wasted round trip for
        # identical data. dict.fromkeys keeps first-seen order without a separate set.
        manage_nos = list(dict.fromkeys(item.get("house_manage_no") for item in items
                                        if item.get("house_manage_no") is not None))
        by_manage_no: dict[str, dict[str, Any]] = {}
        enrichment_note: str | None = None
        if not manage_nos:
            enrichment_note = "분양공고에 단지관리번호가 없어 K-apt 단지 정보 보강을 생략했습니다."
        else:
            try:
                enriched = await self.session.call("enrich_complex_info", {"house_manage_nos": manage_nos})
                # Filter out rows with no house_manage_no here, and skip id-less items on the other
                # side of the join below: str(None) is the literal string "None", so one malformed
                # upstream row missing an id would otherwise occupy by_manage_no["None"] -- and every
                # *other* id-less announcement would match that key and inherit an unrelated
                # complex's 세대수·연식 as if it had actually been looked up.
                by_manage_no = {str(row.get("house_manage_no")): row for row in _items(enriched)
                                if row.get("house_manage_no") is not None}
            except MCPUnavailable:
                # Enrichment is an optional embellishment; the announcements themselves are the
                # answer the user is entitled to see, so a failure here must not discard them --
                # handlers don't catch MCPUnavailable elsewhere precisely so run() can turn it into
                # status=error, but that would throw away perfectly good search results here.
                enrichment_note = "K-apt 단지 정보 보강에 실패해 분양공고만 표시합니다."

        # Build new dicts rather than mutating `item` in place: these dicts came straight out of
        # the MCP payload, and nothing here guarantees that payload is a private, freshly-allocated
        # object the caller never looks at again (a cache, a test fixture reused across calls, a
        # future MCP client that memoizes) -- mutating it would let this handler's enrichment leak
        # into whatever else holds a reference.
        items = [{**item, "complex_info": by_manage_no[str(item.get("house_manage_no"))]}
                 if item.get("house_manage_no") is not None and str(item.get("house_manage_no")) in by_manage_no
                 else item for item in items]

        citations = [applyhome_citation]
        if by_manage_no:
            citations.append(citation("K-apt 단지 정보", "https://www.k-apt.go.kr/", "K-apt", "lookup_seoul_presale"))

        result = {"status": "ok", "items": items, "scope_note": scope_note, "citations": citations}
        if enrichment_note:
            result["enrichment_note"] = enrichment_note
        return result

    async def _lookup_seoul_complex(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        payload = await self.session.call("get_complex_info", {"latitude": place.latitude, "longitude": place.longitude,
                                                               "complex_name": place.name, "bjd_code": place.bjd_code})
        if not payload or not payload.get("kapt_code"):
            return {"status": "not_found", "complex": None,
                    "message": f"{place.name} 의 K-apt 단지 정보를 찾지 못했습니다. 아파트 단지가 아닐 수 있습니다.",
                    "citations": [citation("K-apt 단지 검색", "https://www.k-apt.go.kr/", "K-apt", "lookup_seoul_complex")]}
        return {"status": "ok", "complex": payload,
                "citations": [citation(f"K-apt 단지 정보 — {payload.get('kapt_name') or place.name}",
                                       _https(payload.get("source_url") or "", "https://www.k-apt.go.kr/"),
                                       "K-apt", "lookup_seoul_complex")]}

    async def _lookup_complex_trades(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place = self._require_place(arguments)
        try:
            months = int(arguments.get("months") or 12)
        except (TypeError, ValueError):
            months = 12
        # Clamp rather than forward unvalidated: a model-supplied 0, negative, or multi-decade span
        # would go straight to MOLIT otherwise. 1-36 (up to 3 years) comfortably covers what a
        # location decision needs.
        months = max(1, min(months, 36))
        payload = await self.session.call("get_complex_trades", {"bjd_code": place.bjd_code, "sgg_code": place.sgg_code,
                                                                 "complex_name": place.name, "months": months})
        items = _items(payload)
        source = _https(payload.get("source_url") or "", "https://rt.molit.go.kr/")
        if not items:
            return {"status": "empty", "items": [], "months": months,
                    "message": f"{place.name} 의 최근 {months}개월 실거래 신고 내역을 찾지 못했습니다.",
                    "citations": [citation("국토교통부 실거래가", source, "국토교통부 실거래가", "lookup_complex_trades")]}
        return {"status": "ok", "items": items, "months": months,
                "note": "최근 1~2개월은 신고 지연으로 실제보다 적게 보일 수 있습니다.",
                "citations": [citation(f"국토교통부 실거래가 — {place.name}", source,
                                       "국토교통부 실거래가", "lookup_complex_trades")]}

    async def _resolve_seoul_place(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = (arguments.get("query") or "").strip()
        if not query:
            return {"status": "error", "message": "찾을 지명이나 주소가 비어 있습니다."}

        address_payload = await self.session.call("get_address", {"query": query})
        document = _first_document(address_payload)
        if document is None:
            return {"status": "not_found", "message": f"'{query}' 에 해당하는 공식 주소를 찾지 못했습니다."}

        address = document.get("road_address_name") or document.get("address_name") or query
        geo_payload = await self.session.call("get_geocode", {"address": address})
        geo = _first_document(geo_payload)
        if geo is None:
            return {"status": "not_found", "message": f"'{address}' 의 좌표를 확인하지 못했습니다."}

        district = (geo.get("region_2depth_name") or "").strip()
        # Assumes Kakao's region_2depth_name is always the bare 자치구 name (e.g. "강남구"), never
        # prefixed with 시/도 ("서울 강남구"). If that assumption ever drifts, the value simply
        # won't match anything in SEOUL_DISTRICTS and the guard fails closed (out_of_scope), never
        # open.
        # Refuse before spending a region-code call on a place we will not serve.
        if district not in SEOUL_DISTRICTS:
            return {"status": "out_of_scope", "message": OUT_OF_SCOPE_MESSAGE,
                    "detected_region": district or "확인 불가"}

        # A malformed upstream payload (missing/non-numeric x·y) is a data-provider failure,
        # not a bug in this handler -- treat it the same as any other "couldn't answer" case
        # rather than letting a raw KeyError/ValueError past run()'s `except MCPUnavailable`.
        try:
            latitude, longitude = float(geo["y"]), float(geo["x"])
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": f"'{address}' 의 좌표 값이 올바르지 않습니다."}

        region = await self.session.call("get_region_code", {"address": geo.get("address_name") or address})
        place = self.registry.issue(
            name=document.get("place_name") or address, address=geo.get("address_name") or address,
            latitude=latitude, longitude=longitude, district=district,
            bjd_code=str(region.get("bjd_code") or geo.get("b_code") or ""),
            sgg_code=str(region.get("sgg_code") or ""), applyhome_code=str(region.get("applyhome_code") or ""))
        return {"status": "ok", "place_ref": place.ref, "name": place.name, "address": place.address,
                "district": place.district,
                "citations": [citation(f"카카오 로컬 장소 — {place.name}",
                                       document.get("place_url") or "https://map.kakao.com/",
                                       "카카오 로컬", "resolve_seoul_place")]}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"name": "resolve_seoul_place",
     "description": ("지명·아파트 단지명·주소를 공식 좌표와 자치구로 해석하고 place_ref 를 발급한다. "
                     "다른 모든 도구는 좌표가 아니라 이 place_ref 를 받는다. 반드시 이 도구를 먼저 호출하라. "
                     "서울 25개 자치구 밖이면 status=out_of_scope 를 돌려준다."),
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"query": {"type": "string", "description": "지명, 아파트 단지명, 또는 주소"}},
                    "required": ["query"]}},
    {"name": "lookup_seoul_presale",
     "description": ("place_ref 가 가리키는 자치구의 청약홈 분양공고와 주택형·분양가를 조회한다. "
                     "청약홈은 자치구 단위 지역코드로만 조회되므로 결과는 항상 해당 구 전체이며 "
                     "특정 지점이나 반경으로 좁혀지지 않는다. 이 사실을 scope_note 그대로 사용자에게 전하라. "
                     "일부 공고에는 K-apt 단지 정보(complex_info)가 추가로 붙을 수 있고, 보강이 생략되거나 "
                     "실패하면 enrichment_note 에 그 사실이 담긴다 -- 이때는 단지 정보가 확인되지 않았다고 전하라."),
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"}},
                    "required": ["place_ref"]}},
    {"name": "lookup_seoul_complex",
     "description": "place_ref 가 가리키는 아파트 단지의 K-apt 개요(세대수·연식·동수·주차대수)를 조회한다. 실거래는 포함하지 않는다.",
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"}},
                    "required": ["place_ref"]}},
    {"name": "lookup_complex_trades",
     "description": ("place_ref 가 가리키는 단지의 국토교통부 실거래(매매·전월세·분양권)를 조회한다. "
                     "반환된 금액을 그대로 인용하라. 평당가·증감률을 직접 계산하지 마라."),
     "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"place_ref": {"type": "string", "description": "resolve_seoul_place 가 발급한 값"},
                                   "months": {"type": "integer",
                                              "description": "선택. 조회 개월 수. 기본 12, 1~36 범위를 벗어나면 자동 보정된다"}},
                    "required": ["place_ref"]}},
]
