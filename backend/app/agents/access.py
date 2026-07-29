"""어디 — 접근성 축.

**새 도구를 만들지 않는다.** 대화가 이미 쓰는 `chat_tools.ChatToolset` 의 두 도구를 그대로
부른다: `resolve_seoul_place` 로 좌표를 확인하고, `scan_nearby_facilities` 로 주변을 훑는다.
같은 질문에 두 벌의 조회 코드를 두면 화면과 대화가 다른 답을 내게 된다.

`resolve_seoul_place` 를 먼저 부르는 것은 편의가 아니라 계약이다. `get_geocode` 가 주소 →
좌표 한 방향이라 모델이나 호출자가 건넨 좌표는 서울 자치구 안인지 확인할 방법이 없다. 그래서
좌표를 신뢰하기 **전에** 관문이 서고, 다른 도구는 전부 `place_ref` 만 받는다.

── 이 축이 켜지지 않는 조건 ────────────────────────────────────────────────

도구가 배선되지 않았거나(MCP 미가용) 후보에 주소가 없으면 `integration_pending` 이다. 좌표계를
추측해 채우지 않는다 — 접근성은 "역에서 몇 분"처럼 들리는 수치라, 틀린 값이 빈 값보다 훨씬
나쁘다. 판정하지 못한 축은 후보 탈락 근거로도 쓰이지 않는다.
"""
from __future__ import annotations

from typing import Any

from .contracts import AgentOutcome, AgentStatus
from .registry import spec

_PENDING = ("주변 시설 조회 도구가 연결되지 않아 접근성을 판정하지 않았습니다. "
            "좌표계를 추측해 거리·소요시간을 만들지 않습니다.")
_NO_ADDRESS = ("후보에 주소가 없어 위치를 확인하지 못했습니다. 주소 없이 좌표를 짐작하지 않습니다.")


class AccessAxis:
    """도구 세트를 **직접 받거나**, 실행 시점에 만들 방법을 받는다.

    `toolset_factory` 는 `async with` 로 열고 닫는 컨텍스트 매니저를 돌려주는 호출 가능 객체다.
    MCP 세션이 그런 모양이어야 하는 이유는 `mcp_client` 가 이미 적어 둔 그대로다 —
    `stdio_client`/`ClientSession` 이 각각 anyio 취소 스코프를 열고, anyio 는 스코프를 연 태스크가
    닫기를 요구한다. 그래서 세션은 이 `run()` **한 함수 안에서** 열리고 닫힌다. 세션을 미리 만들어
    보관하면 첫 재시작에서 `RuntimeError` 가 난다.
    """

    key = "location.access"

    def __init__(self, toolset: Any | None = None, toolset_factory: Any | None = None):
        self.toolset = toolset
        self.toolset_factory = toolset_factory

    async def run(self, candidates: list[dict[str, Any]]) -> AgentOutcome:
        declaration = spec(self.key)
        if self.toolset is not None:
            return await self._with(self.toolset, candidates)
        if self.toolset_factory is None:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_PENDING,
                                       required_actions=["presale-mcp 를 연결하면 이 축이 켜집니다."])
        try:
            async with self.toolset_factory() as toolset:
                return await self._with(toolset, candidates)
        except Exception:  # noqa: BLE001 — CancelledError 는 BaseException 이라 통과한다
            # 조회 실패는 실패가 아니라 연동 대기다. 축이 꺼진 이유는 원천이지 이 코드가 아니다.
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_PENDING)

    async def _with(self, toolset: Any, candidates: list[dict[str, Any]]) -> AgentOutcome:
        declaration = spec(self.key)
        readings: dict[str, Any] = {}
        for candidate in candidates:
            address = candidate.get("address") or candidate.get("name")
            if not address:
                continue
            reading = await self._scan(toolset, str(address))
            if reading is not None:
                readings[candidate["id"]] = reading
        if not readings:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_NO_ADDRESS)
        return declaration.outcome(AgentStatus.OK, data={"by_candidate": readings})

    async def _scan(self, toolset: Any, address: str) -> dict[str, Any] | None:
        """관문 → 스캔. `ChatToolset.run` 은 어떤 실패도 값으로 바꾸므로 예외를 보지 않는다."""
        resolved = await toolset.run("resolve_seoul_place", {"query": address})
        if resolved.get("status") != "ok":
            return None
        place_ref = resolved.get("place_ref") or (resolved.get("place") or {}).get("place_ref")
        if not place_ref:
            return None
        scanned = await toolset.run("scan_nearby_facilities", {"place_ref": place_ref})
        if scanned.get("status") != "ok":
            return None
        # 원천이 준 값을 그대로 옮긴다. 여기서 거리·소요시간을 계산하거나 등급을 매기지 않는다 —
        # 좌표계 실측이 끝나기 전에는 그 산술이 무엇을 뜻하는지 말할 수 없다.
        return {"facilities": scanned.get("facilities", []),
                "citations": scanned.get("citations", []),
                "evidence_grade": spec("location.access").evidence_grade}
