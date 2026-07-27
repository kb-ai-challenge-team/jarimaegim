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


class PlaceRefError(Exception):
    """The model passed a place_ref this turn's registry never issued."""


class ChatToolset:
    """Wraps presale-mcp's 11 primitives into the seven tools the model is allowed to see."""

    def __init__(self, session, registry: PlaceRegistry):
        self.session = session
        self.registry = registry
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            "resolve_seoul_place": self._resolve_seoul_place,
            # Stub only: Task 5 fills in the real lookup. Registered now so the place_ref
            # guard tests (which predate the tool's real body) have a handler to call through.
            "lookup_seoul_complex": self._lookup_seoul_complex_stub,
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

    async def _lookup_seoul_complex_stub(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_place(arguments)
        return {"status": "not_implemented"}

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
]
