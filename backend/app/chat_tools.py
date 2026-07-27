from __future__ import annotations
import secrets
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from .mcp_client import MCPUnavailable

SEOUL_DISTRICTS = {"종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구",
                   "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구",
                   "관악구", "서초구", "강남구", "송파구", "강동구"}

OUT_OF_SCOPE_MESSAGE = "자리매김은 서울 25개 자치구만 다룹니다. 이 지역은 분석 범위 밖입니다."


class Place:
    """A coordinate the model is never allowed to see or invent."""

    def __init__(self, ref: str, name: str, address: str, latitude: float, longitude: float,
                 district: str, bjd_code: str, sgg_code: str, applyhome_code: str):
        self.ref, self.name, self.address = ref, name, address
        self.latitude, self.longitude, self.district = latitude, longitude, district
        self.bjd_code, self.sgg_code, self.applyhome_code = bjd_code, sgg_code, applyhome_code


class PlaceRegistry:
    """Scoped to a single turn. A ref from another turn resolves to nothing by construction."""

    def __init__(self):
        self._places: dict[str, Place] = {}

    def issue(self, **fields) -> Place:
        ref = f"pl_{secrets.token_hex(4)}"
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
        try:
            return await handler(arguments or {})
        except MCPUnavailable as exc:
            return {"status": "error", "message": str(exc)}

    def _place_or_error(self, arguments: dict[str, Any]) -> tuple[Place | None, dict[str, Any] | None]:
        place = self.registry.get(arguments.get("place_ref"))
        if place is None:
            return None, {"status": "invalid_place_ref",
                          "message": "먼저 resolve_seoul_place 로 위치를 확인한 뒤 그 place_ref 를 사용하세요."}
        return place, None

    async def _lookup_seoul_complex_stub(self, arguments: dict[str, Any]) -> dict[str, Any]:
        place, error = self._place_or_error(arguments)
        if error is not None:
            return error
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
