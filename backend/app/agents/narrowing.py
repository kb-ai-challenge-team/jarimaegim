"""후보 축소. 결정론이고, 모델도 LLM 도 여기 없다.

**탈락 권한은 매출 축 하나만 갖는다.** 축이 여덟 개로 늘었다고 탈락 사유가 여덟 가지로 늘면
안 된다 — 축을 늘린 목적은 "무엇을 아는가"를 넓히는 것이지 "무엇을 떨어뜨리는가"를 넓히는
것이 아니다. 수요가 낮다는 사실은 사용자가 보고 판단할 표시이지, 후보를 지울 근거가 아니다.

그래서 권한을 상수로 선언하고, 그 밖의 축이 탈락을 시도하면 **실패한다**. 조용히 무시하지
않는 이유는 그것이 곧 "탈락시켰다고 생각했는데 안 됐다"는 상태를 만들기 때문이다 — 규칙을
어긴 쪽이 그 자리에서 알아야 한다.

판정하지 못한 축은 애초에 여기 들어오지 않는다(`AgentOutcome.active` 가 아닌 것). 원천이
없다는 사실이 "이 자리는 나쁘다"로 둔갑하지 않게 하는 성질이 이 모듈에서도 그대로다.
"""
from __future__ import annotations

from typing import Any

from .contracts import AgentOutcome

#: 후보를 떨어뜨릴 수 있는 축. 목표매출이 상권 동종 매출 분포의 상위 10%를 넘으면
#: "그 상권 상위 10%만큼 팔아야 성립"이라는 뜻이고, 그것만이 하드 탈락 사유다(제안서 04장).
DROP_AUTHORITY: frozenset[str] = frozenset({"location.viability"})


class UnauthorisedDrop(RuntimeError):
    """탈락 권한이 없는 축이 후보를 떨어뜨리려 했다."""


def drop_reason(key: str, judgement: dict[str, Any] | None) -> str | None:
    """이 축이 이 후보를 떨어뜨릴 사유가 있으면 문장으로, 없으면 None.

    권한이 없는 축이 사유를 내면 `UnauthorisedDrop` 이다. 사유를 만들 수 있는 코드를 축마다
    두지 않고 여기 모으는 이유가 그것이다 — 권한 검사와 사유 생성이 떨어져 있으면 검사를
    건너뛴 경로가 생긴다."""
    if not judgement:
        return None
    if not judgement.get("above_top_decile"):
        return None
    if key not in DROP_AUTHORITY:
        raise UnauthorisedDrop(
            f"{key} 축은 후보를 떨어뜨릴 수 없습니다. 탈락 권한은 {sorted(DROP_AUTHORITY)} 뿐입니다.")
    return ("목표매출이 상권 동종 상위 10% 경계를 넘어 분기점 미달입니다 "
            f"(분포 위치 {judgement['value']:.0%}).")


def narrow(candidates: list[dict[str, Any]],
           outcomes: list[AgentOutcome]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """사유가 있는 것만 탈락시킨다. 개수는 고정하지 않는다.

    판정하지 못한 축(`active` 가 아닌 것)은 읽지 않는다 — 데이터가 없다는 사실이 후보를
    떨어뜨리는 근거가 되면 원천이 붙지 않은 축이 곧 불리한 판정이 된다."""
    judged: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        if outcome.key in DROP_AUTHORITY and outcome.active:
            judged = outcome.data.get("by_candidate", {}) or {}
            break

    surviving, dropped = [], []
    for candidate in candidates:
        reason = None
        for key in DROP_AUTHORITY:
            reason = drop_reason(key, judged.get(candidate["id"]))
            if reason:
                break
        (dropped if reason else surviving).append(
            {**candidate, "reason": reason} if reason else candidate)
    return surviving, dropped
