"""메인 에이전트.

제안서 04장의 실행 순서를 그대로 코드로 옮긴 것이 `run()` 이다:

    조건 확정 → 금융처방(후보 무관 1회) → 권장 밴드로 자동 진행 → 입지추천 → 축소 → 타이밍(잔존만)

되먹임 방향이 이 순서를 정한다. 입지를 먼저 뽑으면 무엇이 노이즈인지 판정할 기준이 없다 —
조달 상한을 모르는 상태에서는 감당 불가한 후보를 걸러낼 수 없기 때문이다. 그래서 금융이
선행해 기준선을 만들고, 입지가 그 선을 넘을 수 있는지 증명한다.

게이트는 두 개뿐이고 둘 다 팀이 스스로 선언한다(`TeamReport.halted`). 메인은 그 선언을 읽고
멈출 뿐, 팀의 판정에 개입하지 않는다.

── 메인이 쓰는 자유 문장과 그 가드 ────────────────────────────────────────

메인은 12개 중 유일하게 문장을 쓴다. 그래서 여기서는 가드 1이 문법이 아니라 **후처리**로
구현된다 — 제안서 06장의 "근거 표시가 없는데 숫자를 포함한 문장은 후처리로 제거". 팀이 낸
수치 집합을 `quoted_numbers` 로 모으고, 그 집합에 없는 숫자가 든 문장을 `strip_unsourced_numbers`
가 통째로 버린다. 문장을 잃는 쪽이 틀린 수치를 남기는 쪽보다 낫다는 판단이고, 버려진 문장은
`narrative_dropped` 로 함께 저장되어 무엇이 걸러졌는지 확인할 수 있다.

`summary` 는 지금도 팀이 산출한 값을 **골라 담기만** 한다. 이 파일에는 산술이 없다.

실행은 비동기다 — 팀마다 모델 호출이 한 번씩 끼기 때문이고, 그 대기를 팀 경계에 두어야
SSE 진행 표시가 실제 진행을 따라간다. 실행당 호출 상한(`RunBudget`)은 실행 시작마다 초기화된다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .contracts import AgentStatus, TeamReport
from .llm import AgentLLM, RunBudget
from .registry import AGENT_SPECS, spec

#: 문장 분리. 마침표·물음표·느낌표·줄바꿈에서 끊는다.
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)
#: 문장에서 숫자를 찾는다. 천단위 쉼표는 숫자의 일부로 본다 — 쉼표를 경계로 보면
#: "1,234,567"이 "1"·"234"·"567"로 쪼개져 근거 없는 수치가 통과한다.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


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


def quoted_numbers(payload: Any) -> set[str]:
    """팀 산출물 안에 실제로 있는 수치를 문자열 집합으로 모은다.

    비율은 백분율 표기도 함께 허용한다 — 팀이 0.2 로 낸 값을 문장에서 20% 로 쓰는 것은
    인용이지 창작이 아니다. `bool` 은 제외한다: 파이썬에서 True 는 1 이므로 숫자로 세면
    근거 없는 "1"이 통과하게 된다."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int):
            found.add(str(value))
        elif isinstance(value, float):
            found.add(str(int(value)) if value.is_integer() else str(value))
            if 0 < abs(value) < 1:
                found.add(str(int(round(value * 100))))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(payload)
    return found


