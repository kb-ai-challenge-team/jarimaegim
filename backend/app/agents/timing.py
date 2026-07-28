"""언제 — 타이밍 팀.

잔존 후보에 대해서만 돈다. 개발·정책 일정 원천이 확보되지 않았으므로 현재는 언제나
"일정 확인 전 판단 유보"를 반환하고, 후보는 한 건도 건드리지 않는다.

이 팀을 지우지 않고 빈 채로 남겨 두는 것이 설계 결정이다 — 제품 정의의 "언제"를 삭제하면
공백이 보이지 않게 되고, 그러면 채워지지 않았다는 사실 자체가 화면에서 사라진다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import AgentStatus, TeamReport
from .registry import spec

_WITHHELD = ("개발·정책 일정 원천이 확보되지 않아 계약 시점을 권고하지 않습니다. "
             "일정 확인 전 판단 유보입니다.")


@dataclass(frozen=True)
class TimingReport(TeamReport):
    surviving: list[dict[str, Any]] = field(default_factory=list)


class TimingTeam:
    team = "timing"
    name = "타이밍 팀"

    def run(self, candidates: list[dict[str, Any]]) -> TimingReport:
        outcome = spec("timing.policy").outcome(
            AgentStatus.INTEGRATION_PENDING, message=_WITHHELD,
            required_actions=["재개발·교통·주택공급·공사 일정 원천을 확보해야 시점을 말할 수 있습니다."])
        # 후보는 그대로 통과시킨다. 판정하지 못한 팀이 후보를 줄이면 안 된다.
        return TimingReport(team=self.team, name=self.name, outcomes=[outcome], blocking=False,
                            surviving=list(candidates))
