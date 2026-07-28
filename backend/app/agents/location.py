"""어디 — 입지추천 팀.

금융처방 팀이 만든 기준선 안에서 후보를 판정한다. 팀 계약상 **후속을 막지 않는다**:
축 하나가 죽어도 나머지 축으로 계속 가고, 죽은 축은 탈락 근거로 쓰이지 않는다.

`trade_area` 어댑터로 상권 프로파일을 받는다. 없으면 세 축이 스스로 `integration_pending` 을
선언하고, 그 상태에서 후보는 **전원 잔존한다**. 데이터가 없다는 사실이 "이 자리는 나쁘다"로
둔갑하지 않게 하는 것이 이 파일에서 가장 중요한 성질이다.

생존시기 축은 유일한 A등급 경로이고 인허가 이력 코호트를 요구한다. 코호트가 없는 동안
상권 집계로 대신 채우지 않는다 — 상권 폐업률은 '상권 안 동종 점포 중 이번 분기에 폐업한 비율'
이지 '이 매물이 폐업할 확률'이 아니며, 후자를 말하는 순간 B등급 데이터로 A등급 주장을 하게 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import AgentOutcome, AgentStatus, TeamReport
from .registry import spec

#: 서울 중앙값 대비 어느 비율부터 높다/낮다로 부를지. 데이터가 아니라 선언한 분류 기준이다.
HIGH_RATIO = 1.2
LOW_RATIO = 0.8

#: 목표매출이 상권 동종 분포에서 이 분위를 넘으면 "그 상권 상위 10%만큼 팔아야 성립"이라는 뜻이다.
#: 제안서 04장의 하드 탈락 규칙 — 분기점 미달.
TOP_DECILE = 0.9

_TRADE_AREA_PENDING = ("서울시 상권분석 프로파일이 없어 이 축을 판정하지 않았습니다. "
                       "판정하지 않은 축은 후보 탈락 근거로 쓰이지 않습니다.")
_SURVIVAL_PENDING = ("행정안전부 인허가 이력 코호트가 구축되지 않아 영업유지율을 판정하지 않았습니다. "
                     "상권 집계로 개별 점포의 생존을 대신 말하지 않습니다.")


@dataclass(frozen=True)
class LocationReport(TeamReport):
    """팀 보고 + 축소 결과. 탈락은 언제나 사유와 함께 나간다."""

    surviving: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)


def _band_of(value: float) -> str:
    if value >= HIGH_RATIO:
        return "HIGH"
    return "LOW" if value <= LOW_RATIO else "MID"


class LocationTeam:
    team = "location"
    name = "입지추천 팀"

    def __init__(self, *, trade_area: Any | None = None,
                 stress_check: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None):
        self.trade_area = trade_area
        self.stress_check = stress_check

    @property
    def profiles_available(self) -> bool:
        return bool(self.trade_area is not None and getattr(self.trade_area, "available", False))

    def run(self, candidates: list[dict[str, Any]], conditions: dict[str, Any]) -> LocationReport:
        industry = conditions.get("industry", "")
        profiles = self._profiles(candidates, industry)
        outcomes = [
            self._axis("location.demand", profiles, "demand_index",
                       lambda value: _band_of(value)),
            # 경쟁은 방향이 반대다 — 지수가 높을수록 불리하므로 등급을 뒤집는다.
            self._axis("location.competition", profiles, "competition_index",
                       lambda value: {"HIGH": "LOW", "LOW": "HIGH"}.get(_band_of(value), "MID")),
            self._viability(profiles),
            self._survival(),
        ]
        surviving, dropped = self._narrow(candidates, profiles, outcomes)
        return LocationReport(team=self.team, name=self.name, outcomes=outcomes, blocking=False,
                              surviving=surviving, dropped=dropped)

    def _profiles(self, candidates: list[dict[str, Any]], industry: str) -> dict[str, dict[str, Any]]:
        """판정할 수 있는 후보만 담는다. 프로파일이 없는 후보는 여기 들어오지 않는다."""
        if not self.profiles_available:
            return {}
        found: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            profile = self.trade_area.profile(candidate.get("admin_dong", ""), industry)
            if profile:
                found[candidate["id"]] = profile
        return found

    def _axis(self, key: str, profiles: dict[str, dict[str, Any]], field_name: str,
              grade_of: Callable[[float], str]) -> AgentOutcome:
        declaration = spec(key)
        if not self.profiles_available:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_TRADE_AREA_PENDING)
        by_candidate = {}
        for candidate_id, profile in profiles.items():
            value = profile.get(field_name)
            if not isinstance(value, (int, float)):
                continue
            by_candidate[candidate_id] = {
                "value": float(value), "band": grade_of(float(value)),
                "evidence_grade": declaration.evidence_grade,
                "quarter": profile.get("quarter"),
            }
        return declaration.outcome(AgentStatus.OK, data={"by_candidate": by_candidate})

    def _viability(self, profiles: dict[str, dict[str, Any]]) -> AgentOutcome:
        declaration = spec("location.viability")
        if not self.profiles_available:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_TRADE_AREA_PENDING)
        by_candidate = {}
        for candidate_id, profile in profiles.items():
            percentile = profile.get("revenue_percentile")
            if not isinstance(percentile, (int, float)):
                continue
            by_candidate[candidate_id] = {
                "value": float(percentile),
                "band": "LOW" if float(percentile) > TOP_DECILE else _band_of(1.0 - float(percentile) + 0.5),
                "above_top_decile": float(percentile) > TOP_DECILE,
                "evidence_grade": declaration.evidence_grade,
                "quarter": profile.get("quarter"),
            }
        return declaration.outcome(AgentStatus.OK, data={"by_candidate": by_candidate})

    def _survival(self) -> AgentOutcome:
        return spec("location.survival").outcome(
            AgentStatus.INTEGRATION_PENDING, message=_SURVIVAL_PENDING,
            required_actions=["행정안전부 지방행정 인허가데이터로 개업·폐업 코호트를 구축해야 합니다."])

    def _narrow(self, candidates: list[dict[str, Any]], profiles: dict[str, dict[str, Any]],
                outcomes: list[AgentOutcome]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """사유가 있는 것만 탈락시킨다. 개수는 고정하지 않는다.

        판정하지 못한 축(`active` 가 아닌 것)은 이 함수가 아예 읽지 않는다."""
        viability = next(item for item in outcomes if item.key == "location.viability")
        viable = viability.data.get("by_candidate", {}) if viability.active else {}

        surviving, dropped = [], []
        for candidate in candidates:
            reason = self._hard_drop_reason(candidate, viable.get(candidate["id"]))
            if reason:
                dropped.append({**candidate, "reason": reason})
            else:
                surviving.append(candidate)
        return surviving, dropped

    def _hard_drop_reason(self, candidate: dict[str, Any],
                          viability: dict[str, Any] | None) -> str | None:
        if viability and viability.get("above_top_decile"):
            return ("목표매출이 상권 동종 상위 10% 경계를 넘어 분기점 미달입니다 "
                    f"(분포 위치 {viability['value']:.0%}).")
        if self.stress_check is not None:
            verdict = self.stress_check(candidate)
            if verdict is not None and not verdict.get("passes", True):
                months = verdict.get("runway_months")
                tail = f" ({months}개월 내 소진)" if months is not None else ""
                return f"매출 −20% 스트레스에서 현금이 버티지 못합니다{tail}."
        return None