def strip_unsourced_numbers(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """허용된 수치만 남긴다. 그 밖의 숫자가 든 문장은 통째로 버린다."""
    kept, dropped = [], []
    for match in _SENTENCE.finditer(text or ""):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        numbers = [item.replace(",", "") for item in _NUMBER.findall(sentence)]
        if all(number in allowed for number in numbers):
            kept.append(sentence)
        else:
            dropped.append(sentence)
    return " ".join(kept), dropped


class MainAgent:
    def __init__(self, *, conditions, finance, location, timing,
                 llm: AgentLLM | None = None, budget: RunBudget | None = None):
        self.conditions = conditions
        self.finance = finance
        self.location = location
        self.timing = timing
        self.llm = llm
        self.budget = budget
        self._last: RunResult | None = None

    async def run(self, conditions: dict[str, Any],
                  candidates: list[dict[str, Any]]) -> RunResult:
        """진행 이벤트를 버리고 결과만 받는 편의 경로. 실행 순서는 `run_events` 하나에만 있다."""
        result: RunResult | None = None
        async for event in self.run_events(conditions, candidates):
            if event["event"] == "done":
                result = event["result"]
        assert result is not None  # run_events 는 언제나 done 으로 끝난다
        return result

    async def run_events(self, conditions: dict[str, Any], candidates: list[dict[str, Any]]):
        """팀·에이전트 단위 진행을 내보내며 실행한다.

        제안서 04장 — 15회 호출은 20~40초이므로 진행 표시가 필수이며, 그것이 12개 전문 분석이
        실제로 돌았다는 시각적 근거이기도 하다. 그래서 결과만 주는 API 를 따로 두지 않고
        이 제너레이터가 유일한 실행 경로다."""
        fingerprint = _fingerprint(conditions, candidates)
        yield {"event": "run_start", "total_agents": len(AGENT_SPECS), "fingerprint": fingerprint}

        if self._last is not None and self._last.fingerprint == fingerprint:
            # 같은 조건이면 팀을 다시 돌리지 않는다(가드 2). 재실행은 조건이 바뀔 때만 일어난다.
            # 모델 호출도 이 경로에서는 한 번도 일어나지 않는다 — 같은 조건에 다른 답이 나오는
            # 유일한 경로를 막는 것이 이 캐시의 목적이다.
            reused = RunResult(**{**self._last.__dict__, "reused": True})
            yield {"event": "done", "result": reused}
            return

        if self.budget is not None:
            self.budget.reset()
        reports: list[TeamReport] = []

        settled = await self.conditions.arun(conditions)
        for event in self._team_events(settled):
            yield event
        reports.append(settled)
        if settled.halted:
            async for event in self._close(fingerprint, reports, halted_at="condition",
                                           questions=list(settled.questions)):
                yield event
            return

        # 발화에서 읽어 채운 값이 있으면 후속 팀은 그것까지 반영된 조건을 본다.
        confirmed = settled.conditions or conditions

        prescription = await self.finance.arun(confirmed)
        for event in self._team_events(prescription):
            yield event
        reports.append(prescription)
        if prescription.halted:
            async for event in self._close(fingerprint, reports, halted_at="finance"):
                yield event
            return

        # 권장 밴드로 자동 진행한다 — 사용자를 여기서 세우지 않는다(제안서 04장).
        narrowed = await self.location.arun(candidates, confirmed)
        for event in self._team_events(narrowed):
            yield event
        reports.append(narrowed)

        scheduled = await self.timing.arun(narrowed.surviving)
        for event in self._team_events(scheduled):
            yield event
        reports.append(scheduled)

        async for event in self._close(fingerprint, reports, surviving=scheduled.surviving,
                                       dropped=list(narrowed.dropped),
                                       summary=self._summary(prescription)):
            yield event

    async def _close(self, fingerprint: str, reports: list[TeamReport], **rest: Any):
        """메인 에이전트가 마지막으로 자기 보고를 낸다.

        메인도 일을 한다 — 팀 보고를 모아 수치 카드와 설명문을 만드는 것이 그 일이고,
        제안서 03장에서 12개 중 하나로 세어진다. 스스로 결과를 내지 않으면 화면에는 11개만
        도착한다. 멈춘 실행에서는 통합할 것이 없으므로 `ok` 가 아니라 유보다 — 통합했다고
        말하면 존재하지 않는 종합 판단이 있었던 것처럼 읽힌다."""
        halted_at = rest.get("halted_at")
        summary = rest.get("summary") or {}
        surviving = rest.get("surviving") or []
        dropped = rest.get("dropped") or []
        data: dict[str, Any] = {"summary": summary, "surviving_count": len(surviving),
                                "dropped_count": len(dropped)}
        if not halted_at:
            data.update(await self._narrate(reports, summary, surviving, dropped))
        outcome = spec("main.integrate").outcome(
            AgentStatus.WITHHELD if halted_at else AgentStatus.OK,
            message=(f"{halted_at} 단계에서 멈춰 종합할 팀 보고가 없습니다." if halted_at else None),
            data=data)
        report = TeamReport(team="main", name="메인 에이전트", outcomes=[outcome], blocking=False)
        for event in self._team_events(report):
            yield event
        reports.append(report)
        yield {"event": "done", "result": self._finish(fingerprint, reports, **rest)}

    async def _narrate(self, reports: list[TeamReport], summary: dict[str, Any],
                       surviving: list[dict[str, Any]],
                       dropped: list[dict[str, Any]]) -> dict[str, Any]:
        """설명문을 받고, 팀이 내지 않은 수치가 든 문장을 버린다."""
        if self.llm is None:
            return {}
        # `data` 만 훑는다 — 에이전트가 실제로 산출한 수치가 거기 있고, 그것만이 인용 가능한
        # 근거다. 보고 객체 자체를 넘기면 데이터클래스라 아무것도 걷히지 않는다.
        allowed = quoted_numbers([outcome.data for report in reports
                                  for outcome in report.outcomes])
        allowed |= quoted_numbers({"surviving": len(surviving), "dropped": len(dropped)})
        narration = await self.llm.narrate(
            agent_key="main.integrate",
            instruction=("팀들이 낸 결과를 사용자에게 설명하세요. 입력에 있는 숫자만 그대로 옮겨 적고, "
                         "판정하지 못한 축은 확인하지 못했다고 쓰세요."),
            context={"권장 조달선 산출": summary,
                     "남은 후보 수": len(surviving), "탈락 후보 수": len(dropped),
                     "탈락 사유": [item.get("reason") for item in dropped],
                     "판정하지 못한 축": [{"이름": item.name, "사유": item.message}
                                  for report in reports for item in report.outcomes
                                  if item.status is not AgentStatus.OK]})
        text, removed = strip_unsourced_numbers(narration.text, allowed)
        return {"narrative": text, "narrative_dropped": removed,
                "narrative_source": narration.source}

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
