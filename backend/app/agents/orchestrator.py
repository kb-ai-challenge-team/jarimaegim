"""메인 에이전트.

제안서 04장의 실행 순서를 그대로 코드로 옮긴 것이 `run()` 이다:

    조건 확정 → 금융처방(후보 무관 1회) → 권장 밴드로 자동 진행 → 입지추천 → 축소 → 타이밍(잔존만)

되먹임 방향이 이 순서를 정한다. 입지를 먼저 뽑으면 무엇이 노이즈인지 판정할 기준이 없다 —
조달 상한을 모르는 상태에서는 감당 불가한 후보를 걸러낼 수 없기 때문이다. 그래서 금융이
선행해 기준선을 만들고, 입지가 그 선을 넘을 수 있는지 증명한다.

게이트는 두 개뿐이고 둘 다 팀이 스스로 선언한다(`TeamReport.halted`). 메인은 그 선언을 읽고
멈출 뿐, 팀의 판정에 개입하지 않는다.

메인 계약 — "수치 카드만 표시. 설명문을 지어내지 않는다." 그래서 `summary` 는 팀이 이미
산출한 값을 **골라 담기만** 하고, 이 파일에는 산술이 없다. 문장을 만드는 일(문서 초안)은
LLM 의 몫이지만 그 입력은 여기서 나온 수치뿐이다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .contracts import AgentStatus, TeamReport
from .registry import AGENT_SPECS


@dataclass(frozen=True)
class RunResult:
    fingerprint: str
    reports: list[TeamReport]
    activation: dict[str, Any]
    surviving: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, str]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    halted_at: str | None = None
    reused: bool = False


def _fingerprint(conditions: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    """가드 2의 재실행 금지를 판정하는 키. 조건과 후보 집합이 같으면 결과도 같아야 한다."""
    payload = json.dumps(
        {"conditions": {key: conditions[key] for key in sorted(conditions)},
         "candidates": sorted(str(item.get("id")) for item in candidates)},
        ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class MainAgent:
    def __init__(self, *, conditions, finance, location, timing):
        self.conditions = conditions
        self.finance = finance
        self.location = location
        self.timing = timing
        self._last: RunResult | None = None

    def run(self, conditions: dict[str, Any], candidates: list[dict[str, Any]]) -> RunResult:
        """진행 이벤트를 버리고 결과만 받는 편의 경로. 실행 순서는 `run_events` 하나에만 있다."""
        result: RunResult | None = None
        for event in self.run_events(conditions, candidates):
            if event["event"] == "done":
                result = event["result"]
        assert result is not None  # run_events 는 언제나 done 으로 끝난다
        return result

    def run_events(self, conditions: dict[str, Any], candidates: list[dict[str, Any]]):
        """팀·에이전트 단위 진행을 내보내며 실행한다.

        제안서 04장 — 15회 호출은 20~40초이므로 진행 표시가 필수이며, 그것이 12개 전문 분석이
        실제로 돌았다는 시각적 근거이기도 하다. 그래서 결과만 주는 API 를 따로 두지 않고
        이 제너레이터가 유일한 실행 경로다."""
        fingerprint = _fingerprint(conditions, candidates)
        yield {"event": "run_start", "total_agents": len(AGENT_SPECS), "fingerprint": fingerprint}

        if self._last is not None and self._last.fingerprint == fingerprint:
            # 같은 조건이면 팀을 다시 돌리지 않는다(가드 2). 재실행은 조건이 바뀔 때만 일어난다.
            reused = RunResult(**{**self._last.__dict__, "reused": True})
            yield {"event": "done", "result": reused}
            return

        reports: list[TeamReport] = []

        settled = self.conditions.run(conditions)
        yield from self._team_events(settled)
        reports.append(settled)
        if settled.halted:
            yield {"event": "done",
                   "result": self._finish(fingerprint, reports, halted_at="condition",
                                          questions=list(settled.questions))}
            return

        prescription = self.finance.run(conditions)
        yield from self._team_events(prescription)
        reports.append(prescription)
        if prescription.halted:
            yield {"event": "done",
                   "result": self._finish(fingerprint, reports, halted_at="finance")}
            return

        # 권장 밴드로 자동 진행한다 — 사용자를 여기서 세우지 않는다(제안서 04장).
        narrowed = self.location.run(candidates, conditions)
        yield from self._team_events(narrowed)
        reports.append(narrowed)

        scheduled = self.timing.run(narrowed.surviving)
        yield from self._team_events(scheduled)
        reports.append(scheduled)

        yield {"event": "done",
               "result": self._finish(fingerprint, reports, surviving=scheduled.surviving,
                                      dropped=list(narrowed.dropped),
                                      summary=self._summary(prescription))}

    @staticmethod
    def _team_events(report: TeamReport):
        yield {"event": "team_start", "team": report.team, "name": report.name,
               "agent_count": len(report.outcomes)}
        for outcome in report.outcomes:
            yield {"event": "agent_end", "team": report.team, "key": outcome.key,
                   "name": outcome.name, "status": outcome.status, "message": outcome.message}
        yield {"event": "team_end", "team": report.team, "active": report.active_count,
               "halted": report.halted}

    def _finish(self, fingerprint: str, reports: list[TeamReport], **rest: Any) -> RunResult:
        result = RunResult(fingerprint=fingerprint, reports=reports,
                           activation=self._activation(reports), **rest)
        self._last = result
        return result

    @staticmethod
    def _activation(reports: list[TeamReport]) -> dict[str, Any]:
        """화면의 "12개 축 중 N개 가동"(가드 3). 돌지 않은 팀의 축은 상태가 없으므로 None 이다 —
        비활성과 구분해야 "아직 순서가 오지 않았다"와 "원천이 없다"가 섞이지 않는다."""
        by_key: dict[str, AgentStatus | None] = {item.key: None for item in AGENT_SPECS}
        for report in reports:
            for outcome in report.outcomes:
                by_key[outcome.key] = outcome.status
        active = sum(1 for status in by_key.values() if status is AgentStatus.OK)
        return {"total": len(AGENT_SPECS), "active": active, "by_key": by_key}

    @staticmethod
    def _summary(prescription: TeamReport) -> dict[str, Any]:
        """팀이 낸 수치를 고르기만 한다. 여기서 새로 계산하는 값은 하나도 없다."""
        band = next((item for item in prescription.outcomes if item.key == "finance.band"), None)
        if band is None or not band.active:
            return {}
        recommended = next(line for line in band.data["bands"] if line["band"] == "RECOMMENDED")
        return {
            "recommended_ceiling_krw": recommended["ceiling_krw"],
            "monthly_repayment_krw": recommended["monthly_repayment_krw"],
            "target_monthly_revenue_krw": recommended["target_monthly_revenue_krw"],
            "target_daily_revenue_krw": recommended["target_daily_revenue_krw"],
            "runway_months": recommended["runway_months"],
            "required_capital_krw": band.data.get("required_capital_krw"),
        }
