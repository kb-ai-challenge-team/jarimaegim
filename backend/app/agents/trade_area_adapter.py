"""상권 프로파일(`trade_area.TradeAreaService`)을 입지팀의 어댑터 계약으로 옮긴다.

이 파일이 지키는 규칙은 하나다 — **같은 숫자를 두 번 판정하지 않는다.**

`TradeAreaService` 는 서울 동종 중앙값 대비 비교와 표본 보정(적은 표본을 중앙값 쪽으로 당기는
것)을 이미 끝낸 판정을 내놓는다. 어댑터가 원시 비율만 받아 입지팀 기준으로 다시 등급을 매기면
그 보정이 사라지고, 점포 6곳짜리 행정동이 '서울 중앙값의 617%'로 다시 1순위를 차지한다
(제안서 06장 JUDGEMENT 02 가 실제로 겪고 고친 문제다). 그래서 여기서는 판정을 그대로 옮기고,
입지팀은 옮겨진 판정을 인용만 한다.

**달성 가능성(location.viability)은 옮기지 않는다.** 그 축은 "목표매출을 상권 매출 분포에
대입한 백분위"이고, 상위 10%를 넘으면 후보를 **탈락시킨다.** 상권 데이터에는 점포당 추정매출의
중앙값 대비 비율은 있어도 '이 사업의 목표매출이 분포 어디에 놓이는가'는 없다. 그 백분위를 어떻게
정의할지가 정해지기 전에 붙이면 정의되지 않은 기준으로 후보가 사라지므로, 판정할 수 없다고
말하고 축을 켜지 않는다. 판정하지 않은 축은 탈락 근거로 쓰이지 않는다는 규칙이 여기서도 그대로다.

생존시기는 애초에 이 원천의 몫이 아니다 — 인허가 이력 코호트가 있어야 하는 유일한 A등급 경로다.
"""
from __future__ import annotations

from typing import Any, Callable

#: 상권 신호와 입지 축이 1:1로 대응하는 것만 켠다.
JUDGEABLE: tuple[str, ...] = ("demand", "competition")

PENDING_REASONS = {
    "viability": ("목표매출을 상권 매출 분포에 대입하는 백분위 정의가 정해지지 않아 이 축을 판정하지 "
                  "않았습니다. 정의 전에는 추정하지 않으며, 판정하지 않은 축은 탈락 근거로 쓰이지 않습니다."),
}


def _default_resolve(industry: str) -> str | None:
    from ..industry import resolve as resolve_industry
    return resolve_industry(industry)


def _default_unavailable():
    from ..trade_area import TradeAreaUnavailable
    return TradeAreaUnavailable


class TradeAreaProfiles:
    """입지팀이 기대하는 `available` · `profile(...)` 만 노출한다.

    조회 키가 이름이 아니라 **코드**인 것이 중요하다. 행정동은 코드로, 업종은 정규화된 코드로만
    결합한다 — 이름으로 맞추면 '스터디카페'가 '커피-음료'에 붙는 유사 매칭이 되살아난다.
    """

    def __init__(self, service: Any, *,
                 resolve: Callable[[str], str | None] | None = None,
                 unavailable_type: type | None = None):
        self.service = service
        self._resolve = resolve or _default_resolve
        self._unavailable = unavailable_type or _default_unavailable()

    #: 후보의 어느 필드로 결합하는가. 이름이 아니라 행정동 코드다.
    keyed_by = "admin_dong_code"

    @property
    def available(self) -> bool:
        return bool(getattr(self.service, "available", False))

    @property
    def judgeable(self) -> tuple[str, ...]:
        return JUDGEABLE

    @staticmethod
    def reason_for(axis: str) -> str | None:
        """이 어댑터로 판정할 수 없는 축과 그 사유. 판정할 수 있으면 None."""
        return PENDING_REASONS.get(axis)

    def profile(self, dong_code: str, industry: str) -> dict[str, Any] | None:
        code = self._resolve(industry or "")
        if not dong_code or not code:
            # 정규화되지 않은 업종으로는 조회조차 하지 않는다. 비슷한 업종을 대신 넣지 않는다.
            return None
        found = self.service.lookup(dong_code, code)
        if found is None or isinstance(found, self._unavailable):
            return None
        signals = {item.name: {"score_band": item.score_band, "direction": item.direction,
                               "label": item.label, "explanation": item.explanation}
                   for item in self.service.signals(found)}
        return {"quarter": getattr(self.service, "quarter", None),
                "sample_n": found.get("store_count"),
                "admin_dong": found.get("admin_dong"),
                "industry_code": code,
                "signals": signals}
