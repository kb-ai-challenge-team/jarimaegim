"""조건 확정 레이어.

제안서 03장 — "최소 조건 미충족 시 후보를 생성하지 않고 질문합니다. 최대 3개, 답이 후보를
바꾸는 항목만." 그래서 이 레이어는 `blocking=True` 다. 조건이 덜 찬 채로 후보를 만들면
그 후보는 사용자가 말하지 않은 가정 위에 서게 된다.

질문 상한 3개는 UX 예의가 아니라 정보 설계다. 답이 후보 목록을 바꾸지 않는 항목까지 물으면
사용자는 "무엇을 답해야 결과가 달라지는지" 알 수 없게 된다. 평수·운영형태를 선택 항목으로
둔 이유가 그것이다 — 없어도 후보는 나오고, 있으면 필요자금과 현금소진이 더 정확해질 뿐이다.

마이데이터는 게이트 off 다. 수동 입력이 **동일 스키마를 충족**하므로 제품은 성립하고,
이 레이어는 어느 경로로 채워졌는지를 `source` 로 밝힌다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import AgentStatus, TeamReport
from .registry import spec

#: 답이 후보를 바꾸는 항목. 이것이 최소 조건이다.
REQUIRED_LOCATION = (("industry", "업종"), ("district", "자치구"))
REQUIRED_FINANCE = (("equity_krw", "자기자본"), ("monthly_rent_krw", "희망 월세"))

#: 있으면 필요자금·현금소진이 정확해지지만, 없어도 후보는 나온다.
OPTIONAL_LOCATION = (("area_pyeong", "희망 평수"), ("operating_style", "운영형태"),
                     ("deposit_krw", "희망 보증금"))

QUESTION_LIMIT = 3


@dataclass(frozen=True)
class ConditionReport(TeamReport):
    questions: list[dict[str, str]] = field(default_factory=list)
    settled: bool = False

    @property
    def halted(self) -> bool:
        """기본 규칙(`활성 0건`)을 쓰지 않는다. 두 에이전트 중 하나만 미충족이어도 후보를
        만들면 안 되므로, 이 레이어의 중단 조건은 "전부 확정되었는가" 하나다."""
        return not self.settled


def _missing(conditions: dict[str, Any], required) -> list[tuple[str, str]]:
    gaps = []
    for key, label in required:
        value = conditions.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            gaps.append((key, label))
    return gaps


class ConditionLayer:
    team = "condition"
    name = "조건 확정 레이어"

    def __init__(self, *, mydata_enabled: bool = False):
        self.mydata_enabled = mydata_enabled

    def run(self, conditions: dict[str, Any]) -> ConditionReport:
        location_gaps = _missing(conditions, REQUIRED_LOCATION)
        finance_gaps = _missing(conditions, REQUIRED_FINANCE)

        location = spec("condition.location")
        finance = spec("condition.finance")
        outcomes = [
            location.outcome(
                AgentStatus.WITHHELD if location_gaps else AgentStatus.OK,
                message="입지 최소 조건이 아직 확정되지 않았습니다." if location_gaps else None,
                data={"settled": {key: conditions.get(key) for key, _ in REQUIRED_LOCATION},
                      "optional": {key: conditions.get(key) for key, _ in OPTIONAL_LOCATION},
                      "missing": [key for key, _ in location_gaps]}),
            finance.outcome(
                AgentStatus.WITHHELD if finance_gaps else AgentStatus.OK,
                message="금융 프로필이 아직 확정되지 않았습니다." if finance_gaps else None,
                data={"source": "MYDATA" if self.mydata_enabled else "MANUAL",
                      "mydata_enabled": self.mydata_enabled,
                      "settled": {key: conditions.get(key) for key, _ in REQUIRED_FINANCE},
                      "missing": [key for key, _ in finance_gaps]}),
        ]

        questions = [{"field": key, "label": label} for key, label in
                     (location_gaps + finance_gaps)][:QUESTION_LIMIT]
        settled = not location_gaps and not finance_gaps
        return ConditionReport(team=self.team, name=self.name, outcomes=outcomes, blocking=True,
                              questions=questions, settled=settled,
                              message=None if settled else "확정되지 않은 조건이 있어 후보를 생성하지 않았습니다.")
